--!strict
-- Volume no padrão das redes: loudness integrado em -14 LUFS e pico abaixo de -1,5 dBTP.
local ng3 = require("@ng3")

local M = {}

function M.info()
	return {
		id = "normalizar-audio",
		nome = "Normalizar áudio",
		descricao = "No projeto: põe o ganho certo no clipe de áudio do vídeo dentro do .fcproj. "
			.. "No arquivo: grava <vídeo>_norm.mp4 ao lado com o FFmpeg (imagem copiada, sem recodificar). "
			.. "O original nunca é tocado.",
		aplicaA = { "video", "corte" },
		params = {
			{ id = "onde", rotulo = "Aplicar em", tipo = "escolha",
				opcoes = { "projeto e arquivo", "só projeto", "só arquivo" }, padrao = "projeto e arquivo" },
			{ id = "lufs", rotulo = "Alvo (LUFS)", tipo = "numero", padrao = -14, min = -24, max = -9, passo = 1,
				ajuda = "-14 é a referência comum para Reels" },
			{ id = "pico", rotulo = "Pico máximo (dBTP)", tipo = "numero", padrao = -1.5, min = -6, max = -0.5, passo = 0.5 },
		},
	}
end

function M.rodar(itens, p)
	for _, item in itens do
		for _, v in item.videos do
			local cmd = { "python3", "plugins/normalizar-audio/normalizar.py", v,
				"--lufs", tostring(p.lufs), "--pico", tostring(p.pico) }
			local projeto = item.projeto ~= nil and item.projeto ~= ""
			if p.onde ~= "só arquivo" and projeto then
				table.insert(cmd, "--projeto")
				table.insert(cmd, item.projeto)
			elseif p.onde ~= "só arquivo" then
				ng3.avisar(`{item.nome}: ainda sem projeto, só o arquivo`)
			end
			if p.onde == "só projeto" and projeto then
				table.insert(cmd, "--sem-arquivo")
			end
			ng3.processo(cmd)
		end
	end
end

return M
