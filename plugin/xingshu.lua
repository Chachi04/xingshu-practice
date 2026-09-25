--- Command definition for the xingshu applet. Everything else loads on demand.
if vim.g.loaded_xingshu then
	return
end
vim.g.loaded_xingshu = true

local subcommands = {
	type = function()
		require("xingshu").toggle()
	end,
	practice = function(args)
		if args[1] == "continue" then
			require("xingshu").practice({ continue = true })
			return
		end
		local hsk, set = tonumber(args[1]), tonumber(args[2])
		if (args[1] and not hsk) or (args[2] and not set) then
			vim.notify("xingshu: usage: :Xingshu practice [hsk [set] | continue]", vim.log.levels.ERROR)
			return
		end
		require("xingshu").practice({ hsk = hsk, set = set })
	end,
	deck = function()
		require("xingshu").deck()
	end,
}

vim.api.nvim_create_user_command("Xingshu", function(cmd)
	local name = cmd.fargs[1]
	if name == nil then
		require("xingshu").random()
		return
	end
	local run = subcommands[name]
	if run == nil then
		vim.notify(("xingshu: unknown subcommand %q; try type, practice or deck"):format(name), vim.log.levels.ERROR)
		return
	end
	run(vim.list_slice(cmd.fargs, 2))
end, {
	nargs = "*",
	desc = "Xingshu: random learnt card, `type` to look characters up, `practice` for flashcards, `deck` to manage cards",
	complete = function(arg_lead, cmdline)
		-- The subcommand, then `continue` after `practice`; levels and sets are numbers.
		local words = vim.split(vim.trim(cmdline), "%s+")
		local position = #words - (arg_lead == "" and 0 or 1)
		local candidates = {}
		if position == 1 then
			candidates = vim.tbl_keys(subcommands)
		elseif position == 2 and words[2] == "practice" then
			candidates = { "continue" }
		end
		return vim.tbl_filter(function(name)
			return vim.startswith(name, arg_lead)
		end, candidates)
	end,
})
