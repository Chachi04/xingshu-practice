--- The two floating windows: a one-line input and the image canvas below it.
---
--- They are separate windows on purpose. Images are painted over the canvas at
--- absolute screen positions and Nvim knows nothing about them, so the cursor
--- must never be in there -- a single window holding both would put it there
--- every time you moved left from the input line.
local config = require("xingshu.config")
local render = require("xingshu.render")

local M = {}

--- Geometry for both windows, centred horizontally and above centre vertically.
---@param opts xingshu.Config
---@param title string?
---@return table input, table canvas, integer canvas_width
local function layout(opts, title)
	local width = math.max(20, math.min(opts.width, vim.o.columns - 4))
	local canvas_height = render.canvas_height(opts)
	local total = canvas_height + 4 -- both borders plus the input line
	local row = math.max(0, math.floor((vim.o.lines - total) / 2))
	local col = math.floor((vim.o.columns - width) / 2)

	local input = {
		relative = "editor",
		width = width,
		height = 1,
		row = row,
		col = col,
		style = "minimal",
		border = opts.border,
		title = (" %s "):format(title or "xingshu"),
		title_pos = "center",
		zindex = 50,
	}
	local canvas = {
		relative = "editor",
		width = width,
		height = canvas_height,
		row = row + 3,
		col = col,
		style = "minimal",
		border = opts.border,
		focusable = false,
		zindex = 50,
	}
	return input, canvas, width
end

--- Create both windows and their scratch buffers.
---
--- With `editable = false` the input line is display-only: the caller fills
--- it with `set_line`, and typing into it does nothing.
---@param ui_opts { title: string?, editable: boolean? }?
---@return table state
function M.open(ui_opts)
	ui_opts = ui_opts or {}
	local opts = config.options
	local input_cfg, canvas_cfg, width = layout(opts, ui_opts.title)

	local input_buf = vim.api.nvim_create_buf(false, true)
	vim.bo[input_buf].bufhidden = "wipe"
	vim.bo[input_buf].filetype = "xingshu"
	if ui_opts.editable == false then
		vim.bo[input_buf].modifiable = false
	end

	local canvas_buf = vim.api.nvim_create_buf(false, true)
	vim.bo[canvas_buf].bufhidden = "wipe"
	local blank = {}
	for _ = 1, render.canvas_height(opts) do
		table.insert(blank, "")
	end
	vim.api.nvim_buf_set_lines(canvas_buf, 0, -1, false, blank)
	vim.bo[canvas_buf].modifiable = false

	local input_win = vim.api.nvim_open_win(input_buf, true, input_cfg)
	local canvas_win = vim.api.nvim_open_win(canvas_buf, false, canvas_cfg)
	vim.wo[canvas_win].winhl = "Normal:NormalFloat"

	return {
		input_buf = input_buf,
		input_win = input_win,
		canvas_buf = canvas_buf,
		canvas_win = canvas_win,
		canvas_width = width,
		title = ui_opts.title,
		ns = vim.api.nvim_create_namespace("xingshu"),
		images = {},
	}
end

--- Reposition both windows after the editor is resized.
---@param state table
function M.resize(state)
	local input_cfg, canvas_cfg, width = layout(config.options, state.title)
	if state.footer then
		canvas_cfg.footer = state.footer
		canvas_cfg.footer_pos = "right"
	end
	if state.input_win and vim.api.nvim_win_is_valid(state.input_win) then
		vim.api.nvim_win_set_config(state.input_win, input_cfg)
	end
	if state.canvas_win and vim.api.nvim_win_is_valid(state.canvas_win) then
		vim.api.nvim_win_set_config(state.canvas_win, canvas_cfg)
	end
	state.canvas_width = width
end

--- The text currently typed into the input line.
---@param state table
---@return string
function M.text(state)
	if not (state.input_buf and vim.api.nvim_buf_is_valid(state.input_buf)) then
		return ""
	end
	local lines = vim.api.nvim_buf_get_lines(state.input_buf, 0, 1, false)
	return lines[1] or ""
end

--- Replace the input line, even when it is not editable.
---@param state table
---@param text string
function M.set_line(state, text)
	if not (state.input_buf and vim.api.nvim_buf_is_valid(state.input_buf)) then
		return
	end
	local modifiable = vim.bo[state.input_buf].modifiable
	vim.bo[state.input_buf].modifiable = true
	vim.api.nvim_buf_set_lines(state.input_buf, 0, -1, false, { text })
	vim.bo[state.input_buf].modifiable = modifiable
end

--- Show a short status in the canvas's bottom border.
---@param state table
---@param text string
function M.set_footer(state, text)
	state.footer = (" %s "):format(text)
	if state.canvas_win and vim.api.nvim_win_is_valid(state.canvas_win) then
		vim.api.nvim_win_set_config(state.canvas_win, { footer = state.footer, footer_pos = "right" })
	end
end

--- Close both windows. Images are torn down by the caller first.
---@param state table
function M.close(state)
	for _, win in ipairs({ state.input_win, state.canvas_win }) do
		if win and vim.api.nvim_win_is_valid(win) then
			pcall(vim.api.nvim_win_close, win, true)
		end
	end
end

return M
