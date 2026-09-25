--- The last practice session, kept on disk so `:Xingshu practice continue`
--- can pick it up again.
---
--- Only which cards were chosen is saved, not the cards themselves: the list is
--- rebuilt from the deck on continue, so edits made since are not lost.
local deck = require("xingshu.deck")

local M = {}

---@class xingshu.Source
---@field kind "set"|"starred"|"learnt"
---@field hsk integer? required for "set", optional otherwise
---@field set integer? "set" only

---@class xingshu.Session
---@field source xingshu.Source
---@field title string
---@field card_id string the card on screen when last saved
---@field index integer its position then, for when the card is gone

--- Where the session lives. State rather than cache: cache may be wiped.
---@return string
function M.path()
	return vim.fs.joinpath(vim.fn.stdpath("state"), "xingshu", "last_practice.json")
end

--- Whether a failed save has been reported, so a broken directory does not
--- warn on every card.
local warned = false

--- Save `entry` as the session to continue.
---@param entry xingshu.Session
function M.save(entry)
	local path = M.path()
	local ok, err = pcall(function()
		vim.fn.mkdir(vim.fs.dirname(path), "p")
		if vim.fn.writefile({ vim.json.encode(entry) }, path) ~= 0 then
			error("could not write " .. path)
		end
	end)
	if not ok and not warned then
		warned = true
		vim.notify(("xingshu: could not save practice session: %s"):format(err), vim.log.levels.WARN)
	end
end

--- The saved session, or nil when there is none worth continuing.
---@return xingshu.Session?
function M.load()
	local ok, lines = pcall(vim.fn.readfile, M.path())
	if not ok or #lines == 0 then
		return nil
	end
	local decoded, entry = pcall(vim.json.decode, table.concat(lines, "\n"))
	if not decoded or type(entry) ~= "table" or type(entry.source) ~= "table" then
		return nil
	end
	local kind = entry.source.kind
	if kind ~= "set" and kind ~= "starred" and kind ~= "learnt" then
		return nil
	end
	return entry
end

--- The cards `source` picks out of the deck, in file order.
---@param cards xingshu.Card[]
---@param source xingshu.Source
---@return xingshu.Card[]
function M.cards(cards, source)
	return deck.filter(cards, {
		hsk = source.hsk,
		set = source.kind == "set" and source.set or nil,
		starred = source.kind == "starred" or nil,
		learnt = source.kind == "learnt" or nil,
	})
end

--- Where to resume in `list`: the saved card if it is still there, otherwise
--- the saved position, kept inside the list.
---@param list xingshu.Card[]
---@param entry xingshu.Session
---@return integer
function M.start_index(list, entry)
	for i, card in ipairs(list) do
		if card.id == entry.card_id then
			return i
		end
	end
	return math.max(1, math.min(tonumber(entry.index) or 1, #list))
end

return M
