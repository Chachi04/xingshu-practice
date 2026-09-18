--- `:checkhealth xingshu` -- why images or lookups are not working.
local M = {}

--- Run a tmux format query, returning nil outside tmux or on failure.
---@param format string
---@return string?
local function tmux(format)
	local ok, result = pcall(function()
		return vim.system({ "tmux", "display-message", "-p", format }, { text = true }):wait(1000)
	end)
	if not ok or result.code ~= 0 then
		return nil
	end
	return vim.trim(result.stdout or "")
end

function M.check()
	local health = vim.health
	local backend = require("xingshu.backend")
	local config = require("xingshu.config")

	health.start("xingshu: images")

	if vim.fn.has("nvim-0.13") == 0 then
		health.warn("Nvim 0.13+ is needed for vim.ui.img; the applet falls back to printing paths")
	end

	backend.reset()
	local supported, reason = backend.supported()
	if supported then
		health.ok("images will display")
	else
		health.warn(("images unavailable: %s"):format(reason or "unknown"))
		health.info("the applet still works; it lists image paths instead")
	end

	if vim.env.TMUX then
		health.start("xingshu: tmux")
		health.info("Nvim's own backend writes raw APC, which tmux discards; this plugin wraps it")

		local passthrough = tmux("#{?#{==:#{allow-passthrough},off},off,on}")
		if passthrough == "off" then
			health.error("allow-passthrough is off", { "set -g allow-passthrough on" })
		else
			health.ok("allow-passthrough is on")
		end

		local term = tmux("#{client_termname}") or "?"
		if term:lower():find("kitty", 1, true) then
			health.ok(("tmux client terminal: %s"):format(term))
		else
			health.warn(("tmux client terminal is %q, not Kitty"):format(term))
		end

		local geometry = tmux("#{pane_top} #{pane_left} #{client_height} #{window_height}")
		health.info(("pane/client geometry: %s"):format(geometry or "unavailable"))
		health.info(("status-position: %s"):format(tmux("#{status-position}") or "unavailable"))
	end

	health.start("xingshu: search")
	local cmd = vim.list_extend(vim.deepcopy(config.options.cmd), { "--coverage" })
	local ok, result = pcall(function()
		return vim.system(cmd, { text = true }):wait(30000)
	end)

	if not ok or result == nil then
		health.error(("could not run: %s"):format(table.concat(cmd, " ")))
	elseif result.code ~= 0 then
		health.error(("`search --coverage` exited %d"):format(result.code), { vim.trim(result.stderr or "") })
	else
		health.ok(("search runs: %s"):format(table.concat(config.options.cmd, " ")))
		for line in vim.gsplit(vim.trim(result.stdout or ""), "\n") do
			health.info(line)
		end
	end
end

return M
