return {
  -- Status line
  {
    "nvim-lualine/lualine.nvim",
    event = "VeryLazy",
    dependencies = { "nvim-tree/nvim-web-devicons" },
    opts = {
      options = {
        -- "auto" picks up the active colorscheme without requiring the
        -- catppuccin/lualine-theme module to be present.
        theme = "auto",
        globalstatus = true,
        disabled_filetypes = { statusline = { "dashboard", "lazy" } },
      },
      sections = {
        lualine_a = { "mode" },
        lualine_b = { "branch", "diff", "diagnostics" },
        lualine_c = { { "filename", path = 1 } },
        lualine_x = { "encoding", "fileformat", "filetype" },
        lualine_y = { "progress" },
        lualine_z = { "location" },
      },
    },
  },

  -- Bufferline
  {
    "akinsho/bufferline.nvim",
    event = "VeryLazy",
    dependencies = { "nvim-tree/nvim-web-devicons" },
    opts = {
      options = {
        diagnostics = "nvim_lsp",
        always_show_bufferline = false,
        offsets = {
          { filetype = "neo-tree", text = "Files", highlight = "Directory", text_align = "left" },
        },
      },
    },
  },

  -- File tree
  {
    "nvim-neo-tree/neo-tree.nvim",
    branch = "v3.x",
    cmd = "Neotree",
    dependencies = {
      "nvim-lua/plenary.nvim",
      "nvim-tree/nvim-web-devicons",
      "MunifTanjim/nui.nvim",
    },
    opts = {
      filesystem = {
        bind_to_cwd = false,
        follow_current_file = { enabled = true },
        use_libuv_file_watcher = true,
      },
      window = { width = 35 },
      default_component_configs = {
        indent = { with_expanders = true },
      },
    },
  },

  -- Notifications + command palette
  {
    "folke/noice.nvim",
    event = "VeryLazy",
    dependencies = { "MunifTanjim/nui.nvim", "rcarriga/nvim-notify" },
    opts = {
      lsp = {
        override = {
          ["vim.lsp.util.convert_input_to_markdown_lines"] = true,
          ["vim.lsp.util.stylize_markdown"] = true,
          ["cmp.entry.get_documentation"] = true,
        },
      },
      presets = {
        bottom_search = true,
        command_palette = true,
        long_message_to_split = true,
        inc_rename = false,
      },
    },
  },

  -- Which-key (key binding hints)
  {
    "folke/which-key.nvim",
    event = "VeryLazy",
    opts = {
      delay = 400,
      icons = { mappings = true },
      spec = {
        { "<leader>b", group = "buffers" },
        { "<leader>c", group = "code" },
        { "<leader>f", group = "find/files" },
        { "<leader>g", group = "git" },
        { "<leader>s", group = "search" },
        { "<leader>t", group = "terminal" },
        { "<leader>u", group = "ui" },
        { "<leader>x", group = "diagnostics/quickfix" },
      },
    },
  },

  -- Indent guides
  {
    "lukas-reineke/indent-blankline.nvim",
    event = "BufReadPost",
    main = "ibl",
    opts = {
      indent = { char = "│" },
      scope = { show_start = false, show_end = false },
    },
  },

  -- Dashboard
  {
    "nvimdev/dashboard-nvim",
    event = "VimEnter",
    opts = {
      theme = "doom",
      config = {
        header = {
          "",
          "  ███╗   ██╗███████╗ ██████╗ ██╗   ██╗██╗███╗   ███╗",
          "  ████╗  ██║██╔════╝██╔═══██╗██║   ██║██║████╗ ████║",
          "  ██╔██╗ ██║█████╗  ██║   ██║██║   ██║██║██╔████╔██║",
          "  ██║╚██╗██║██╔══╝  ██║   ██║╚██╗ ██╔╝██║██║╚██╔╝██║",
          "  ██║ ╚████║███████╗╚██████╔╝ ╚████╔╝ ██║██║ ╚═╝ ██║",
          "  ╚═╝  ╚═══╝╚══════╝ ╚═════╝   ╚═══╝  ╚═╝╚═╝     ╚═╝",
          "",
        },
        center = {
          { icon = "  ", key = "f", desc = "Find files",    action = "Telescope find_files" },
          { icon = "  ", key = "r", desc = "Recent files",  action = "Telescope oldfiles" },
          { icon = "  ", key = "g", desc = "Live grep",     action = "Telescope live_grep" },
          { icon = "  ", key = "e", desc = "File tree",     action = "Neotree toggle" },
          { icon = "  ", key = "s", desc = "Restore session", action = "lua require('persistence').load()" },
          { icon = "󰒲  ", key = "l", desc = "Lazy",          action = "Lazy" },
          { icon = "  ", key = "q", desc = "Quit",           action = "qa" },
        },
        footer = function()
          local stats = require("lazy").stats()
          return { "⚡ " .. stats.count .. " plugins loaded in " .. stats.startuptime .. "ms" }
        end,
      },
    },
  },

  -- Indent scope animation
  {
    "echasnovski/mini.indentscope",
    event = "BufReadPost",
    opts = { symbol = "│", options = { try_as_border = true } },
    init = function()
      vim.api.nvim_create_autocmd("FileType", {
        pattern = { "help", "lazy", "neo-tree", "dashboard", "Trouble" },
        callback = function() vim.b.miniindentscope_disable = true end,
      })
    end,
  },

  -- Colorize hex codes
  {
    "NvChad/nvim-colorizer.lua",
    event = "BufReadPost",
    opts = { user_default_options = { tailwind = true, css = true } },
  },

  -- Smooth scrolling
  {
    "karb94/neoscroll.nvim",
    event = "BufReadPost",
    opts = { mappings = { "<C-u>", "<C-d>", "<C-b>", "<C-f>", "zt", "zz", "zb" } },
  },
}
