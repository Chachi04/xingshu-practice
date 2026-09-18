--- Image output, with a tmux path that `vim.ui.img` does not provide.
---
--- Outside tmux this is a thin delegation to `vim.ui.img`, which works. Inside
--- tmux nothing works, because Nvim's Kitty backend writes raw APC sequences
--- straight to the terminal and tmux swallows them: `allow-passthrough` only
--- forwards the explicit `ESC Ptmux; ... ESC \` form. That is true of the
--- capability query too, which is why `_supported()` reports false rather than
--- the images merely failing to appear. Upstream acknowledges this only as a
--- `:checkhealth` warning ("tmux is detected. Images may not display
--- correctly") and the docs invite replacing the backend, which is what this is.
---
--- Two things have to change inside tmux:
---
--- * every sequence is wrapped for passthrough, with its own escapes doubled
--- * coordinates are shifted, because Nvim's rows and columns are relative to
---   its pane while Kitty places against the whole terminal
local config = require("xingshu.config")

local M = {}

---@type table<integer, integer> our placement id -> kitty image id
local placements = {}

--- Kitty ids, namespaced by pid the way Nvim's own backend does it so two
--- programs in one terminal do not fight over the same image.
local next_id = (function()
	local bit = require("bit")
	local base, count = nil, 0
	return function()
		if base == nil then
			local pid = vim.fn.getpid()
			base = bit.band(bit.bxor(pid, bit.rshift(pid, 5), bit.rshift(pid, 10)), 0x3FF)
		end
		count = count + 1
		return bit.bor(bit.lshift(base, 14), count)
	end
end)()

---@return boolean
local function in_tmux()
	return vim.env.TMUX ~= nil and vim.env.TMUX ~= ""
end

--- Run `tmux display-message -p` with a format string.
---@param format string
---@return string?
local function tmux_query(format)
	local ok, result = pcall(function()
		return vim.system({ "tmux", "display-message", "-p", format }, { text = true }):wait(1000)
	end)
	if not ok or result.code ~= 0 or not result.stdout then
		return nil
	end
	return vim.trim(result.stdout)
end

--- Build a Kitty graphics escape sequence.
---@param control table<string, string|integer>
---@param payload string?
---@return string
local function seq(control, payload)
	local pairs_out = {}
	for key, value in pairs(control) do
		table.insert(pairs_out, key .. "=" .. tostring(value))
	end

	local out = "\027_G" .. table.concat(pairs_out, ",")
	if payload and payload ~= "" then
		out = out .. ";" .. payload
	end
	return out .. "\027\\"
end

--- Wrap a sequence so tmux forwards it verbatim to the outer terminal.
---
--- Every ESC inside the payload must be doubled, including the one that ends
--- the sequence being wrapped; tmux un-doubles them on the way out.
---@param payload string
---@return string
local function passthrough(payload)
	return "\027Ptmux;" .. payload:gsub("\027", "\027\027") .. "\027\\"
end

---@param payload string
local function emit(payload)
	vim.api.nvim_ui_send(in_tmux() and passthrough(payload) or payload)
end

--- Screen offset of Nvim's top-left cell within the whole terminal.
---
--- `pane_top` is measured inside tmux's window area, which excludes the status
--- line, so a status line at the top shifts everything down by its height --
--- the difference between the client and window heights.
---@return integer row, integer col
local function offsets()
	if not in_tmux() then
		return 0, 0
	end

	local geometry = tmux_query("#{pane_top} #{pane_left} #{client_height} #{window_height}")
	if geometry == nil then
		return 0, 0
	end

	local top, left, client_height, window_height = geometry:match("^(%d+) (%d+) (%d+) (%d+)$")
	if top == nil then
		return 0, 0
	end

	local status = 0
	if tmux_query("#{status-position}") == "top" then
		status = tonumber(client_height) - tonumber(window_height)
	end

	return tonumber(top) + status, tonumber(left)
end

---@type boolean?
local supported_cache = nil

--- Whether images can be displayed.
---
--- Inside tmux the capability query cannot be used: the reply would have to
--- travel back through tmux to this pane, and it does not. Infer instead from
--- what tmux can be asked directly -- the terminal it is attached to, and
--- whether passthrough is enabled at all.
---@return boolean supported
---@return string? reason why not
function M.supported()
	if config.options.force_supported ~= nil then
		return config.options.force_supported
	end
	if supported_cache ~= nil then
		return supported_cache
	end

	if type(vim.ui) ~= "table" or type(vim.ui.img) ~= "table" then
		supported_cache = false
		return false, "vim.ui.img is unavailable; Nvim 0.13+ is required"
	end

	if not in_tmux() then
		local ok, result = pcall(vim.ui.img._supported)
		supported_cache = ok and result == true
		return supported_cache, supported_cache and nil or "terminal does not support the Kitty graphics protocol"
	end

	if tmux_query("#{?pane_in_mode,1,0}") == nil then
		supported_cache = false
		return false, "in tmux, but the tmux command is not runnable"
	end

	local passthrough_on = tmux_query("#{?#{==:#{allow-passthrough},off},off,on}")
	if passthrough_on == "off" then
		supported_cache = false
		return false, "tmux needs: set -g allow-passthrough on"
	end

	local term = tmux_query("#{client_termname}") or ""
	if not term:lower():find("kitty", 1, true) then
		supported_cache = false
		return false, ("tmux is attached to %q, which is not Kitty"):format(term)
	end

	supported_cache = true
	return true
end

--- Forget the cached capability answer.
function M.reset()
	supported_cache = nil
end

--- Send image bytes to the terminal in base64 chunks.
---@param img_id integer
---@param data string
local function transmit(img_id, data)
	local encoded = vim.base64.encode(data)
	local size = 4096
	local pos = 1

	while pos <= #encoded do
		local stop = math.min(pos + size - 1, #encoded)
		local last = stop >= #encoded
		local control = { m = last and 0 or 1 }

		if pos == 1 then
			control.f = 100 -- PNG
			control.a = "t" -- transmit only
			control.t = "d" -- direct
			control.i = img_id
			control.q = 2 -- suppress replies
		end

		emit(seq(control, encoded:sub(pos, stop)))
		pos = stop + 1
	end
end

--- Display an image. Mirrors `vim.ui.img.set` for new images only.
---@param data string PNG bytes
---@param opts table row/col/width/height/zindex, row and col 1-indexed
---@return integer id
function M.set(data, opts)
	if not in_tmux() then
		return vim.ui.img.set(data, opts)
	end

	local img_id = next_id()
	local placement_id = next_id()
	transmit(img_id, data)

	local row_offset, col_offset = offsets()
	local control = {
		a = "p",
		i = img_id,
		p = placement_id,
		C = 1, -- leave the cursor alone
		q = 2,
	}
	if opts.width then
		control.c = opts.width
	end
	if opts.height then
		control.r = opts.height
	end
	if opts.zindex then
		control.z = opts.zindex
	end

	-- The cursor move has to reach the outer terminal too: Kitty places at the
	-- real cursor, so this whole block travels as one passthrough payload.
	emit(
		"\0277"
			.. "\027[?25l"
			.. ("\027[%d;%dH"):format((opts.row or 1) + row_offset, (opts.col or 1) + col_offset)
			.. seq(control)
			.. "\0278"
			.. "\027[?25h"
	)

	placements[placement_id] = img_id
	return placement_id
end

--- Remove one image.
---@param id integer
---@return boolean
function M.del(id)
	if not in_tmux() then
		local ok, found = pcall(vim.ui.img.del, id)
		return ok and found or false
	end

	local img_id = placements[id]
	if img_id == nil then
		return false
	end

	emit(seq({ a = "d", d = "i", i = img_id, q = 2 }))
	placements[id] = nil
	return true
end

return M
