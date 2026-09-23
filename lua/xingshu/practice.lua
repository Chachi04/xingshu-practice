--- Flashcards in the applet's float: pinyin on the input line, xingshu below.
---
--- Mirrors the Python TUI's card screen. The window and image lifecycle stay in
--- init.lua; this module only decides what the float shows and wires the keys.
local deck = require("xingshu.deck")
local ui = require("xingshu.ui")

local M = {}

--- Punctuation the books do not index. Stripped before lookup so the canvas
--- shows only characters, instead of a "not indexed" line on every sentence.
--- A set rather than a pattern class: Lua classes match bytes, and most of
--- these are three bytes long.
local punctuation = {}
for _, char in ipairs(vim.fn.split("，。？！、；：“”‘’（）《》…—·,.?!;:\"'()", "\\zs")) do
	punctuation[char] = true
end

--- The characters of `hanzi` worth looking up.
---@param hanzi string
---@return string
local function characters(hanzi)
	local kept = {}
	for _, char in ipairs(vim.fn.split(hanzi, "\\zs")) do
		if not (punctuation[char] or char:find("^%s$")) then
			table.insert(kept, char)
		end
	end
	return table.concat(kept)
end

--- Pick a random card from `pool`, avoiding `current` when there is a choice.
---@param pool xingshu.Card[]
---@param current xingshu.Card?
---@return xingshu.Card?
local function draw_random(pool, current)
	local candidates = vim.tbl_filter(function(card)
		return card ~= current
	end, pool)
	if #candidates == 0 then
		candidates = pool
	end
	if #candidates == 0 then
		return nil
	end
	return candidates[math.random(#candidates)]
end

---@class xingshu.PracticeHooks
---@field draw fun(text: string) look `text` up and draw it; "" clears the canvas
---@field close fun() tear the applet down

--- Turn an open, read-only applet into a card session.
---
--- With `random_pool`, the session holds one card at a time and `n` draws
--- another from the pool rather than stepping through `cards`.
---@param state table from ui.open
---@param cards xingshu.Card[]
---@param opts { random_pool: xingshu.Card[]? }
---@param hooks xingshu.PracticeHooks
function M.attach(state, cards, opts, hooks)
	local session = { cards = cards, index = 1, flipped = false, pool = opts.random_pool }

	local function show()
		local card = session.cards[session.index]
		ui.set_line(state, card.pinyin)

		local position = session.pool and ("random of %d"):format(#session.pool)
			or ("%d / %d"):format(session.index, #session.cards)
		ui.set_footer(
			state,
			table.concat({
				position,
				card.starred and "★" or "☆",
				card.learnt and "✓ learnt" or "· new",
				session.flipped and "back" or "front",
			}, "   ")
		)

		hooks.draw(session.flipped and characters(card.hanzi) or "")
	end

	local function flip()
		session.flipped = not session.flipped
		show()
	end

	local function go_next()
		if session.pool then
			-- Unlearning a card mid-session takes it out of the rotation.
			session.pool = deck.filter(session.pool, { learnt = true })
			local card = draw_random(session.pool, session.cards[1])
			if card == nil then
				vim.notify("xingshu: no learnt cards left", vim.log.levels.INFO)
				return
			end
			session.cards = { card }
		elseif session.index < #session.cards then
			session.index = session.index + 1
		else
			vim.notify("xingshu: last card", vim.log.levels.INFO)
			return
		end
		session.flipped = false
		show()
	end

	local function previous()
		if session.pool or session.index <= 1 then
			return
		end
		session.index = session.index - 1
		session.flipped = false
		show()
	end

	---@param field "starred"|"learnt"
	local function toggle(field)
		local card = session.cards[session.index]
		deck.set_flag(card, field, not card[field], function(err)
			if not err and state.session == session then
				show()
			end
		end)
	end

	state.session = session
	state.redraw = show

	local maps = {
		[{ "<Space>", "<CR>" }] = flip,
		[{ "n", "l", "<Right>" }] = go_next,
		[{ "p", "h", "<Left>" }] = previous,
		[{ "s" }] = function()
			toggle("starred")
		end,
		[{ "L" }] = function()
			toggle("learnt")
		end,
		[{ "q", "<Esc>", "<C-c>" }] = hooks.close,
	}
	for lhs_list, rhs in pairs(maps) do
		for _, lhs in ipairs(lhs_list) do
			vim.keymap.set("n", lhs, rhs, { buffer = state.input_buf, nowait = true })
		end
	end

	show()
end

return M
