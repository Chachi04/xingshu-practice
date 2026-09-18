--- Asking the `search` CLI for renderings, asynchronously and once per character.
local config = require("xingshu.config")

local M = {}

--- char -> list of renderings, including the empty list for a known miss.
---
--- Caching negatives matters as much as caching hits: without it, every
--- keystroke would re-ask about the same unindexed character, and typing would
--- spawn a process per stroke forever rather than only while the text is new.
---@type table<string, table[]>
local cache = {}

--- Split a string into characters, UTF-8 aware.
---@param text string
---@return string[]
function M.chars(text)
	if text == "" then
		return {}
	end
	return vim.fn.split(text, "\\zs")
end

--- Forget every cached lookup.
function M.reset()
	cache = {}
end

--- Assemble a result list for `text` out of the cache.
---@param text string
---@return { char: string, renderings: table[] }[]
local function from_cache(text)
	return vim.tbl_map(function(char)
		return { char = char, renderings = cache[char] or {} }
	end, M.chars(text))
end

--- Resolve every character of `text`, calling `on_done` with the results.
---
--- Only characters missing from the cache are sent to the CLI, so steady-state
--- typing costs nothing. `on_done` always runs on the main loop and always
--- receives one entry per input character, in order.
---
---@param text string
---@param on_done fun(results: { char: string, renderings: table[] }[], err: string?)
function M.query(text, on_done)
	local wanted = {}
	local seen = {}
	for _, char in ipairs(M.chars(text)) do
		if cache[char] == nil and not seen[char] then
			seen[char] = true
			table.insert(wanted, char)
		end
	end

	if #wanted == 0 then
		on_done(from_cache(text), nil)
		return
	end

	local cmd = vim.list_extend(vim.deepcopy(config.options.cmd), {
		"--json",
		table.concat(wanted),
	})

	-- vim.system() raises ENOENT synchronously when the binary is missing
	-- rather than reporting it through the callback, and a missing `uv` is the
	-- likeliest first-run failure -- so this must not escape as a stack trace.
	local spawned = pcall(vim.system, cmd, { text = true }, function(result)
		vim.schedule(function()
			local decoded = nil
			if result.stdout and result.stdout ~= "" then
				local ok, value = pcall(vim.json.decode, result.stdout)
				decoded = ok and value or nil
			end

			-- A non-zero exit is normal here: it only means some character was
			-- unindexed. Only treat it as a failure when nothing parsed, which
			-- is what a missing binary or an unloadable library looks like.
			if decoded == nil then
				local err = result.stderr
				if err == nil or err == "" then
					err = ("`%s` exited %d"):format(cmd[1], result.code)
				end
				on_done(from_cache(text), vim.trim(err))
				return
			end

			for _, entry in ipairs(decoded) do
				cache[entry.char] = entry.renderings
			end
			-- Characters the CLI dropped as punctuation never come back; cache
			-- them as misses so they are not requested again.
			for _, char in ipairs(wanted) do
				if cache[char] == nil then
					cache[char] = {}
				end
			end

			on_done(from_cache(text), nil)
		end)
	end)

	if not spawned then
		on_done(from_cache(text), ("could not run `%s`"):format(table.concat(cmd, " ")))
	end
end

return M
