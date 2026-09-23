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
		local hsk, set = tonumber(args[1]), tonumber(args[2])
		if (args[1] and not hsk) or (args[2] and not set) then
			vim.notify("xingshu: usage: :Xingshu practice [hsk [set]]", vim.log.levels.ERROR)
			return
		end
		require("xingshu").practice({ hsk = hsk, set = set })
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
		vim.notify(("xingshu: unknown subcommand %q; try type or practice"):format(name), vim.log.levels.ERROR)
		return
	end
	run(vim.list_slice(cmd.fargs, 2))
end, {
	nargs = "*",
	desc = "Xingshu: random learnt card, `type` to look characters up, `practice` for flashcards",
	complete = function(arg_lead, cmdline)
		-- Only the first argument has fixed choices; levels and sets are numbers.
		local words = vim.split(vim.trim(cmdline), "%s+")
		if #words > (arg_lead == "" and 1 or 2) then
			return {}
		end
		return vim.tbl_filter(function(name)
			return vim.startswith(name, arg_lead)
		end, vim.tbl_keys(subcommands))
	end,
})
