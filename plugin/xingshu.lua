--- Command definition for the xingshu applet. Everything else loads on demand.
if vim.g.loaded_xingshu then
	return
end
vim.g.loaded_xingshu = true

vim.api.nvim_create_user_command("Xingshu", function()
	require("xingshu").toggle()
end, { desc = "Type Chinese characters and see them in xingshu" })
