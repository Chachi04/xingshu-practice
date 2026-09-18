--- Type Chinese characters, see how they are written in xingshu.
---
--- `:Xingshu` opens a floating input; renderings appear beneath it as you type,
--- fetched from this project's `search` CLI.
local backend = require("xingshu.backend")
local config = require("xingshu.config")
local render = require("xingshu.render")
local search = require("xingshu.search")
local ui = require("xingshu.ui")

local M = {}

---@type table? nil when the applet is closed
local state = nil

--- Whether the terminal can display images. nil until first asked.
---@type boolean?
local supported = nil

local augroup = vim.api.nvim_create_augroup("Xingshu", { clear = true })

--- Ask the terminal once whether it can show images.
---
--- The query blocks for up to a second waiting for a reply, so it must not run
--- at startup, and the answer is remembered for the session. A "no" is not
--- fatal: the applet falls back to listing paths, which still works over SSH.
---@return boolean
local function image_support()
	if supported == nil then
		local ok, reason = backend.supported()
		supported = ok
		if not ok then
			vim.notify(
				("xingshu: showing paths instead of images (%s)"):format(reason or "unsupported terminal"),
				vim.log.levels.WARN
			)
		end
	end
	return supported
end

--- Look the current input up and draw it.
local function refresh()
	if state == nil then
		return
	end

	local text = ui.text(state)
	if text == "" then
		render.clear(state)
		render.set_status(state, {})
		return
	end

	search.query(text, function(results, err)
		if state == nil then
			return
		end
		if err then
			render.clear(state)
			render.set_status(state, {}, err)
			return
		end
		if image_support() then
			render.render(state, results)
		else
			render.render_text(state, results)
		end
	end)
end

--- Schedule a refresh, collapsing bursts of keystrokes into one lookup.
local function schedule_refresh()
	if state == nil then
		return
	end
	if state.timer then
		state.timer:stop()
		state.timer:close()
	end
	state.timer = vim.uv.new_timer()
	state.timer:start(
		config.options.debounce_ms,
		0,
		vim.schedule_wrap(function()
			refresh()
		end)
	)
end

--- Close the applet, tearing images down before the windows they sit over.
function M.close()
	if state == nil then
		return
	end

	local closing = state
	state = nil

	if closing.timer then
		closing.timer:stop()
		closing.timer:close()
		closing.timer = nil
	end

	-- Images first: they are painted by the terminal, not by Nvim, so closing
	-- the windows underneath them would leave them on screen.
	render.clear(closing)
	ui.close(closing)
	vim.api.nvim_clear_autocmds({ group = augroup })
end

--- Open the applet, or focus it if it is already open.
function M.open()
	if state ~= nil then
		if state.input_win and vim.api.nvim_win_is_valid(state.input_win) then
			vim.api.nvim_set_current_win(state.input_win)
			return
		end
		M.close()
	end

	state = ui.open()

	vim.api.nvim_create_autocmd({ "TextChangedI", "TextChanged" }, {
		group = augroup,
		buffer = state.input_buf,
		callback = schedule_refresh,
	})

	vim.api.nvim_create_autocmd("VimResized", {
		group = augroup,
		callback = function()
			if state == nil then
				return
			end
			ui.resize(state)
			refresh()
		end,
	})

	-- Covers every way the window can go away that is not M.close(): :q, a
	-- window command, another plugin closing it. Without this the images would
	-- outlive the float.
	vim.api.nvim_create_autocmd({ "WinClosed", "BufWipeout" }, {
		group = augroup,
		buffer = state.input_buf,
		callback = function()
			vim.schedule(M.close)
		end,
	})

	for _, lhs in ipairs({ "<Esc>", "<C-c>" }) do
		vim.keymap.set({ "n", "i" }, lhs, M.close, { buffer = state.input_buf })
	end
	vim.keymap.set("n", "q", M.close, { buffer = state.input_buf })

	vim.cmd.startinsert()
end

--- Open the applet if closed, close it if open.
function M.toggle()
	if state == nil then
		M.open()
	else
		M.close()
	end
end

--- Configure the applet. Optional; defaults work inside this repo.
---@param opts table?
function M.setup(opts)
	config.setup(opts)
	search.reset()
	backend.reset()
	supported = nil
end

return M
