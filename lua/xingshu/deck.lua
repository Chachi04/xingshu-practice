--- The flashcards, read and changed through the `practice` CLI.
---
--- The Python side owns the card file: where it lives, how it is seeded, how
--- it is saved atomically. Going through the CLI rather than decoding the JSON
--- here means the TUI and the editor can never disagree about any of that.
local config = require("xingshu.config")

local M = {}

---@class xingshu.Card
---@field id string
---@field hanzi string
---@field pinyin string
---@field hsk integer
---@field set integer
---@field starred boolean
---@field learnt boolean

--- Run the `practice` CLI with extra arguments, calling `on_done` on the main loop.
---@param args string[]
---@param on_done fun(stdout: string?, err: string?)
local function run(args, on_done)
	local cmd = vim.list_extend(vim.deepcopy(config.options.practice_cmd), args)

	-- As in search.query: a missing binary raises instead of calling back.
	local spawned = pcall(vim.system, cmd, { text = true }, function(result)
		vim.schedule(function()
			if result.code ~= 0 then
				local err = vim.trim(result.stderr or "")
				if err == "" then
					err = ("`%s` exited %d"):format(cmd[1], result.code)
				end
				on_done(nil, err)
				return
			end
			on_done(result.stdout or "", nil)
		end)
	end)

	if not spawned then
		on_done(nil, ("could not run `%s`"):format(table.concat(cmd, " ")))
	end
end

--- Load every card.
---@param on_done fun(cards: xingshu.Card[]?, err: string?)
function M.load(on_done)
	run({ "list", "--json" }, function(stdout, err)
		if err then
			on_done(nil, err)
			return
		end
		local ok, cards = pcall(vim.json.decode, stdout)
		if not ok or type(cards) ~= "table" then
			on_done(nil, "`practice list --json` returned something that is not JSON")
			return
		end
		on_done(cards, nil)
	end)
end

--- Cards matching every given filter, in file order.
---@param cards xingshu.Card[]
---@param filter { hsk: integer?, set: integer?, starred: boolean?, learnt: boolean? }
---@return xingshu.Card[]
function M.filter(cards, filter)
	return vim.tbl_filter(function(card)
		return (filter.hsk == nil or card.hsk == filter.hsk)
			and (filter.set == nil or card.set == filter.set)
			and (not filter.starred or card.starred)
			and (not filter.learnt or card.learnt)
	end, cards)
end

--- Cards grouped by set, sets sorted by level then number.
---@param cards xingshu.Card[]
---@return { hsk: integer, set: integer, cards: xingshu.Card[] }[]
function M.sets(cards)
	local by_key = {}
	local sets = {}
	for _, card in ipairs(cards) do
		local key = card.hsk .. "-" .. card.set
		if by_key[key] == nil then
			by_key[key] = { hsk = card.hsk, set = card.set, cards = {} }
			table.insert(sets, by_key[key])
		end
		table.insert(by_key[key].cards, card)
	end
	table.sort(sets, function(a, b)
		if a.hsk ~= b.hsk then
			return a.hsk < b.hsk
		end
		return a.set < b.set
	end)
	return sets
end

--- CLI flag for setting each boolean field.
local flags = {
	starred = { [true] = "--star", [false] = "--unstar" },
	learnt = { [true] = "--learn", [false] = "--unlearn" },
}

--- Set a boolean field of a card and save it.
---
--- `card` is only changed once the CLI has saved, so what is shown never
--- claims something the file does not hold.
---@param card xingshu.Card
---@param field "starred"|"learnt"
---@param value boolean
---@param on_done fun(err: string?)?
function M.set_flag(card, field, value, on_done)
	run({ "edit", card.id, flags[field][value] }, function(_, err)
		if err then
			vim.notify(("xingshu: could not save card %s: %s"):format(card.id, err), vim.log.levels.ERROR)
		else
			card[field] = value
		end
		if on_done then
			on_done(err)
		end
	end)
end

return M
