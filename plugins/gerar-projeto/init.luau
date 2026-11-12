--!strict
-- Gera o projeto FilmCraft/PhotoCraft dos itens selecionados (o mesmo gerar_projetos.py do botão
-- do rodapé, aqui com as opções à mão).
local ng3 = require("@ng3")

local M = {}

function M.info()
	return {
		id = "gerar-projeto",
		nome = "Gerar projeto",
		descricao = "Cria o .fcproj (vídeo) ou .pcraft (imagens) de cada item com o modelo base: abertura, "
			.. "legenda presa à fala, música, encerramento. Usa o montagem.json do post quando existe.",
		aplicaA = { "post", "corte" },
		params = {
			{ id = "forcar", rotulo = "Refazer os que já existem", tipo = "booleano", padrao = false },
		},
	}
end

function M.rodar(itens, p)
	local posts, cortes = {}, {}
	for _, item in itens do
		if item.tipo == "corte" then
			table.insert(cortes, item.nome)
		else
			table.insert(posts, item.nome)
		end
	end
	if #posts > 0 then ng3.gerar(posts, false, p.forcar) end
	if #cortes > 0 then ng3.gerar(cortes, true, p.forcar) end
end

return M
