--!strict
-- Coloca os motions prontos (_motion/prontos/<id>.mov) no projeto do FilmCraft e/ou num vídeo novo.
local ng3 = require("@ng3")

local M = {}

function M.info()
	return {
		id = "inserir-motion",
		nome = "Inserir motion",
		descricao = "Pega os momentos aprovados que já têm o MOV exportado em _motion/prontos/ e: no projeto, "
			.. "monta a faixa Motion no topo, cada um no seu tempo (o corte de silêncio é levado em conta); "
			.. "no arquivo, grava <vídeo>_motion.mp4 em saidas/ com o FFmpeg.",
		aplicaA = { "video", "corte" },
		params = {
			{ id = "onde", rotulo = "Aplicar em", tipo = "escolha",
				opcoes = { "projeto e arquivo", "só projeto", "só arquivo" }, padrao = "só projeto" },
		},
	}
end

function M.rodar(itens, p)
	local n = 0
	for _, item in itens do
		if #item.videos == 0 then
			continue
		end
		local pasta = if item.tipo == "corte" then item.arquivo else item.pasta
		local cmd = { "python3", "src/plano/momentos.py", "inserir", pasta, "--onde", p.onde }
		if item.projeto ~= nil and item.projeto ~= "" then
			table.insert(cmd, "--projeto")
			table.insert(cmd, item.projeto)
		end
		ng3.processo(cmd)
		n += 1
	end
	ng3.avisar(`inserir motion: {n} item(ns)`)
end

return M
