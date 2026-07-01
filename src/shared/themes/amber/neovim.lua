return {
	{
		"bjarneo/hackerman.nvim",
		dependencies = { "bjarneo/aether.nvim" },
		priority = 1000,
		config = function()
			require("hackerman").setup({
				override = {
					Normal = { bg = "#000000", fg = "#FFA033" },
					NormalFloat = { bg = "#1A0F03", fg = "#FFA033" },
					FloatBorder = { bg = "#1A0F03", fg = "#FFA033" },
					CursorLine = { bg = "#1A0F03" },
					CursorLineNr = { fg = "#FFC266", bold = true },
					LineNr = { fg = "#996022" },
					Visual = { bg = "#FFA033", fg = "#000000" },
					Search = { bg = "#FFD24D", fg = "#000000" },
					IncSearch = { bg = "#FFCC33", fg = "#000000" },
					Cursor = { bg = "#FFC266", fg = "#000000" },
					StatusLine = { bg = "#1A0F03", fg = "#FFA033" },
					StatusLineNC = { bg = "#000000", fg = "#996022" },
					Pmenu = { bg = "#1A0F03", fg = "#FFA033" },
					PmenuSel = { bg = "#FFA033", fg = "#000000" },
					PmenuSbar = { bg = "#1A0F03" },
					PmenuThumb = { bg = "#FFA033" },
					Comment = { fg = "#996022", italic = true },
					String = { fg = "#FFCC33" },
					Keyword = { fg = "#FFD24D" },
					Function = { fg = "#FFC266" },
					Type = { fg = "#FF8000" },
					Constant = { fg = "#FFCC33" },
					Number = { fg = "#FF8000" },
					DiagnosticError = { fg = "#FF5A2C" },
					DiagnosticWarn = { fg = "#FFCC33" },
					DiagnosticInfo = { fg = "#FFA033" },
					DiagnosticHint = { fg = "#CC7A2C" },
					WinSeparator = { fg = "#996022", bg = "#000000" },
					SignColumn = { bg = "#000000" },
					EndOfBuffer = { fg = "#000000" },
				},
			})
		end,
	},
	{
		"LazyVim/LazyVim",
		opts = {
			colorscheme = "hackerman",
		},
	},
}
