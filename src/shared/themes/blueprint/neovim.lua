return {
  {
    "LazyVim/LazyVim",
    opts = {
      colorscheme = function()
        vim.cmd.colorscheme("default")
        local groups = {
          Normal = { fg = "#ffffff", bg = "#000000" },
          NormalFloat = { fg = "#ffffff", bg = "#000000" },
          FloatBorder = { fg = "#e6e6e6", bg = "#000000" },
          WinSeparator = { fg = "#555555", bg = "#000000" },
          Comment = { fg = "#999999", italic = true },
          Constant = { fg = "#ffffff" },
          String = { fg = "#d6d6d6" },
          Identifier = { fg = "#ffffff" },
          Function = { fg = "#ffffff" },
          Statement = { fg = "#ff8a30", bold = true },
          PreProc = { fg = "#ff8a30" },
          Type = { fg = "#ffffff", bold = true },
          Special = { fg = "#ff8a30" },
          Visual = { fg = "#000000", bg = "#ff8a30" },
          Search = { fg = "#000000", bg = "#ff8a30" },
          IncSearch = { fg = "#000000", bg = "#ffac6b" },
          LineNr = { fg = "#999999", bg = "#000000" },
          CursorLineNr = { fg = "#ff8a30", bold = true },
          StatusLine = { fg = "#ffffff", bg = "#101010" },
          StatusLineNC = { fg = "#999999", bg = "#000000" },
          Pmenu = { fg = "#ffffff", bg = "#080808" },
          PmenuSel = { fg = "#000000", bg = "#ff8a30" },
        }
        for name, value in pairs(groups) do
          vim.api.nvim_set_hl(0, name, value)
        end
      end,
    },
  },
}
