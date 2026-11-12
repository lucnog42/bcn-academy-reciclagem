--!strict
-- Legenda presa à fala, no arquivo (.srt/.words.json) e dentro do projeto do FilmCraft.
local ng3 = require("@ng3")

local M = {}

function M.info()
	return {
		id = "legendar",
		nome = "Legendar",
		descricao = "Refinar mede a voz e acerta o começo e o fim de cada palavra (segundos por vídeo); "
			.. "transcrever roda o Whisper de novo. Com projeto, troca só a faixa de legenda do .fcproj "
			.. "(o resto do que foi editado no FilmCraft fica).",
		aplicaA = { "video", "corte" },
		params = {
			{ id = "modo", rotulo = "O que fazer", tipo = "escolha", opcoes = { "refinar", "transcrever" }, padrao = "refinar" },
			{ id = "projeto", rotulo = "Atualizar o projeto", tipo = "booleano", padrao = true },
		},
	}
end

function M.rodar(itens, p)
	for _, item in itens do
		for _, v in item.videos do
			local cmd = { "python3", "plugins/legendar/aplicar.py", v, "--modo", p.modo }
			if p.projeto and item.projeto ~= nil and item.projeto ~= "" then
				table.insert(cmd, "--projeto")
				table.insert(cmd, item.projeto)
			end
			ng3.processo(cmd)
		end
	end
end

return M
