return {
	{
		"bjarneo/hackerman.nvim",
		dependencies = { "bjarneo/aether.nvim" },
		priority = 1000,
		config = function()
			require("hackerman").setup({
				override = {
					Normal = { bg = "#000000", fg = "#C8CCD2" },
					NormalFloat = { bg = "#141519", fg = "#C8CCD2" },
					FloatBorder = { bg = "#141519", fg = "#C8CCD2" },
					CursorLine = { bg = "#141519" },
					CursorLineNr = { fg = "#E4E7EC", bold = true },
					LineNr = { fg = "#4C5158" },
					Visual = { bg = "#AEB9C4", fg = "#000000" },
					Search = { bg = "#CBB98C", fg = "#000000" },
					IncSearch = { bg = "#DBCDA8", fg = "#000000" },
					Cursor = { bg = "#E4E7EC", fg = "#000000" },
					StatusLine = { bg = "#141519", fg = "#C8CCD2" },
					StatusLineNC = { bg = "#000000", fg = "#4C5158" },
					Pmenu = { bg = "#141519", fg = "#C8CCD2" },
					PmenuSel = { bg = "#AEB9C4", fg = "#000000" },
					PmenuSbar = { bg = "#141519" },
					PmenuThumb = { bg = "#AEB9C4" },
					Comment = { fg = "#5C616A", italic = true },
					String = { fg = "#9FB79A" },
					Keyword = { fg = "#93AEBE" },
					Function = { fg = "#E4E7EC" },
					Type = { fg = "#AEB9C4" },
					Constant = { fg = "#CBB98C" },
					Number = { fg = "#CBB98C" },
					DiagnosticError = { fg = "#CE8181" },
					DiagnosticWarn = { fg = "#CBB98C" },
					DiagnosticInfo = { fg = "#93AEBE" },
					DiagnosticHint = { fg = "#7E97A8" },
					WinSeparator = { fg = "#4C5158", bg = "#000000" },
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
