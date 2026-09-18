--- Defaults and user configuration for the xingshu applet.
local M = {}

--- Absolute path to this repository, found by walking up from this file.
---
--- The plugin ships inside the Python project it drives, so the repo root is
--- also the `--project` directory `uv` needs. Deriving it beats hardcoding a
--- path that breaks the moment the checkout moves.
---@return string
local function repo_root()
	local this = debug.getinfo(1, "S").source:sub(2)
	return vim.fs.root(this, "pyproject.toml") or vim.fn.fnamemodify(this, ":h:h:h")
end

---@class xingshu.Config
---@field cmd string[] argv prefix for the `search` CLI
---@field cell_width integer image width in terminal cells
---@field gap integer blank cells between images
---@field max_rows integer rows of images before the canvas stops growing
---@field debounce_ms integer quiet period before a keystroke triggers a lookup
---@field zindex integer image stacking order; must beat the float's own
---@field width integer applet width in cells
---@field border string|string[] border passed to `nvim_open_win`
---@field force_supported boolean? override image-capability detection entirely
local defaults = {
	cmd = { "uv", "run", "--project", repo_root(), "search" },
	cell_width = 8,
	gap = 1,
	max_rows = 3,
	debounce_ms = 120,
	zindex = 200,
	width = 64,
	border = "rounded",
	force_supported = nil,
}

---@type xingshu.Config
M.options = vim.deepcopy(defaults)

--- Merge user options over the defaults.
---@param opts table?
function M.setup(opts)
	M.options = vim.tbl_deep_extend("force", vim.deepcopy(defaults), opts or {})
end

--- The repository this plugin lives in.
M.root = repo_root()

return M
