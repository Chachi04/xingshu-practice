--- Chinese characters in xingshu, in a float.
---
--- Three ways in, all sharing one pair of windows:
---
--- * `:Xingshu type`: a floating input; renderings appear beneath it as you
---   type, fetched from this project's `search` CLI.
--- * `:Xingshu practice [hsk [set]]`: flashcards from the `practice` deck,
---   pinyin first, flipping to the sentence in xingshu.
--- * `:Xingshu`: one random card from those marked learnt.
local backend = require("xingshu.backend")
local config = require("xingshu.config")
local deck = require("xingshu.deck")
local render = require("xingshu.render")
local search = require("xingshu.search")
local ui = require("xingshu.ui")

local M = {}

--- Only one applet exists at a time: images are placed at absolute screen
--- positions, so two floats would paint over each other.
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

--- Look `text` up and draw it on the canvas; "" clears it.
---
--- Lookups are asynchronous, so a slow answer can arrive after the text has
--- changed again. Each call bumps a generation and a reply is only drawn if it
--- is still the latest, or flipping a card back would not stick.
---@param text string
local function draw(text)
	if state == nil then
		return
	end
	state.generation = (state.generation or 0) + 1
	local generation = state.generation

	if text == "" then
		render.clear(state)
		render.set_status(state, {})
		return
	end

	search.query(text, function(results, err)
		if state == nil or state.generation ~= generation then
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

--- Look the current input up and draw it.
local function refresh()
	if state == nil then
		return
	end
	draw(ui.text(state))
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

	-- Autocmds before windows, so closing them does not re-enter here.
	vim.api.nvim_clear_autocmds({ group = augroup })
	-- Images first: they are painted by the terminal, not by Nvim, so closing
	-- the windows underneath them would leave them on screen.
	render.clear(closing)
	ui.close(closing)
end

--- Open fresh windows, replacing whatever was open, with the autocmds every
--- mode needs. The caller sets `state.redraw` and its own keys.
---@param ui_opts { title: string?, editable: boolean? }?
---@return table state
local function open(ui_opts)
	M.close()
	state = ui.open(ui_opts)

	vim.api.nvim_create_autocmd("VimResized", {
		group = augroup,
		callback = function()
			if state == nil then
				return
			end
			ui.resize(state)
			if state.redraw then
				state.redraw()
			end
		end,
	})

	-- Covers every way the window can go away that is not M.close(): :q, a
	-- window command, another plugin closing it. Without this the images would
	-- outlive the float. Scheduled, so by then another applet may have taken
	-- this one's place; that one is left alone.
	local owner = state
	vim.api.nvim_create_autocmd({ "WinClosed", "BufWipeout" }, {
		group = augroup,
		buffer = state.input_buf,
		callback = function()
			vim.schedule(function()
				if state == owner then
					M.close()
				end
			end)
		end,
	})

	return state
end

--- Open the typing applet, or focus it if it is already open.
function M.type()
	if state ~= nil and state.mode == "type" then
		if state.input_win and vim.api.nvim_win_is_valid(state.input_win) then
			vim.api.nvim_set_current_win(state.input_win)
			return
		end
	end

	open()
	state.mode = "type"
	state.redraw = refresh

	vim.api.nvim_create_autocmd({ "TextChangedI", "TextChanged" }, {
		group = augroup,
		buffer = state.input_buf,
		callback = schedule_refresh,
	})

	for _, lhs in ipairs({ "<Esc>", "<C-c>" }) do
		vim.keymap.set({ "n", "i" }, lhs, M.close, { buffer = state.input_buf })
	end
	vim.keymap.set("n", "q", M.close, { buffer = state.input_buf })

	vim.cmd.startinsert()
end

--- Kept for mappings made before `type` existed.
M.open = M.type

--- Open the typing applet, or close it if it is the one open. A card
--- session is replaced rather than closed, so `:Xingshu type` always types.
function M.toggle()
	if state ~= nil and state.mode == "type" then
		M.close()
	else
		M.type()
	end
end

--- Run through `cards` in the float.
---@param cards xingshu.Card[]
---@param title string
---@param opts { random_pool: xingshu.Card[]? }?
local function start_practice(cards, title, opts)
	open({ title = title, editable = false })
	state.mode = "practice"
	vim.cmd.stopinsert()
	require("xingshu.practice").attach(state, cards, opts or {}, { draw = draw, close = M.close })
end

--- Load the deck, reporting a failure rather than passing it on.
---@param on_loaded fun(cards: xingshu.Card[])
local function with_cards(on_loaded)
	deck.load(function(cards, err)
		if err then
			vim.notify(("xingshu: could not load cards: %s"):format(err), vim.log.levels.ERROR)
			return
		end
		on_loaded(cards)
	end)
end

--- Practise a set: straight away when both level and set are given,
--- otherwise through a picker narrowed to `hsk` if that is given.
---@param args { hsk: integer?, set: integer? }?
function M.practice(args)
	args = args or {}
	with_cards(function(cards)
		if args.hsk and args.set then
			local chosen = deck.filter(cards, { hsk = args.hsk, set = args.set })
			if #chosen == 0 then
				vim.notify(("xingshu: no cards in HSK %d set %d"):format(args.hsk, args.set), vim.log.levels.WARN)
				return
			end
			start_practice(chosen, ("HSK %d · Set %d"):format(args.hsk, args.set))
			return
		end

		require("xingshu.picker").pick_set(cards, { hsk = args.hsk }, function(choice)
			start_practice(choice.cards, choice.title)
		end)
	end)
end

--- Review one random learnt card; `n` draws another.
function M.random()
	with_cards(function(cards)
		local learnt = deck.filter(cards, { learnt = true })
		if #learnt == 0 then
			vim.notify(
				"xingshu: no learnt cards yet; mark some with L in :Xingshu practice, or `practice edit ID --learn`",
				vim.log.levels.INFO
			)
			return
		end
		local card = learnt[math.random(#learnt)]
		start_practice({ card }, "learnt", { random_pool = learnt })
	end)
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
