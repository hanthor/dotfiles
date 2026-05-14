return {
  {
    "catppuccin/nvim",
    name = "catppuccin",
    priority = 1000,
    lazy = false,
    opts = {
      flavour = "mocha",
      transparent_background = false,
      show_end_of_buffer = false,
      term_colors = true,
      dim_inactive = { enabled = true, shade = "dark", percentage = 0.15 },
      styles = {
        comments = { "italic" },
        conditionals = { "italic" },
        keywords = { "bold" },
        functions = {},
        strings = {},
        variables = {},
      },
      integrations = {
        cmp = true,
        gitsigns = true,
        nvimtree = false,
        neo_tree = true,
        telescope = { enabled = true },
        treesitter = true,
        treesitter_context = true,
        lsp_saga = false,
        mason = true,
        mini = { enabled = true },
        indent_blankline = { enabled = true },
        which_key = true,
        illuminate = { enabled = true },
        noice = true,
        notify = true,
        blink_cmp = true,
      },
    },
    config = function(_, opts)
      require("catppuccin").setup(opts)
      vim.cmd.colorscheme("catppuccin")
    end,
  },
}
