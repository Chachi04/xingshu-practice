--- A card as a small buffer of `key: value` lines, saved on write.
---
--- Writing validates the fields and saves through the `practice` CLI, which
--- regenerates the pinyin from the hanzi. A write that fails leaves the buffer
--- modified, so `:wq` keeps the window and the text rather than losing both.
local config = require("xingshu.config")
local deck = require("xingshu.deck")

local M = {}

--- The fields shown, in order.
local fields = { "hanzi", "hsk", "set" }

--- Read the buffer back into card fields.
---@param lines string[]
---@return xingshu.CardFields?, string[] errors
local function parse(lines)
	local values = {}
	local errors = {}
	for i, line in ipairs(lines) do
		if vim.trim(line) ~= "" then
			local key, value = line:match("^%s*([%w_]+)%s*:%s*(.-)%s*$")
			if key == nil then
				table.insert(errors, ("line %d: expected `field: value`"):format(i))
			elseif not vim.tbl_contains(fields, key) then
				table.insert(errors, ("line %d: unknown field %q"):format(i, key))
			elseif values[key] ~= nil then
				table.insert(errors, ("line %d: %s given twice"):format(i, key))
			else
				values[key] = value
			end
		end
	end

	if values.hanzi == nil or values.hanzi == "" then
		table.insert(errors, "hanzi must not be empty")
	end
	for _, key in ipairs({ "hsk", "set" }) do
		local value = values[key]
		if value == nil or not value:match("^%d+$") or tonumber(value) == 0 then
			table.insert(errors, ("%s must be a positive integer"):format(key))
		end
	end

	if #errors > 0 then
		return nil, errors
	end
	return { hanzi = values.hanzi, hsk = tonumber(values.hsk), set = tonumber(values.set) }, errors
end

---@param card xingshu.Card?
---@return string
local function title(card)
	return card and (" Edit card %s "):format(card.id) or " New card "
end

--- Name the buffer after the card, so it shows what a write will change.
---@param buf integer
---@param card xingshu.Card?
local function name(buf, card)
	-- Fails if another editor already holds the name; the name is only a label.
	pcall(vim.api.nvim_buf_set_name, buf, "xingshu://card/" .. (card and card.id or "new"))
end

--- Open an editor for `card`, or for a new card when it is nil.
---@param card xingshu.Card?
function M.open(card)
	local buf = vim.api.nvim_create_buf(false, true)
	vim.bo[buf].buftype = "acwrite"
	vim.bo[buf].bufhidden = "wipe"
	vim.bo[buf].swapfile = false
	name(buf, card)
	vim.api.nvim_buf_set_lines(buf, 0, -1, false, {
		"hanzi: " .. (card and card.hanzi or ""),
		"hsk: " .. (card and card.hsk or ""),
		"set: " .. (card and card.set or ""),
	})
	vim.bo[buf].modified = false
	-- Highlighting only: a filetype would attach YAML language servers.
	vim.bo[buf].syntax = "yaml"

	local width = math.max(20, math.min(config.options.width, vim.o.columns - 4))
	local height = #fields
	local win = vim.api.nvim_open_win(buf, true, {
		relative = "editor",
		width = width,
		height = height,
		row = math.max(0, math.floor((vim.o.lines - height - 2) / 2)),
		col = math.floor((vim.o.columns - width) / 2),
		style = "minimal",
		border = config.options.border,
		title = title(card),
		title_pos = "center",
		footer = " :w save · :wq save and close · q close ",
		footer_pos = "center",
	})

	vim.api.nvim_create_autocmd("BufWriteCmd", {
		buffer = buf,
		callback = function()
			local values, errors = parse(vim.api.nvim_buf_get_lines(buf, 0, -1, false))
			if values == nil then
				vim.notify("xingshu: card not saved:\n" .. table.concat(errors, "\n"), vim.log.levels.ERROR)
				return
			end

			local saved, err
			if card then
				saved, err = deck.update(card, values)
			else
				saved, err = deck.add(values)
			end
			if saved == nil then
				vim.notify(("xingshu: card not saved: %s"):format(err), vim.log.levels.ERROR)
				return
			end

			-- From now on this buffer edits the saved card, so writing again
			-- after an add changes that card instead of adding another.
			local added = card == nil
			card = saved
			vim.bo[buf].modified = false
			if added then
				name(buf, card)
				if vim.api.nvim_win_is_valid(win) then
					vim.api.nvim_win_set_config(win, { title = title(card), title_pos = "center" })
				end
			end
			vim.notify(("xingshu: %s %s  %s"):format(added and "added" or "saved", card.hanzi, card.pinyin))
		end,
	})

	vim.keymap.set("n", "q", "<Cmd>quit<CR>", { buffer = buf, desc = "Close the card editor" })
	-- A picker may hand over in insert mode; a new card starts typing the hanzi.
	vim.api.nvim_win_set_cursor(win, { 1, 0 })
	if card then
		vim.cmd.stopinsert()
	else
		vim.cmd.startinsert({ bang = true })
	end
end

return M
