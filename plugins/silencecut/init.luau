--!strict
-- Corta o silêncio: dentro do projeto do FilmCraft e/ou num vídeo novo renderizado com o FFmpeg.
local ng3 = require("@ng3")

local M = {}

function M.info()
	return {
		id = "silencecut",
		nome = "Cortar silêncio",
		descricao = "Acha onde há fala (pelas palavras transcritas, ou pelo nível do som) e tira o resto. "
			.. "No projeto: refaz o .fcproj do item só com a fala de cada vídeo e com J/L entre as falas "
			.. "(a versão anterior fica em projetos_antigos/). No arquivo: grava <vídeo>_sem_silencio.mp4 "
			.. "na pasta saidas/ do item.",
		aplicaA = { "video", "corte" },
		params = {
			{ id = "onde", rotulo = "Aplicar em", tipo = "escolha",
				opcoes = { "projeto e arquivo", "só projeto", "só arquivo" }, padrao = "projeto e arquivo" },
			{ id = "detector", rotulo = "Onde há fala", tipo = "escolha", opcoes = { "fala", "auto", "nivel" }, padrao = "fala",
				ajuda = "fala = pelas palavras transcritas (ignora ruído) · auto = nível estimado · nivel = o dB abaixo" },
			{ id = "limiar", rotulo = "Nível de silêncio (dB)", tipo = "numero", padrao = -40, min = -70, max = -10, passo = 1 },
			{ id = "silencio", rotulo = "Silêncio mínimo (s)", tipo = "numero", padrao = 0.5, min = 0.1, max = 3, passo = 0.05 },
			{ id = "margem", rotulo = "Margem na fala (s)", tipo = "numero", padrao = 0.12, min = 0, max = 0.6, passo = 0.02 },
			{ id = "modo", rotulo = "Cortes no arquivo", tipo = "escolha", opcoes = { "join", "keep" }, padrao = "join",
				ajuda = "join = juntar · keep = manter no lugar" },
			{ id = "jl", rotulo = "J/L-cut", tipo = "escolha", opcoes = { "off", "auto", "j", "l", "alternate" }, padrao = "auto" },
		},
	}
end

local function num(x: any): string
	return string.format("%.3f", x)
end

function M.rodar(itens, p)
	local n = 0
	for _, item in itens do
		if #item.videos == 0 then
			continue
		end
		-- um processo por item: todos os vídeos dele e o projeto refeito uma vez só
		local cmd = { "python3", "plugins/silencecut/aplicar.py" }
		for _, v in item.videos do
			table.insert(cmd, v)
		end
		for _, x in { "--onde", p.onde, "--detector", p.detector, "-t", num(p.limiar), "-s", num(p.silencio),
			"--pad", num(p.margem), "--mode", p.modo, "--jl", p.jl } do
			table.insert(cmd, x)
		end
		table.insert(cmd, if item.tipo == "corte" then "--corte" else "--post")
		table.insert(cmd, item.nome)
		ng3.processo(cmd)
		n += 1
	end
	ng3.avisar(`{n} item(ns) na fila`)
end

return M
