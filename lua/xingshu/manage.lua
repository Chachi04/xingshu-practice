--- `:Xingshu deck`: every card in a picker, to edit, add or delete.
---
--- With Snacks: `<CR>` edits the card, `<C-n>` adds one, `<C-d>` deletes one
--- after asking. Without it, `vim.ui.select` offers the same through a
--- "new card" entry and an edit/delete prompt.
local deck = require("xingshu.deck")
local editor = require("xingshu.editor")

local M = {}

---@class xingshu.CardItem
---@field text string
---@field card xingshu.Card
---@field preview { text: string }?

---@param card xingshu.Card
---@return string
local function describe(card)
	local marks = (card.starred and "★" or " ") .. (card.learnt and "✓" or " ")
	return ("HSK %d · Set %-3d %s %s  %s"):format(card.hsk, card.set, marks, card.hanzi, card.pinyin)
end

---@param card xingshu.Card
---@return string
local function preview(card)
	return table.concat({
		"hanzi:   " .. card.hanzi,
		"pinyin:  " .. card.pinyin,
		"hsk:     " .. card.hsk,
		"set:     " .. card.set,
		"starred: " .. tostring(card.starred),
		"learnt:  " .. tostring(card.learnt),
		"id:      " .. card.id,
	}, "\n")
end

--- One item per card, in set order and file order within a set.
---@param cards xingshu.Card[]
---@return xingshu.CardItem[]
local function items(cards)
	local list = {}
	for _, set in ipairs(deck.sets(cards)) do
		for _, card in ipairs(set.cards) do
			table.insert(list, { text = describe(card), card = card })
		end
	end
	return list
end

--- Ask before deleting `card`, then reopen the list either way.
---@param card xingshu.Card
local function confirm_delete(card)
	local prompt = ("Delete %s (HSK %d · Set %d)?"):format(card.hanzi, card.hsk, card.set)
	vim.ui.select({ "Delete", "Cancel" }, { prompt = prompt }, function(choice)
		if choice ~= "Delete" then
			M.open()
			return
		end
		deck.remove(card, function(err)
			if err then
				vim.notify(("xingshu: could not delete card %s: %s"):format(card.id, err), vim.log.levels.ERROR)
			else
				vim.notify(("xingshu: deleted %s"):format(card.hanzi))
			end
			M.open()
		end)
	end)
end

--- The picker from `vim.ui.select`, for when Snacks is not installed.
---@param list xingshu.CardItem[]
local function select_fallback(list)
	local entries = { { text = "+ New card" } }
	vim.list_extend(entries, list)
	vim.ui.select(entries, {
		prompt = "Xingshu deck",
		format_item = function(entry)
			return entry.text
		end,
	}, function(entry)
		if entry == nil then
			return
		end
		if entry.card == nil then
			editor.open(nil)
			return
		end
		vim.ui.select({ "Edit", "Delete" }, { prompt = entry.card.hanzi }, function(action)
			if action == "Edit" then
				editor.open(entry.card)
			elseif action == "Delete" then
				confirm_delete(entry.card)
			end
		end)
	end)
end

--- Close the picker, then run `fn` once its windows are gone, or whatever
--- `fn` opens would open underneath them and lose focus.
---@param picker snacks.Picker
---@param fn fun()
local function after_close(picker, fn)
	picker:close()
	vim.schedule(fn)
end

--- Open the card list.
function M.open()
	deck.load(function(cards, err)
		if err then
			vim.notify(("xingshu: could not load cards: %s"):format(err), vim.log.levels.ERROR)
			return
		end
		if #cards == 0 then
			editor.open(nil)
			return
		end

		local list = items(cards)
		local ok, snacks = pcall(require, "snacks")
		if not (ok and snacks.picker) then
			select_fallback(list)
			return
		end

		for _, item in ipairs(list) do
			item.preview = { text = preview(item.card) }
		end
		local keys = {
			["<C-n>"] = { "xingshu_new", mode = { "n", "i" }, desc = "New card" },
			["<C-d>"] = { "xingshu_delete", mode = { "n", "i" }, desc = "Delete card" },
		}
		snacks.picker.pick({
			title = "Xingshu deck  (<C-n> new · <C-d> delete)",
			items = list,
			format = "text",
			preview = "preview",
			confirm = function(picker, item)
				after_close(picker, function()
					if item then
						editor.open(item.card)
					end
				end)
			end,
			actions = {
				xingshu_new = function(picker)
					after_close(picker, function()
						editor.open(nil)
					end)
				end,
				xingshu_delete = function(picker, item)
					if item == nil then
						return
					end
					after_close(picker, function()
						confirm_delete(item.card)
					end)
				end,
			},
			win = { input = { keys = keys }, list = { keys = keys } },
		})
	end)
end

return M
