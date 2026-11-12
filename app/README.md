# ng3-painel — o painel do Video Automation NG3

Grade, filtros, abas, preview e marcações do acervo da marca ativa, numa janela nativa feita com
[Rune](https://github.com/anomalyco/rune) (Rust, desenhada na placa de vídeo). O motor é o Python
de `src/`: o app sobe `src/painel/api.py serve` e conversa com ele por JSON.

## Compilar (uma vez)

No Arch:

```bash
sudo pacman -S --needed base-devel rustup libxkbcommon wayland vulkan-icd-loader mpv ffmpeg
rustup default stable            # Rust 1.97 ou mais novo
cd <raiz do projeto>/app
cargo build --release            # a 1ª vez leva ~10 min (compila o Rune e o Luau)
```

O binário fica em `target/release/ng3-painel`. Para ter no menu:
`ln -s "$PWD/target/release/ng3-painel" ~/.local/bin/` (ele acha a raiz do projeto pelo caminho real do executável).

## Rodar

```bash
ng3-painel                          # marca ativa (config/marca-ativa) e o acervo dela
ng3-painel --raiz <projeto>         # se o executável estiver fora do projeto
ng3-painel --acervo <pasta>         # força outro acervo para esta sessão
```

A marca se troca em "chaves e config" → "Marca (cliente)". O LED no topo fica verde quando o
motor Python está ligado.

## O que tem

| Aba | O que faz |
|---|---|
| posts | grade com miniatura, pilar, data, curtidas, score; NI, RP e seleção em cada card; busca na pasta, legenda e fala; filtros por ano, pilar, tipo, status e "só sem projeto" |
| recomendados | ranking pelo score do `plano.py`, com a decomposição (alcance, evergreen, material, maturidade, penal) |
| cortes | uma pasta de `_Cortes/` = um card e um projeto (os vídeos dela em sequência na timeline) |
| plugins | os plugins Luau, com os parâmetros de cada um e "rodar em N" na seleção |

A grade mostra cada mídia no formato dela (vertical, 4:5, horizontal), em linhas justificadas.
Arquivos gerados (`_norm`, `_sem_silencio`, renders com o nome do projeto, `saidas/`, `Auto-Save/`)
não aparecem como vídeos novos.

Clicar num card abre o preview: imagens do carrossel, quadro grande do vídeo com uma tira de
16 quadros para escolher o momento, a legenda que está no ar naquele instante, e
**tocar com som** abre o vídeo no `mpv` a partir do quadro escolhido. (O Rune ainda não toca
vídeo no Linux, por isso os quadros vêm do FFmpeg e o som do mpv.)

**Páginas e desempenho**

- A grade mostra uma página por vez (48, 96, 192 ou todos), com o paginador no rodapé e
  "próxima página" no fim da grade. Mudar o filtro volta para a página 1; marcar NI/RP não.
- Dentro da página só as linhas que estão na tela existem; as miniaturas da página atual e da
  próxima são pedidas antes de rolar, e as de páginas longe são soltas da memória.
- Ordem: recentes, antigos, score ou curtidas. Tamanho dos cards: compacto, normal, grande.
- A busca espera 180 ms depois da última tecla antes de filtrar.
- A lista de posts abre do cache da última vez (`.cache/listas/`) e é atualizada em segundo
  plano; se mudou algo no acervo, a grade se atualiza sozinha.
- O preview carrega as fotos do carrossel em 720 px (cache), não o arquivo original.

**Atalhos:** `/` vai para a busca · `←` `→` trocam de página (no preview, de quadro) ·
`Esc` fecha o preview.

Rodapé: quantos itens estão selecionados, o peso estimado do projeto, **gerar projeto** e o
painel de tarefas, onde a saída de cada geração ou plugin aparece linha a linha.

## Motion

No preview de um post ou pasta de cortes, a seção **Motion**:

1. **Contexto**: escreva o que o Claude precisa saber além da fala (quem fala, nomes, clube,
   lugar, o que destacar, o tom). **Referências**: arraste imagens para a seção (X11), use
   "abrir pasta de referências" e copie para lá, ou "usar este quadro como referência".
   Fica em `<pasta>/motion/contexto.json` e `<pasta>/motion/referencias/`.
2. **Base: o projeto do FilmCraft.** Quando o item já tem projeto, a IA vê a timeline montada
   (trechos de fala já cortados, emendas, abertura com o título, logo, legendas, ending e os
   motions que já estão lá) e escolhe e posiciona os momentos nela; os tempos aparecem como
   "no projeto 0:12 → 0:15". Sem projeto, a base é o vídeo cru.
   **sugerir momentos**: a API do Claude lê a fala com os tempos, o contexto, as referências e
   três quadros do vídeo, e devolve até 4 momentos (destaque, número, nome, lugar, chamada).
   As faixas coloridas sobre a tira mostram onde caem; "ver" leva o preview até o momento.
3. Edite o texto, ajuste ±0,5 s, **aprovar** ou **descartar**. Cada momento tem as **suas
   referências**: arraste imagens para o card dele, "+ quadro atual", "pasta deste momento"
   (`motion/referencias/<id>/`), ou ligue as gerais do item com um clique ("usar também").
   O filme daquele momento usa essas primeiro.
   **Direção do motion** (briefing) e **prompt do vídeo**: escreva, ou use "sugerir/melhorar com
   IA" — a IA das sugestões vê o momento, o que já está na tela no projeto, as imagens e o
   quadro, e devolve uma versão e duas alternativas (clique para usar). O briefing vai na fila. Os aprovados vão para
   `_motion/fila.json`, com o quadro do momento em `_motion/quadros/<id>.png`.
4. Aqui no Claude: "faz os motions da fila" (skill **bcn-motion**). Cada pedido vira um filme
   Motion; na página do filme, Export → MOV e salve como `_motion/prontos/<id>.mov`.
5. Plugin **Inserir motion**: no projeto, uma faixa "Motion" no topo com cada MOV no seu
   tempo (o corte de silêncio é levado em conta); no arquivo, `saidas/<vídeo>_motion.mp4`.

**Vídeo com IA (OpenRouter)**: em qualquer momento (ou num novo, com "+ momento aqui" no quadro
escolhido), "vídeo com IA" abre o pedido: prompt (vem uma sugestão, edite à vontade), modelo
(a lista vem do OpenRouter, com duração, resolução e preço de cada um), as imagens do momento
como 1º quadro ou referência, som gerado ou não. O vídeo sai em `dados/marcas/<marca>/motion/prontos/<id>.mp4` e o
**Inserir motion** coloca no projeto como b-roll (a fala continua por baixo). Usa uma chave
própria do OpenRouter, separada da chave das sugestões: no botão do topo, em "Vídeo com IA"
(`[segredos] video_openrouter_api_key`). O custo de cada vídeo aparece no momento quando termina.
`python3 src/criar/video.py modelos` lista os modelos no terminal.

A IA das sugestões se escolhe no botão do topo (à direita): **Claude**, **DeepSeek**,
**OpenRouter**, **Ollama** (local, sem chave) ou qualquer outra API no formato da OpenAI, com o
modelo e a chave de cada uma. Fica em `config/local.toml` (`[ia]` e `[segredos]`,
fora do git). Se o modelo não aceitar imagens, a pergunta vai só com o texto.
`python3 src/plano/momentos.py teste` grava `dados/marcas/<marca>/motion/teste_transparencia.mov`: arraste para o FilmCraft
sobre um vídeo para conferir se ele respeita a transparência.

## Plugins

Cada plugin é uma pasta `plugins/<nome>/` (na raiz do projeto) com um `init.luau`. Salvar o arquivo
recarrega o plugin com o app aberto. Vêm quatro:

| Plugin | Serve para | No projeto (.fcproj) | No arquivo (FFmpeg) |
|---|---|---|---|
| Cortar silêncio | vídeos e cortes | refaz o projeto do item já cortado | grava `<vídeo>_sem_silencio.mp4`, com J/L |
| Inserir motion | vídeos e cortes | os MOV de `_motion/prontos/` na faixa Motion do projeto e/ou `saidas/<vídeo>_motion.mp4` |
| Normalizar áudio | vídeos e cortes | põe o ganho no clipe de áudio do vídeo | grava `<vídeo>_norm.mp4` (-14 LUFS, pico -1,5 dBTP) |
| Legendar | vídeos e cortes | troca só a faixa de legenda | reescreve `.srt` e `.words.json` |
| Gerar projeto | posts e cortes | cria ou refaz o `.fcproj`/`.pcraft` | — |

Cortar silêncio e Normalizar têm "aplicar em": projeto e arquivo, só projeto ou só arquivo.
O original nunca é tocado, e toda vez que um projeto muda, a versão anterior vai para
`dados/marcas/<marca>/historico/projetos_antigos/` (com data e hora no nome). Depois de mexer, o projeto é
conferido com `filmcraft-cli inspect`; se o FilmCraft recusar, a cópia volta sozinha.

No preview: **abrir projeto** abre o `.fcproj` no FilmCraft (ou o `.pcraft` no PhotoCraft) e
**exportar quadro (PNG)** salva o quadro escolhido em resolução cheia na pasta `quadros/` do
post (ou do corte).

Um plugin novo é uma tabela com `info()` e `rodar(itens, params)`:

```luau
local ng3 = require("@ng3")
local M = {}

function M.info()
    return {
        nome = "Meu plugin",
        descricao = "O que ele faz.",
        aplicaA = { "video", "corte" },          -- video | imagem | post | corte
        params = {
            { id = "forca", rotulo = "Força", tipo = "numero", padrao = 3, min = 1, max = 10, passo = 1 },
            { id = "modo", rotulo = "Modo", tipo = "escolha", opcoes = { "a", "b" }, padrao = "a" },
            { id = "teste", rotulo = "Só simular", tipo = "booleano", padrao = true },
        },
    }
end

function M.rodar(itens, p)
    for _, item in itens do              -- item.tipo, item.nome, item.videos, item.imagens, item.pilar...
        for _, v in item.videos do
            ng3.processo({ "python3", "plugins/meu/meu.py", v, "--modo", p.modo })
        end
    end
    ng3.avisar("na fila")
end

return M
```

`@ng3` oferece `processo{...}`, `gerar(nomes, cortes, forcar)`, `avisar(texto)` e `acervo`.
Por segurança, a `api.py` só roda `python3` (scripts de `src/` e `plugins/`), `ffmpeg`, `ffprobe`,
`filmcraft-cli` e `photocraft-cli`, sempre dentro do acervo. Um plugin pode ainda devolver
`painel = true` no `info()` e uma função `render(view)` para desenhar um painel próprio com
`@rune/ui`.

## Desenvolvimento

```bash
cargo test                                    # filtros e plugins
BCN_ACERVO_TESTE=<acervo de teste> cargo test # + ponta a ponta com o Python
ng3-painel --snap painel.png --scene demo --acervo <acervo>   # imagem sem abrir janela
```

Cenas: `demo`, `preview`, `motion`, `recomendados`, `cortes`, `plugins` (`--size 1360x2300` para ver a página toda).

**Antes de gerar** (em cada momento): **Estilo** mostra os modelos prontos para o tipo do momento
(`config/padroes/modelos-prompt.toml`, e os da marca em `config/marcas/<marca>/modelos-prompt.toml`);
um clique escreve o briefing/prompt a partir dele. **IA: 3 abordagens** pede três caminhos
diferentes, com nome e ideia; nada é gravado até você escolher um.

**B-roll do acervo**: "procurar" (ou "procurar com IA", que escreve as buscas) acha 3–5 candidatos
em todas as fontes ativas da marca (posts, cortes, pastas extras de `acervo.toml`), no máximo 2 do
mesmo item. Clique para montar uma sequência de até 3 pedaços (o número mostra a ordem) e "usar
esta sequência" aprova o momento. O **Inserir motion** põe as sequências numa faixa "B-roll" do
projeto e grava `saidas/<vídeo>_broll.mp4`. O índice (`python3 src/achar/indice.py`) se refaz
sozinho quando tem mais de 12 h.
