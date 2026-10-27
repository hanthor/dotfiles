return {
  -- Fuzzy finder
  {
    "nvim-telescope/telescope.nvim",
    cmd = "Telescope",
    dependencies = {
      "nvim-lua/plenary.nvim",
      { "nvim-telescope/telescope-fzf-native.nvim", build = "make" },
      "nvim-telescope/telescope-ui-select.nvim",
    },
    keys = {
      { "<leader>ff", "<cmd>Telescope find_files<CR>",                desc = "Find files" },
      { "<leader>fg", "<cmd>Telescope live_grep<CR>",                 desc = "Live grep" },
      { "<leader>fr", "<cmd>Telescope oldfiles<CR>",                  desc = "Recent files" },
      { "<leader>fb", "<cmd>Telescope buffers<CR>",                   desc = "Buffers" },
      { "<leader>fh", "<cmd>Telescope help_tags<CR>",                 desc = "Help tags" },
      { "<leader>fs", "<cmd>Telescope lsp_document_symbols<CR>",      desc = "Document symbols" },
      { "<leader>fw", "<cmd>Telescope lsp_workspace_symbols<CR>",     desc = "Workspace symbols" },
      { "<leader>fd", "<cmd>Telescope diagnostics<CR>",               desc = "Diagnostics" },
      { "<leader>gc", "<cmd>Telescope git_commits<CR>",               desc = "Git commits" },
      { "<leader>gb", "<cmd>Telescope git_branches<CR>",              desc = "Git branches" },
      { "<leader>/",  "<cmd>Telescope current_buffer_fuzzy_find<CR>", desc = "Search buffer" },
      { "<leader>:",  "<cmd>Telescope command_history<CR>",           desc = "Command history" },
    },
    opts = function()
      return {
        defaults = {
          prompt_prefix = "  ",
          selection_caret = " ",
          mappings = {
            i = {
              ["<C-j>"] = "move_selection_next",
              ["<C-k>"] = "move_selection_previous",
              ["<C-d>"] = "delete_buffer",
              ["<Esc>"] = "close",
            },
          },
          layout_strategy = "horizontal",
          layout_config = { prompt_position = "top" },
          sorting_strategy = "ascending",
          winblend = 10,
        },
        extensions = {
          ["ui-select"] = { require("telescope.themes").get_dropdown() },
        },
      }
    end,
    config = function(_, opts)
      local telescope = require("telescope")
      telescope.setup(opts)
      -- fzf-native is a compiled extension; on a freshly cloned machine
      -- (before `make` has run) it won't load. Don't kill telescope over it.
      pcall(telescope.load_extension, "fzf")
      pcall(telescope.load_extension, "ui-select")
    end,
  },

  -- Git decorations
  {
    "lewis6991/gitsigns.nvim",
    event = "BufReadPost",
    opts = {
      signs = {
        add          = { text = "▎" },
        change       = { text = "▎" },
        delete       = { text = "" },
        topdelete    = { text = "" },
        changedelete = { text = "▎" },
        untracked    = { text = "▎" },
      },
      on_attach = function(buffer)
        local gs = package.loaded.gitsigns
        local map = function(mode, l, r, desc)
          vim.keymap.set(mode, l, r, { buffer = buffer, desc = desc })
        end
        map("n", "]h", gs.next_hunk,         "Next hunk")
        map("n", "[h", gs.prev_hunk,         "Prev hunk")
        map("n", "<leader>hs", gs.stage_hunk,   "Stage hunk")
        map("n", "<leader>hr", gs.reset_hunk,   "Reset hunk")
        map("n", "<leader>hp", gs.preview_hunk, "Preview hunk")
        map("n", "<leader>hb", function() gs.blame_line({ full = true }) end, "Blame line")
        map("n", "<leader>hd", gs.diffthis,     "Diff this")
        map("n", "<leader>ub", gs.toggle_current_line_blame, "Toggle line blame")
      end,
    },
  },

  -- Session management
  {
    "folke/persistence.nvim",
    event = "BufReadPre",
    opts = { options = { "buffers", "curdir", "tabpages", "winsize", "help", "globals" } },
    keys = {
      { "<leader>ss", function() require("persistence").load() end,                desc = "Restore session" },
      { "<leader>sl", function() require("persistence").load({ last = true }) end, desc = "Restore last session" },
      { "<leader>sd", function() require("persistence").stop() end,                desc = "Don't save session" },
    },
  },

  -- Better diagnostics panel
  {
    "folke/trouble.nvim",
    cmd = { "Trouble" },
    opts = { use_diagnostic_signs = true },
    keys = {
      { "<leader>xx", "<cmd>Trouble diagnostics toggle<CR>",                       desc = "Diagnostics" },
      { "<leader>xb", "<cmd>Trouble diagnostics toggle filter.buf=0<CR>",          desc = "Buffer diagnostics" },
      { "<leader>xs", "<cmd>Trouble symbols toggle focus=false<CR>",               desc = "Symbols" },
      { "<leader>xl", "<cmd>Trouble lsp toggle focus=false win.position=right<CR>", desc = "LSP defs/refs" },
      { "<leader>xL", "<cmd>Trouble loclist toggle<CR>",                           desc = "Location list" },
      { "<leader>xq", "<cmd>Trouble qflist toggle<CR>",                            desc = "Quickfix list" },
    },
  },

  -- Flash.nvim — better motion
  {
    "folke/flash.nvim",
    event = "VeryLazy",
    opts = {},
    keys = {
      { "s",     function() require("flash").jump() end,              mode = { "n", "x", "o" }, desc = "Flash jump" },
      { "S",     function() require("flash").treesitter() end,        mode = { "n", "x", "o" }, desc = "Flash treesitter" },
      { "r",     function() require("flash").remote() end,            mode = "o",               desc = "Remote flash" },
      { "<C-s>", function() require("flash").toggle() end,            mode = "c",               desc = "Toggle flash search" },
    },
  },

  -- Auto-pairs
  {
    "echasnovski/mini.pairs",
    event = "InsertEnter",
    opts = {},
  },

  -- Surround
  {
    "echasnovski/mini.surround",
    event = "BufReadPost",
    opts = {
      mappings = {
        add            = "gsa",
        delete         = "gsd",
        find           = "gsf",
        find_left      = "gsF",
        highlight      = "gsh",
        replace        = "gsr",
        update_n_lines = "gsn",
      },
    },
  },

  -- Better comments
  {
    "folke/ts-comments.nvim",
    event = "VeryLazy",
    opts = {},
  },

  -- Todo comments
  {
    "folke/todo-comments.nvim",
    event = "BufReadPost",
    dependencies = { "nvim-lua/plenary.nvim" },
    opts = {},
    keys = {
      { "<leader>st", "<cmd>TodoTelescope<CR>",                       desc = "Search TODOs" },
      { "]t",         function() require("todo-comments").jump_next() end, desc = "Next TODO" },
      { "[t",         function() require("todo-comments").jump_prev() end, desc = "Prev TODO" },
    },
  },

  -- Search/replace across files
  {
    "MagicDuck/grug-far.nvim",
    cmd = "GrugFar",
    opts = {},
    keys = {
      { "<leader>sr", "<cmd>GrugFar<CR>", desc = "Search & replace (grug-far)" },
    },
  },
}
