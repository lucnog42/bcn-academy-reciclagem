# Reciclagem de conteúdo — @bcn_academy

Kit de organização em lote + plano de reaproveitamento para um acervo baixado
pelo 4K Stogram (3.180 mídias, 1.248 posts, 15 GB, 2021 → 2026).

## Como o acervo está hoje

Duas estruturas convivem, e o índice entende as duas:

**Organizada** (`_posts/`): cada post tem `post.json` (metadados completos),
`legenda.md` e as mídias separadas em **`imagens/`** e **`videos/`**.

**Crua**: `<midia>.<ext>.json` ao lado da mídia. A organização antiga (46 subpastas
manuais, 494 mídias) foi **desmontada** em 05/11/2026 e fundida em `_posts/`, com
`imagens/` e `videos/` separados. O nome da pasta de origem não se perdeu: está em
`movimentos.csv` e o classificador ainda o usa como pista nas 49 mídias sem legenda.

## Os três passos

```bash
cd /home/doykoy/arquivo/BCN/bcn_academy

# 1. índice (1s, não mexe em nada)
python3 _reciclagem/catalogo.py
#    -> catalogo.csv (uma linha por mídia), posts.csv (uma por post),
#       catalogo.sqlite, videos.csv, imagens.csv, relatorio_indexacao.txt

# 2. reorganizar em uma pasta por post (DRY-RUN por padrão)
python3 _reciclagem/organizar.py                  # mostra o plano
python3 _reciclagem/organizar.py --aplicar        # move de verdade
python3 _reciclagem/organizar.py --desfazer       # reverte pelo movimentos.csv
python3 _reciclagem/organizar.py --recolher-json --aplicar   # arquiva json órfão

# 3. nome legível nas pastas (mantém a data; --desfazer volta ao shortcode)
python3 _reciclagem/renomear.py                    # simula
python3 _reciclagem/renomear.py --aplicar

# 4. busca no que é falado (usa catalogo.sqlite)
python3 _reciclagem/buscar.py "visto"

# 5. plano de reciclagem + calendário
python3 _reciclagem/plano.py --n 40
python3 _reciclagem/plano.py --pilar MIC --desde 2022 --n 20
```

Por padrão o organizador **não toca nas 46 subpastas que você já organizou à mão**:
elas entram no índice e no plano, mas ficam onde estão. `--fundir-pastas` inclui
essas também (desfaz a curadoria manual).

### Estrutura de destino (já aplicada)

```
_posts/2023/2023-03-31_MIC_assim-começa-mais-uma-viagem-de-copa-mic/
    imagens/01.webp 02.jpg ... 08.jpg   # ordem original do carrossel
    videos/01.mp4                       # vazio quando o post é só foto
    metadados/03.json ...               # json das mídias 2..n (o 1º é o post.json)
    post.json                           # metadados do post
    legenda.md                          # legenda limpa + ficha do post
_sem_metadata/imagens|videos/           # mídias que vieram sem .json
```

Estado final: **1.248 pastas de post** (2021: 7 · 2022: 105 · 2023: 313 ·
2024: 350 · 2025: 251 · 2026: 226), 3.180 mídias indexadas (2.689 em `imagens/`,
491 em `videos/`), 1.248 `post.json`, 1.936 json irmãos em `metadados/`,
1.248 `legenda.md`.

Soma idêntica à original, sem nada apagado: 3.199 mídias (as 19 sem json estão em
`_sem_metadata/`) e 3.186 json (6 sem mídia em `_sem_metadata/json/`).

`movimentos.csv` guarda origem→destino de tudo (6.388 movimentos), é o que
`--desfazer` usa e a fonte do histórico de pastas (testado: 2.691 arquivos
revertidos sem perda).

## Nomes das pastas

`2023-03-31_MIC_assim-começa-mais-uma-viagem-de-copa-mic` — **data + pilar + primeira
linha útil da legenda**, sem hashtag, @menção, link ou emoji. O corte acontece em
pontuação (`. ! ? : ,`) ou fim de palavra, e remove preposição pendurada (`de`, `da`,
`com`, `recém`...), com limite de 56 caracteres. Post sem texto vira
`AAAA-MM-DD_PILAR_sem-legenda`, e nomes repetidos no mesmo dia ganham `-2`, `-3`.

O shortcode saiu do caminho da pasta, mas continua no `post.json`, no `legenda.md` e
na coluna `pastas` do `posts.csv` — dá para voltar de shortcode para pasta com uma
consulta. Ao renomear, o `movimentos.csv` é reescrito para o histórico das pastas
antigas não quebrar, e `renomear.py --desfazer` volta ao padrão `AAAA-MM-DD_shortcode`
**recomputando do `post.json`** (o log `renomeacoes.csv` é append, mas a reversão não
depende dele — senão rodar o script duas vezes já perderia a primeira passada).

## Transcrições (`transcricoes/`)

469 `.txt` + 469 `.srt` no mesmo espelho de pastas do acervo (`transcricoes/_posts/<ano>/<post>/videos/01.txt`).
Um `.txt` corresponde ao vídeo homônimo por caminho — não por nome de arquivo.

| situação | vídeos |
|---|---|
| com fala utilizável | 357 |
| transcrito mas vazio (música, silêncio) | 84 |
| sem faixa de áudio (`RuntimeError`) | 27 |
| sem transcrição (não rodou) | 23 |

Onde a fala entra:

1. **Rótulo** — só quando a legenda não decide (`OUTROS`/`SEM_LEGENDA`) e a fala tem
   evidência clara (score ≥ `FALA_MINIMA` = 4,0). 2 casos hoje.
2. **Confiança** — legenda e fala concordando somam +0,15 na confiança e ficam na
   trilha como `fala+legenda` (10 casos).
3. **Molde de legenda** — `rascunhos/*.md` traz a seção "O que é dito no vídeo", que é
   de onde sai a legenda nova quando o post tem depoimento.

**Cuidado com música.** Boa parte dos reels tem trilha: o Whisper transcreveu a letra
e ela casava termos por acidente (`"un café caliente y una risa sincera"` virava
BASTIDOR). Por isso a fala nunca sobrescreve legenda legível, e o corte de 4,0 exige
duas ou três âncoras fortes, não uma palavra solta.

### Legenda colada na fala

O Whisper acerta as palavras mas erra as bordas: a 1ª palavra depois de uma
pausa costuma "começar" 0,1–0,4 s antes da voz, e a última antes da pausa
"termina" até 1 s depois. Além disso o gerador redividia o `.srt` por
proporção e empurrava cada cartela para frente quando encostava na anterior,
o que acumulava atraso ao longo do vídeo.

Agora:

- `voz.py` mede onde há voz no áudio (Silero VAD, o mesmo que já vem no
  faster-whisper, + energia a cada 10 ms) e move a borda de cada palavra que
  caiu no silêncio até a voz. O `.words.json` guarda as duas versões:
  `palavras` (refinadas, é o que a legenda usa) e `palavras_whisper` (cruas).
- `legendas.py` é a regra única da cartela, usada pelo `legendar.py` e pelo
  gerador: entra no começo da fala, sai 0,08 s depois, no máximo 4 palavras,
  quebra em pausa > 0,25 s, nunca empurra a seguinte.
- O gerador monta a legenda direto do `.words.json`, já na timeline com o
  silêncio cortado, alinhada ao quadro do vídeo.

```bash
# corrige o que já foi transcrito, sem rodar o modelo de novo (segundos por vídeo)
python3 _reciclagem/legendar.py --raiz _Cortes --so-srt --aplicar
python3 _reciclagem/legendar.py --raiz _posts  --so-srt --aplicar

# confere: quanto a legenda entra antes/depois da voz e quanto sobra na tela
python3 _reciclagem/conferir_legendas.py --raiz _Cortes
python3 _reciclagem/conferir_legendas.py --arquivo <vídeo.mp4> --detalhe

# regras da cartela
python3 -m unittest discover -s _reciclagem/testes
```

Depois de corrigir os `.srt`, gere de novo os projetos que já existem
(`gerar_projetos.py ... --forcar`): o `.fcproj` antigo guarda a legenda velha.

### Buscar no que é falado

```bash
python3 _reciclagem/buscar.py "visto"                       # só legenda não acha isso
python3 _reciclagem/buscar.py "bolsa de estudos" --pilar INTERCAMBIO
python3 _reciclagem/buscar.py gol --desde 2024 --n 20
```

Usa a tabela FTS5 `falas` do `catalogo.sqlite` (texto, vídeo, post, pilar, data).

## App nativo (`_reciclagem/app/`) e plugins

O painel agora também existe como app nativo (Rune), em `_reciclagem/app/`:
mesma grade, filtros, recomendados, cortes, preview e marcações, mais uma aba de plugins
Luau. Instruções de compilação em `_reciclagem/app/README.md`. O app conversa com o Python por:

| arquivo | papel |
|---|---|
| `api.py` | ponte JSON por stdin/stdout (`serve`) ou uma chamada só (`chamar posts`) |
| `config.py` + `config.toml` | caminhos do acervo (logo, aberturas, endings, músicas) e opções; segredos em `config.local.toml`, fora do git |
| `midia.py` | miniaturas, tiras de quadros e info de mídia com cache em `.cache/` |
| `plugins/<nome>/init.luau` | plugins: silencecut, gerar projeto, legendar, normalizar áudio |

O `gerar_projetos.py` passou a ler o `config.toml` e, quando existe, o `montagem.json` do
post (ou `<corte>.montagem.json`) com a música, o encerramento e o título escolhidos.

## Painel visual (`painel.html`)

```bash
python3 _reciclagem/painel.py     # gera <acervo>/painel.html (1,4 MB, autocontido)
```

Abre com duplo clique, sem servidor: dados embutidos no arquivo, mídia por caminho
relativo. O que dá para fazer:

- **buscar** na pasta, na legenda e na fala transcrita (um campo só)
- **filtrar** por ano, pilar (contador em cada pastilha), tipo (`fcproj`/`pcraft`) e
  "só sem projeto"
- **ver** abre o preview do post: todas as mídias em ordem, legenda original, fala
  transcrita, curtidas, confiança do pilar, formato da sequência e link do Instagram
- **hover** num card de vídeo carrega o primeiro frame (nada é pré-carregado na grade)
- **marcar** cartões e **exportar seleção** → `selecao-bcn.json` em Downloads
- badge `PROJETO ✓` marca o que já foi gerado; rodar `painel.py` de novo atualiza

### Marcações de curadoria

| botão | efeito |
|---|---|
| **NI** | não interessante — sai da fila do `plano.py` e fica esmaecido |
| **RP** | já repostado — idem, e é a marca que evita republicar pela terceira vez |

Ficam em `_reciclagem/estados.json`, aplicadas pelo `plano.py`
(`--incluir-marcados` ignora) e visíveis no filtro `status`.

### Aba "recomendados"

Ranking pelo mesmo score do `plano.py` (agora em `bcnlib.pontuar`), com a
decomposição visível por linha: `alcance`, `evergreen`, `material`, `maturidade` e
`penal` (post recente ou legenda repetida). Serve para decidir antes de olhar o
acervo inteiro.

### Dois modos

```bash
python3 _reciclagem/painel.py      # gera painel.html — modo arquivo
python3 _reciclagem/servidor.py    # modo servidor em http://127.0.0.1:8765
```

- **arquivo** (`file://`): tudo funciona, mas marcações ficam no `localStorage` e
  o botão gerar apenas copia o comando.
- **servidor** (`http://127.0.0.1:8765`): LED verde no topo, marcações gravadas
  direto em `estados.json` e o botão **gerar projeto** roda o `gerar_projetos.py`
  de verdade e atualiza o badge `PROJETO ✓` na hora.

O ciclo completo:

```bash
python3 _reciclagem/servidor.py                 # ou só painel.py
# abre http://127.0.0.1:8765 → filtra → marca NI/RP → seleciona → gerar projeto
python3 _reciclagem/plano.py --n 40             # já ignora o que foi marcado
```

### Peso: o que ninguém espera do `.pcraft`

O PhotoCraft guarda o canvas decodificado, não o arquivo: **uma imagem de 288 KB
vira um projeto de 6,4 MB** (1440×1440×4 bytes + preview). `--linked` economiza
quase nada (6,1 MB) porque o custo é o pixel, não a origem.

| cenário | espaço |
|---|---|
| os 803 posts de imagem, todos | **~15,9 GB** |
| só o que você selecionar no painel | alguns GB |

Por isso o painel mostra `~X MB de projeto` no rodapé e no preview, e a geração em
massa deve ser por seleção, não "tudo". O `.fcproj` é ~6 KB (só referencia).

## Cortes (`_Cortes/`)

74 vídeos (65 min) organizados por tema — `depoimentos hotel/1..30`, `Fernando`,
`Costa RIca`, `Futebol Campeao`… Cada corte traz `.srt` e `.txt` **ao lado** (não no
espelho de `transcricoes/`, como os posts).

Entram no sistema em três lugares:

| onde | o que dá para fazer |
|---|---|
| `_reciclagem/cortes.csv` + tabela `cortes` no SQLite | tema, pilar, duração, tamanho, transcrição |
| `gerar_projetos.py --tipo corte` | um `.fcproj` por corte, com legenda do `.srt` lateral |
| aba **cortes** do `painel.html` | busca na fala, filtro por pilar, botão gerar |

```bash
python3 _reciclagem/catalogo.py                      # indexa cortes junto
python3 _reciclagem/gerar_projetos.py --tipo corte --limite 5      # simula
python3 _reciclagem/gerar_projetos.py --tipo corte --aplicar       # todos
python3 _reciclagem/gerar_projetos.py --tipo corte --corte 20260324_103456_corte.mp4 --aplicar
```

O projeto nasce ao lado do corte, com o nome `<Tema>_<stem>.fcproj`
(`_Cortes/Costa RIca/Costa-Rica_20260326_092810_corte.fcproj`), e segue o mesmo modelo
do FilmCraft: abertura com título (tema) + subtítulo (pilar · data), legenda de 4
palavras vinda do `.srt` lateral, música e encerramento.

O pilar do corte vem do tema (`depoimento*` → DEPOIMENTO, `futebol`/`jogo` → JOGO) e,
quando o tema é o nome de uma pessoa, da própria fala — entrevista sem palavra-chave
cai em DEPOIMENTO em vez de OUTROS.

## Projetos FilmCraft / PhotoCraft

Um post vira um projeto, dentro da própria pasta, com o nome dela:

```
_posts/2023/2023-10-18_MIC_continência-para-o-campeão/
    2023-10-18_MIC_continência-para-o-campeão.fcproj   tem vídeo
    2023-10-18_MIC_continência-para-o-campeão.pcraft   só imagem
```

```bash
python3 _reciclagem/gerar_projetos.py --limite 5            # simula
python3 _reciclagem/gerar_projetos.py --aplicar --workers 4
python3 _reciclagem/gerar_projetos.py --tipo imagem --aplicar
python3 _reciclagem/gerar_projetos.py --pilar MIC --desde 2024 --aplicar
python3 _reciclagem/gerar_projetos.py --verificar 5         # reabre e confere
```

Os projetos são criados **pelos próprios apps via CLI headless** (`filmcraft-cli run`,
`photocraft-cli run`), então o schema é o do app, não um JSON escrito à mão.
Modelo completo, decisões e limites em `MODELO_PROJETOS.md`.

| | FilmCraft `.fcproj` | PhotoCraft `.pcraft` |
|---|---|---|
| para | post com vídeo (445) | post só de imagem (803) |
| modelo | **base 2025-07-24** (`_reciclagem/modelo_base.fcproj`): abertura com título/subtítulo, legenda ≤4 palavras, DeEsser, ending de `_endings`, SFX | — |
| sequência/canvas | 9:16→1080×1920, 1:1→1080×1080, 4:5→1080×1350 | tamanho da maior imagem, RGB 8-bit, fundo transparente |
| mídia | vídeos + imagens como stills de 5 s | **um artboard por imagem** (`01`…`NN`), imagem centrada |
| exportar | sequência inteira | `file.export.artboardsToFiles` → um arquivo por foto |
| contexto | marcador no frame 0 com a URL do post | `legenda.md` ao lado |
| tamanho | ~6 KB (não embute mídia) | ~2,8 MB por imagem (pixel decodificado) |

Fila retomável em `projetos.csv` (pula o que existe, `--forcar` refaz).

Opções do modelo FilmCraft:

```bash
python3 _reciclagem/gerar_projetos.py --tipo video --aplicar \
    --musica ~/Downloads/pixabay-faixa.mp3 \
    --ending _endings/enceramento1.mp4 \
    --logo "/run/media/doykoy/SDD/Projetos BCN/Imagens/bcn.png"
```

A música também é achada sozinha em `_audio/musicas/` (primeira em ordem alfabética).
Sem arquivo lá, o projeto sai sem trilha — o resto do modelo não muda.

## O que o plano entrega

| arquivo | para quê |
|---|---|
| `plano_reciclagem.csv` | uma linha por post selecionado: score, pilar, confiança, idade, curtidas vs mediana, pasta, ângulo, formato de saída. Abre no Sheets/LibreOffice. |
| `videos.csv` | 491 vídeos com caminho absoluto — entrada de lote para ffmpeg/EffectCraft |
| `imagens.csv` | 2.689 imagens, mesmo formato |
| `pastas_manuais.csv` | mapa das suas subpastas: mídias, posts, pilar predominante, tamanho |
| `PLANO.md` | leitura rápida: distribuição por pilar, top 15, calendário de 4 semanas (3 posts/semana) e regras anti-penalização. |
| `renomeacoes.csv` | log antigo→novo de cada pasta renomeada (`renomear.py --desfazer`) |
| `rascunhos/NN_shortcode.md` | molde de legenda por post: pasta, gancho, contexto, prova, CTA, hashtags, saída e checklist. |

### Como o score é calculado

```
35  alcance     percentil de curtidas no acervo (não curtidas/maior — um viral de 33k zeraria o resto)
20  evergreen   quantas âncoras reaproveitáveis a legenda tem (oportunidade, intercâmbio, sonho, bolsa...)
20  material    nº de mídias no carrossel + bônus para vídeo
25  maturidade  quanto mais antigo, mais pode voltar (>=3 anos = 25)
-25 penalidade  post com menos de 150 dias (repost recente não rende)
```

Nenhum pilar passa de 40% da seleção — o torneio MIC é 2/3 do acervo e sem o
teto o plano inteiro viraria "MIC de novo".

## Suas subpastas organizadas

O índice varre a árvore inteira: 2.686 mídias soltas na raiz + **494 em 46 subpastas
manuais** (201 posts). Todas entram no catálogo e concorrem no plano — 6 dos 40
selecionados vinham de subpasta.

| pasta | mídias | posts | pilar predominante |
|---|---|---|---|
| Jogos Grandes | 92 | 31 | MIC |
| Fotos Esporte Mic 2022 | 61 | 10 | MIC |
| Fotos Mic 2024 | 50 | 15 | MIC |
| Lucas JR | 46 | 11 | INTERCÂMBIO |
| Grupos Mic 2023 | 31 | 6 | MIC |

O mapa completo está em `pastas_manuais.csv`, e a coluna `pastas` do `posts.csv`
diz de qual pasta cada post veio.

O nome da pasta é curadoria humana, então vale como **pista de classificação —
só quando a legenda não decide** (posts em `OUTROS` ou `SEM_LEGENDA`). Resgatou 49
mídias: "Fotos Esporte Mic 2022" (30 sem legenda → MIC), "Juvenil 2022 x Barca"
(9 → JOGO), "treino fernando marcet" (→ BASTIDOR, não INTERCÂMBIO: a lista de pistas
é ordenada, treino vem antes do programa). Fica marcado em `resgatado_por=pasta`
com confiança 0.35, para você saber que não foi o texto que decidiu.

## Como o rótulo é decidido (a legenda manda)

`bcnlib.rotular()` lê a legenda inteira, não a primeira palavra que encontra:

1. **Termos com peso** em `TERMOS`: 3 = específico do tema (`gol de`, `peneira`,
   `camp day`), 2 = contextual (`espanha`, `treino`), 1 = fraco/ambíguo (`cidade`,
   `vaga`). São ~30 termos por pilar, incluindo espanhol (`equipo`, `partido`, `tour`).
2. **Zonas com multiplicador**: 1ª linha ×2 (é onde o post declara o assunto),
   corpo ×1, hashtags ×1.2 (rótulo que o autor escolheu).
3. **Retorno decrescente** (`0.6^i` sobre as evidências ordenadas): um termo forte
   vale mais que cinco fracos somados. Sem isso, `treino` perdia para a soma de
   `obrigado` + `gratidão` + `experiência`, que aparecem em qualquer rodapé.
4. **Fronteira de palavra** em toda chave via lookaround: `direct` não casa em
   "eliminación directa", `marque` não casa em "marcaram", `mic` não casa em
   "acadêmica".
5. **`confianca`** = score do 1º / (1º + 2º). Abaixo de 0.6 é empate técnico —
   está na coluna do CSV justamente para você revisar esses primeiro.
6. **`EVIDENCIA_MINIMA` = 2.5**: legenda fraca ("#copadiadorabandsub20") não
   sustenta rótulo. Aí tenta `location_name` e, se não houver, cai em `OUTROS`.
7. **`SEM_LEGENDA`** é balde próprio, separado de `OUTROS`: ausência de texto não é
   tema desconhecido, e misturar os dois escondia 69 posts sem critério nenhum.

`classificar_prioridade()` mantém o método antigo (primeiro pilar da lista que
casar) só para comparar. Ele rotulava 66% do acervo como MIC; lendo a legenda,
ficou 45% MIC / 28% INTERCÂMBIO / 7% JOGO, com média de confiança 0.62.

### Pilares (posts, não mídias)

MIC 559 · INTERCÂMBIO 345 · JOGO 85 · SEM_LEGENDA 69 · OUTROS 64 · BASTIDOR 52 ·
ATLETA 33 · AVALIAÇÃO 24 · DIVULGAÇÃO 13 · DEPOIMENTO 4.

Nenhum pilar passa de 40% da seleção. Posts que repetem a legenda de outro post
(184 no acervo) recebem −20 no score, exceto o de melhor desempenho do grupo —
o perfil já reciclou aquele texto internamente.

## Consultas úteis no índice

```sql
-- posts com melhor desempenho relativo por pilar
select pilar, post_shortcode, curtidas, data from posts
where curtidas > 300 order by pilar, curtidas desc limit 20;

-- quanto material de cada pilar está velho o suficiente para repostar
select pilar, count(*) from posts where data < date('now','-18 months') group by 1;

-- atletas citados (tags)
select tags, count(*) c from posts where tags<>'' group by 1 order by c desc limit 15;
```

## Rotina semanal (o workflow em si)

1. **Segunda** — abre `PLANO.md`, pega os 3 posts da semana, marca o que já foi usado
   numa coluna extra do CSV (`status`: pendente / editado / publicado).
2. **Terça** — baixa os arquivos da pasta do post, refaz a capa (a 1ª imagem decide o
   alcance) e corta o reel. Se o material for antigo, o gancho precisa ser novo.
3. **Quarta/Quinta** — escreve a legenda em cima do molde do `rascunhos/`, sem copiar
   a original.
4. **Sexta** — publica, e anota curtidas em 48h no CSV. Depois de 3 meses dá para
   recalibrar o score com o desempenho real do repost.

## Limitações conhecidas

- `likes` é o número no momento do download — serve para comparar posts entre si, não
  como métrica atual.
- 6 JSONs apontam para mídia que não existe mais; 19 mídias vieram sem JSON.
- Carrossel antigo em 1:1 precisa de moldura 4:5 no feed, ou vira reel.
- Áudio original de 2022–2023 não deve ser reaproveitado: entrega cai. Trilha nova.
