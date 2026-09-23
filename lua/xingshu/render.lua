--- Laying images out on the canvas and handing them to `vim.ui.img`.
---
--- `vim.ui.img` positions are absolute terminal cells: the Kitty backend emits
--- a bare `ESC[row;colH` before placing. Images therefore do not scroll, do not
--- follow a window, and are not cleaned up by Nvim. Everything here exists to
--- keep placements aligned to a fixed float and to guarantee they are deleted.
local backend = require("xingshu.backend")
local config = require("xingshu.config")

local M = {}

--- Image height in cells for a given width.
---
--- The source PNGs are square (about 105x105) and a terminal cell is roughly
--- twice as tall as it is wide, so half the width keeps the character from
--- being stretched. Derived rather than configured so the two cannot disagree.
---@param cell_width integer
---@return integer
function M.cell_height(cell_width)
	return math.max(1, math.floor(cell_width / 2))
end

--- How many images fit across a canvas of the given width.
---@param canvas_width integer
---@param cell_width integer
---@param gap integer
---@return integer
function M.slots(canvas_width, cell_width, gap)
	return math.max(1, math.floor((canvas_width + gap) / (cell_width + gap)))
end

--- Total canvas height in cells for the configured layout.
---@param opts xingshu.Config
---@return integer
function M.canvas_height(opts)
	return M.cell_height(opts.cell_width) * opts.max_rows
end

--- Delete every image this state has placed, and any path list drawn in
--- their place.
---
--- Safe to call repeatedly and safe to call on a torn-down window: a stale id
--- simply returns false. Leaving one behind paints it over the editor until
--- the terminal is cleared, so this runs on every re-render and every close.
---@param state table
function M.clear(state)
	for _, id in ipairs(state.images or {}) do
		pcall(backend.del, id)
	end
	state.images = {}

	if state.text_drawn and state.canvas_buf and vim.api.nvim_buf_is_valid(state.canvas_buf) then
		local blank = {}
		for _ = 1, M.canvas_height(config.options) do
			table.insert(blank, "")
		end
		vim.bo[state.canvas_buf].modifiable = true
		vim.api.nvim_buf_set_lines(state.canvas_buf, 0, -1, false, blank)
		vim.bo[state.canvas_buf].modifiable = false
	end
	state.text_drawn = false
end

--- Read a PNG off disk as bytes.
---@param path string
---@return string?
local function read_png(path)
	local ok, data = pcall(vim.fn.readblob, path)
	if not ok or data == nil then
		return nil
	end
	return data
end

--- Screen cell of the canvas's top-left interior corner.
---
--- `screenpos()` maps a *buffer* position to a screen one, so its column
--- argument is a byte index into the line -- on the canvas's empty lines every
--- column collapses onto the first. Anchor on (1, 1), which always exists, and
--- offset from there; this still picks up the float's border and position,
--- which `nvim_win_get_position` would miss.
---@param win integer
---@return { row: integer, col: integer }?
local function origin(win)
	local pos = vim.fn.screenpos(win, 1, 1)
	if pos.row == 0 then
		return nil
	end
	return { row = pos.row, col = pos.col }
end

--- Place one image at a slot.
---@param state table
---@param anchor { row: integer, col: integer }
---@param index integer zero-based slot
---@param path string
---@param opts xingshu.Config
local function place(state, anchor, index, path, opts)
	local height = M.cell_height(opts.cell_width)
	local slots = M.slots(state.canvas_width, opts.cell_width, opts.gap)

	local line = math.floor(index / slots)
	if line >= opts.max_rows then
		return
	end

	local column = (index % slots) * (opts.cell_width + opts.gap)
	if column + opts.cell_width > state.canvas_width then
		return
	end

	local data = read_png(path)
	if data == nil then
		return
	end

	local ok, id = pcall(backend.set, data, {
		row = anchor.row + line * height,
		col = anchor.col + column,
		width = opts.cell_width,
		height = height,
		zindex = opts.zindex,
	})
	if ok then
		table.insert(state.images, id)
	end
end

--- Draw the results: images for hits, a marker line for misses.
---@param state table
---@param results { char: string, renderings: table[] }[]
function M.render(state, results)
	local opts = config.options
	M.clear(state)

	if not (state.canvas_win and vim.api.nvim_win_is_valid(state.canvas_win)) then
		return
	end

	local anchor = origin(state.canvas_win)
	local missing = {}
	for index, entry in ipairs(results) do
		local rendering = entry.renderings[1]
		if rendering and anchor then
			place(state, anchor, index - 1, rendering.path, opts)
		elseif not rendering then
			table.insert(missing, entry.char)
		end
	end

	M.set_status(state, missing)
end

--- Write the miss list (or an error) into the canvas buffer's last line.
---@param state table
---@param missing string[]
---@param err string?
function M.set_status(state, missing, err)
	if not (state.canvas_buf and vim.api.nvim_buf_is_valid(state.canvas_buf)) then
		return
	end

	local text = ""
	local hl = "DiagnosticWarn"
	if err then
		text = "error: " .. err:gsub("%s+", " ")
		hl = "DiagnosticError"
	elseif #missing > 0 then
		text = "not indexed: " .. table.concat(missing, " ")
	end

	vim.api.nvim_buf_clear_namespace(state.canvas_buf, state.ns, 0, -1)
	if text == "" then
		return
	end

	local last = vim.api.nvim_buf_line_count(state.canvas_buf) - 1
	vim.api.nvim_buf_set_extmark(state.canvas_buf, state.ns, last, 0, {
		virt_text = { { text, hl } },
		virt_text_pos = "overlay",
	})
end

--- Fallback for terminals without image support: list the paths as text.
---@param state table
---@param results { char: string, renderings: table[] }[]
function M.render_text(state, results)
	if not (state.canvas_buf and vim.api.nvim_buf_is_valid(state.canvas_buf)) then
		return
	end

	local lines = {}
	local missing = {}
	for _, entry in ipairs(results) do
		local rendering = entry.renderings[1]
		if rendering then
			table.insert(lines, ("%s  %s"):format(entry.char, rendering.path))
		else
			table.insert(missing, entry.char)
		end
	end

	local height = M.canvas_height(config.options)
	while #lines < height do
		table.insert(lines, "")
	end

	vim.bo[state.canvas_buf].modifiable = true
	vim.api.nvim_buf_set_lines(state.canvas_buf, 0, -1, false, lines)
	vim.bo[state.canvas_buf].modifiable = false
	state.text_drawn = true
	M.set_status(state, missing)
end

return M
