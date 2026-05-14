local opt = vim.opt

-- UI
opt.number = true
opt.relativenumber = true
opt.signcolumn = "yes"
opt.cursorline = true
opt.termguicolors = true
opt.showmode = false         -- lualine shows it
opt.laststatus = 3           -- single global statusline
opt.cmdheight = 1
opt.pumheight = 10
opt.scrolloff = 8
opt.sidescrolloff = 8
opt.splitbelow = true
opt.splitright = true
opt.wrap = false
opt.colorcolumn = "100"
opt.list = true
opt.listchars = { tab = "» ", trail = "·", nbsp = "␣" }

-- Editing
opt.expandtab = true
opt.shiftwidth = 2
opt.tabstop = 2
opt.softtabstop = 2
opt.smartindent = true
opt.breakindent = true

-- Search
opt.ignorecase = true
opt.smartcase = true
opt.hlsearch = true
opt.incsearch = true

-- Files
opt.updatetime = 200
opt.timeoutlen = 300
opt.undofile = true
opt.undolevels = 10000
opt.backup = false
opt.swapfile = false
opt.confirm = true           -- ask instead of error on unsaved changes

-- Completion
opt.completeopt = "menu,menuone,noselect"
opt.pumblend = 10
opt.winblend = 10

-- Folding (ufo handles this)
opt.foldlevel = 99
opt.foldlevelstart = 99
opt.foldenable = true

-- Misc
opt.mouse = "a"
opt.clipboard = "unnamedplus"
opt.virtualedit = "block"
opt.inccommand = "nosplit"   -- live preview of substitutions
opt.jumpoptions = "view"
opt.spelllang = "en_us"
opt.spell = false

-- Leader
vim.g.mapleader = " "
vim.g.maplocalleader = "\\"
