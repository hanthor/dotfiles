local map = vim.keymap.set

-- ── Better defaults ───────────────────────────────────────────────
map("n", "<Esc>", "<cmd>nohlsearch<CR>")
map("i", "jk", "<Esc>", { desc = "Exit insert" })
map("n", "U", "<C-r>", { desc = "Redo" })

-- ── Window navigation ─────────────────────────────────────────────
map("n", "<C-h>", "<C-w>h")
map("n", "<C-j>", "<C-w>j")
map("n", "<C-k>", "<C-w>k")
map("n", "<C-l>", "<C-w>l")

-- ── Resize windows ───────────────────────────────────────────────
map("n", "<C-Up>", "<cmd>resize +2<CR>")
map("n", "<C-Down>", "<cmd>resize -2<CR>")
map("n", "<C-Left>", "<cmd>vertical resize -2<CR>")
map("n", "<C-Right>", "<cmd>vertical resize +2<CR>")

-- ── Buffers ──────────────────────────────────────────────────────
map("n", "<S-h>", "<cmd>bprevious<CR>", { desc = "Prev buffer" })
map("n", "<S-l>", "<cmd>bnext<CR>", { desc = "Next buffer" })
map("n", "<leader>bd", "<cmd>bdelete<CR>", { desc = "Delete buffer" })
map("n", "<leader>bo", "<cmd>%bdelete|edit#|bdelete#<CR>", { desc = "Delete other buffers" })

-- ── Better movement ───────────────────────────────────────────────
map("n", "j", "v:count == 0 ? 'gj' : 'j'", { expr = true, silent = true })
map("n", "k", "v:count == 0 ? 'gk' : 'k'", { expr = true, silent = true })
map("n", "H", "^")
map("n", "L", "$")

-- ── Indenting in visual keeps selection ──────────────────────────
map("v", "<", "<gv")
map("v", ">", ">gv")

-- ── Move lines ───────────────────────────────────────────────────
map("n", "<A-j>", "<cmd>m .+1<CR>==", { desc = "Move line down" })
map("n", "<A-k>", "<cmd>m .-2<CR>==", { desc = "Move line up" })
map("v", "<A-j>", ":m '>+1<CR>gv=gv", { desc = "Move selection down" })
map("v", "<A-k>", ":m '<-2<CR>gv=gv", { desc = "Move selection up" })

-- ── Save ─────────────────────────────────────────────────────────
map({ "n", "i", "v" }, "<C-s>", "<cmd>w<CR><Esc>", { desc = "Save" })

-- ── Quickfix ─────────────────────────────────────────────────────
map("n", "]q", "<cmd>cnext<CR>", { desc = "Next quickfix" })
map("n", "[q", "<cmd>cprev<CR>", { desc = "Prev quickfix" })
map("n", "<leader>q", "<cmd>copen<CR>", { desc = "Open quickfix" })

-- ── Diagnostics ──────────────────────────────────────────────────
map("n", "]d", vim.diagnostic.goto_next, { desc = "Next diagnostic" })
map("n", "[d", vim.diagnostic.goto_prev, { desc = "Prev diagnostic" })
map("n", "<leader>e", vim.diagnostic.open_float, { desc = "Show diagnostic" })

-- ── Terminal ─────────────────────────────────────────────────────
map("t", "<Esc><Esc>", "<C-\\><C-n>", { desc = "Exit terminal mode" })

-- ── File tree ────────────────────────────────────────────────────
map("n", "<leader>e", "<cmd>Neotree toggle<CR>", { desc = "Toggle file tree" })
map("n", "<leader>E", "<cmd>Neotree reveal<CR>", { desc = "Reveal in file tree" })

-- ── Lazy ─────────────────────────────────────────────────────────
map("n", "<leader>l", "<cmd>Lazy<CR>", { desc = "Lazy plugin manager" })
map("n", "<leader>L", "<cmd>Lazy update<CR>", { desc = "Lazy update plugins" })
