--- Choosing what to practise: a Snacks picker, or `vim.ui.select` without it.
local deck = require("xingshu.deck")

local M = {}

---@class xingshu.Choice
---@field text string what the picker shows and matches on
---@field title string title for the practice window
---@field cards xingshu.Card[]
---@field source xingshu.Source what to save, so the session can be continued
---@field preview { text: string }? filled in for Snacks only

--- Count cards for which `field` is true.
---@param cards xingshu.Card[]
---@param field string
---@return integer
local function count(cards, field)
	local n = 0
	for _, card in ipairs(cards) do
		if card[field] then
			n = n + 1
		end
	end
	return n
end

--- Everything that can be practised: the starred and learnt collections, then
--- every set. Empty collections are left out, since choosing one would do nothing.
---@param cards xingshu.Card[]
---@param hsk integer?
---@return xingshu.Choice[]
local function choices(cards, hsk)
	local pool = deck.filter(cards, { hsk = hsk })
	local level = hsk and (" · HSK %d"):format(hsk) or ""
	local items = {}

	local starred = deck.filter(pool, { starred = true })
	if #starred > 0 then
		table.insert(items, {
			text = ("★  All starred%s  (%d cards)"):format(level, #starred),
			title = "All starred" .. level,
			cards = starred,
			source = { kind = "starred", hsk = hsk },
		})
	end
	local learnt = deck.filter(pool, { learnt = true })
	if #learnt > 0 then
		table.insert(items, {
			text = ("✓  All learnt%s  (%d cards)"):format(level, #learnt),
			title = "All learnt" .. level,
			cards = learnt,
			source = { kind = "learnt", hsk = hsk },
		})
	end

	for _, set in ipairs(deck.sets(pool)) do
		local marks = ""
		local stars, known = count(set.cards, "starred"), count(set.cards, "learnt")
		if stars > 0 then
			marks = marks .. (", %d★"):format(stars)
		end
		if known > 0 then
			marks = marks .. (", %d✓"):format(known)
		end
		table.insert(items, {
			text = ("HSK %d · Set %-3d (%d cards%s)"):format(set.hsk, set.set, #set.cards, marks),
			title = ("HSK %d · Set %d"):format(set.hsk, set.set),
			cards = set.cards,
			source = { kind = "set", hsk = set.hsk, set = set.set },
		})
	end
	return items
end

--- The cards of a choice as preview text, so a set can be recognised before
--- it is opened.
---@param choice xingshu.Choice
---@return string
local function preview(choice)
	local lines = {}
	for _, card in ipairs(choice.cards) do
		local marks = (card.starred and "★" or " ") .. (card.learnt and "✓" or " ")
		table.insert(lines, ("%s %s  %s"):format(marks, card.hanzi, card.pinyin))
	end
	return table.concat(lines, "\n")
end

--- Ask which set to practise.
---@param cards xingshu.Card[]
---@param opts { hsk: integer? }
---@param on_choice fun(choice: xingshu.Choice)
function M.pick_set(cards, opts, on_choice)
	local items = choices(cards, opts.hsk)
	if #items == 0 then
		vim.notify("xingshu: no cards to practise", vim.log.levels.WARN)
		return
	end

	local ok, snacks = pcall(require, "snacks")
	if not (ok and snacks.picker) then
		vim.ui.select(items, {
			prompt = "Xingshu practice",
			format_item = function(item)
				return item.text
			end,
		}, function(item)
			if item then
				on_choice(item)
			end
		end)
		return
	end

	for _, item in ipairs(items) do
		item.preview = { text = preview(item) }
	end
	snacks.picker.pick({
		title = "Xingshu practice",
		items = items,
		format = "text",
		preview = "preview",
		confirm = function(picker, item)
			picker:close()
			if item then
				-- After the picker's windows are gone, or the practice float
				-- would open underneath them and lose focus.
				vim.schedule(function()
					on_choice(item)
				end)
			end
		end,
	})
end

return M
