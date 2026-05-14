return {
  -- Git blame / diff in editor
  {
    "sindrets/diffview.nvim",
    cmd = { "DiffviewOpen", "DiffviewFileHistory" },
    keys = {
      { "<leader>gd", "<cmd>DiffviewOpen<CR>",          desc = "Git diff" },
      { "<leader>gh", "<cmd>DiffviewFileHistory %<CR>",  desc = "File history" },
      { "<leader>gH", "<cmd>DiffviewFileHistory<CR>",   desc = "Repo history" },
      { "<leader>gc", "<cmd>DiffviewClose<CR>",          desc = "Close diffview" },
    },
  },

  -- GitHub integration
  {
    "pwntester/octo.nvim",
    cmd = "Octo",
    dependencies = {
      "nvim-lua/plenary.nvim",
      "nvim-telescope/telescope.nvim",
      "nvim-tree/nvim-web-devicons",
    },
    opts = {},
  },

  -- Better folding
  {
    "kevinhwang91/nvim-ufo",
    event = "BufReadPost",
    dependencies = { "kevinhwang91/promise-async" },
    opts = {
      provider_selector = function() return { "treesitter", "indent" } end,
    },
    keys = {
      { "zR", function() require("ufo").openAllFolds() end,  desc = "Open all folds" },
      { "zM", function() require("ufo").closeAllFolds() end, desc = "Close all folds" },
      { "zK", function() require("ufo").peekFoldedLinesUnderCursor() end, desc = "Peek fold" },
    },
  },

  -- Multi-cursor / extra text objects
  {
    "echasnovski/mini.ai",
    event = "BufReadPost",
    opts = { n_lines = 500 },
  },

  -- Highlight word under cursor
  {
    "RRethy/vim-illuminate",
    event = "BufReadPost",
    opts = {
      delay = 200,
      large_file_cutoff = 2000,
      large_file_overrides = { providers = { "lsp" } },
    },
    config = function(_, opts)
      require("illuminate").configure(opts)
      vim.keymap.set("n", "]]", function() require("illuminate").goto_next_reference() end, { desc = "Next reference" })
      vim.keymap.set("n", "[[", function() require("illuminate").goto_prev_reference() end, { desc = "Prev reference" })
    end,
  },

  -- Markdown preview
  {
    "MeanderingProgrammer/render-markdown.nvim",
    dependencies = { "nvim-treesitter/nvim-treesitter", "nvim-tree/nvim-web-devicons" },
    ft = { "markdown" },
    opts = {},
  },

  -- Lazygit integration
  {
    "kdheepak/lazygit.nvim",
    cmd = "LazyGit",
    dependencies = { "nvim-lua/plenary.nvim" },
    keys = {
      { "<leader>gg", "<cmd>LazyGit<CR>", desc = "LazyGit" },
    },
  },

  -- Test runner
  {
    "nvim-neotest/neotest",
    lazy = true,
    dependencies = {
      "nvim-lua/plenary.nvim",
      "nvim-treesitter/nvim-treesitter",
      "nvim-neotest/neotest-python",
      "nvim-neotest/neotest-go",
    },
    keys = {
      { "<leader>tr", function() require("neotest").run.run() end,            desc = "Run nearest test" },
      { "<leader>tf", function() require("neotest").run.run(vim.fn.expand("%")) end, desc = "Run file tests" },
      { "<leader>to", function() require("neotest").output.open() end,        desc = "Test output" },
      { "<leader>ts", function() require("neotest").summary.toggle() end,     desc = "Test summary" },
    },
    opts = function()
      return {
        adapters = {
          require("neotest-python"),
          require("neotest-go"),
        },
      }
    end,
  },

  -- Copilot (optional — requires `gh copilot` or token)
  {
    "zbirenbaum/copilot.lua",
    cmd = "Copilot",
    event = "InsertEnter",
    opts = {
      suggestion = { enabled = false },
      panel = { enabled = false },
    },
  },
  {
    "zbirenbaum/copilot-cmp",
    dependencies = { "zbirenbaum/copilot.lua" },
    event = "InsertEnter",
    opts = {},
    config = function(_, opts)
      local ok, copilot_cmp = pcall(require, "copilot_cmp")
      if ok then copilot_cmp.setup(opts) end
    end,
  },
}
