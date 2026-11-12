# Modelo de projeto por postagem

Um **post = um projeto**. O acervo já está em `_posts/<ano>/<AAAA-MM-DD>_<PILAR>_<nome>/`,
então o projeto mora dentro da pasta do post e leva o nome dela:

```
_posts/2023/2023-10-18_MIC_continência-para-o-campeão/
    imagens/01.webp 02.webp …
    videos/01.mp4
    post.json
    legenda.md
    2023-10-18_MIC_continência-para-o-campeão.fcproj   ← FilmCraft (tem vídeo)
    2023-10-18_MIC_continência-para-o-campeão.pcraft   ← PhotoCraft (só imagem)
```

Regra de escolha, uma por post (nunca as duas, para não duplicar a fila de trabalho):

| conteúdo do post | projeto | por quê |
|---|---|---|
| tem ≤ 1 vídeo | **FilmCraft** `.fcproj` | reel é uma sequência; imagens entram como stills |
| só imagens | **PhotoCraft** `.pcraft` | carrossel é camada, não timeline |

## FilmCraft — `.fcproj` (modelo base 2025-07-24)

O base é o projeto
`2025-07-24_MIC_copa-micfootball-2022-o-dia-que-a-bcn-sports-academy`,
copiado para `_reciclagem/modelo_base.fcproj`. Cada projeto gerado é esse base com
vídeo, textos e tempos trocados — ids e efeitos originais preservados.

| trilha | conteúdo |
|---|---|
| **V1** | vídeo do post → transição `motion_camera` (1 s, CenterAtCut) → vídeo de `_endings` → `dip_to_black` |
| **V2** | Shape da abertura, 0 → 6 s |
| **V3** | Lower Third – Slab: **título** (Noto Music) e **subtítulo** (Inter) |
| **V4** | logo `bcn.png`, entra em 6 s, com `brightness_contrast` |
| **A1** | áudio do vídeo + do ending (vinculados ao vídeo por `link`) |
| **Música** | faixa própria com o **DeEsser** quando há legenda |
| **A2** | SFX: whoosh na abertura e no fim do título, notification, riser no corte |
| **A3** | riser de alta energia 2,2 s antes do ending |
| **C1** | legendas — **máximo 4 palavras por cartela** |

Regras de preenchimento:

- **nada pode se sobrepor na mesma faixa** — nem SFX, nem legendas. Um projeto com
  sobreposição é inválido e o app **recusa qualquer edição nele** (é o sintoma de
  "não consigo mudar as configurações"): `effects.setParam` falha em tudo

- **título** = primeiras palavras do gancho (≤ 20 caracteres, ≤ 4 palavras); o corpo
  encolhe até 55% se passar disso, senão cortava na borda do quadro
- **subtítulo** = `DD/MM/AAAA · PILAR`
- **legenda** vem do `.srt` em `transcricoes/` (mesmo caminho do vídeo), quebrada em
  cartelas de ≤ 4 palavras com tempo proporcional. **Nenhuma cartela é descartada**:
  quando o vídeo tem fala a abertura encurta para 4 s e o lower third sobe 10,5% da
  altura (y 835 → 671), para título e legenda coexistirem desde o 0 s
- **vínculo A/V**: o clipe de vídeo e o de áudio do mesmo arquivo recebem o mesmo
  `link`, senão o FilmCraft trata como dois clipes soltos e o volume do vídeo não abre
  para edição (o áudio ficava só na A1)
- **corpo da legenda: 40 pt**, base a 16% da borda — medido no render: é o tamanho que
  mantém 4 palavras em uma linha só e fica fora da interface do Instagram
- **enquadramento**: o vídeo recebe `scale = max(canvas_w/fonte_w, canvas_h/fonte_h)`
  e posição no centro — cobre 1080×1920 exatamente, sem tarja e sem sobra
  (720×1280 → 150%; 1080×1920 → 100%)
- **DeEsser** vai na faixa da **música** quando o vídeo tem legenda ativa, não no
  áudio do vídeo
- **sync lock desligado** em todas as faixas (`sync_lock=false`). O base vinha com
  todas travadas, e qualquer edição que empurrasse clipe de outra faixa morria em
  "this edit would break sync: V2 is sync-locked and has a clip in the way". A trava
  continua disponível no app, um clique por faixa — só não é imposta pelo modelo
- **validação**: todo projeto gerado é aberto com `filmcraft-cli inspect` antes de
  ser considerado pronto. Se o app recusar (item ou legenda sobrepostos), o arquivo é
  apagado e o post entra como erro na fila
- **música**: faixa própria `Música`, cortada no tamanho da sequência, a −18 dB.
  Vem de `_audio/musicas/` — hoje 9 faixas do Pixabay — escolhida por `crc32` do nome
  do post, então cada projeto tem sempre a mesma trilha, mas o acervo varia.
  `--musica arquivo.mp3` força uma faixa específica.
- **ending**: `_endings/enceramento1.mp4` (ou `--ending`)
- **logo**: `--logo` (padrão `/run/media/doykoy/SDD/Projetos BCN/Imagens/bcn.png`)

Conferido no render: frame em 2 s mostra título e subtítulo; em 9 s, legenda de 4
palavras; em 55 s, o encerramento. DeEsser presente no clipe de áudio do vídeo.

## PhotoCraft — `.pcraft`

**Um documento, um artboard por imagem** — cada canvas do carrossel vira um board
autônomo, exportável sozinho (`file.export.artboardsToFiles`).

| campo | valor | por quê |
|---|---|---|
| canvas | formato do post (1:1 → 1080×1080, 4:5 → 1080×1350, 9:16 → 1080×1920) | é o que vai para o feed |
| cor | RGB, 8 bits | é o que o Instagram aceita |
| fundo | transparente | permite recompor sem borda branca |
| artboards | um por imagem, nome `01`…`NN`, dispostos à direita com 100 px de folga | cada foto é um canvas independente; a ordem do carrossel fica visível na mesa |
| conteúdo | `file.placeEmbedded fit:true` centrado no board | imagem inteira, sem corte |
| sobrou camada vazia | `file.scripts.deleteAllEmptyLayers` no fim | o documento novo nasce com "Layer 1" |

Geometria: board *i* em `x = i × (largura + 100)`, `y = 0`. É determinístico, então
não é preciso ler o resultado de um comando para posicionar o próximo.

Exportar o carrossel inteiro em arquivos separados:

```bash
photocraft-cli run <post>.pcraft \
  --cmd file.export.artboardsToFiles --params '{"dir":"saida","format":"jpg","quality":9}'
```

Os boards são **criados de trás para frente** (imagem NN primeiro, 01 por último) de
propósito: o board mais novo fica no topo da pilha, e a exportação percorre a pilha
de cima para baixo — assim os arquivos saem em `01, 02, … NN`, na ordem do carrossel.

## Como é gerado (não é JSON escrito à mão)

O projeto é criado **pelos próprios apps, via CLI headless**, então o schema é o do
app — não uma cópia que envelhece:

```bash
# FilmCraft
filmcraft-cli --save-as <post>.fcproj run <plano>.jsonl
#   file.newProject → file.newSequence → edit.pasteMedia → markers.add

# PhotoCraft
photocraft-cli run --new '{"width":…,"height":…,"background":"transparent"}' \
    --cmd file.placeEmbedded --params '{"path":"…","fit":true}' … --out <post>.pcraft
```

Tempo medido nesta máquina: ~2,3 s por `.fcproj`, ~1,8 s por `.pcraft` (3 camadas).
1.248 posts ≈ 45 min em um processo, ~12 min com 4 em paralelo.

## Fila e controle

`gerar_projetos.py` mantém `_reciclagem/projetos.csv`:

```
post,tipo,projeto,status,segundos,erro
2023-10-18_MIC_…,fcproj,_posts/2023/…/2023-10-18_MIC_….fcproj,ok,2.3,
```

- pular o que já existe (retomável: rodar de novo continua de onde parou)
- `--forcar` regera
- `--limite`, `--pilar`, `--desde`, `--tipo video|imagem` recortam a fila
- `--workers N` paraleliza
- `--verificar N` reabre N projetos no app e confirma que carregam

## Limites conhecidos

- o `.pcraft` embute as imagens (placeEmbedded): **~2,8 MB por imagem** no board de
  1080–1440 px, porque guarda o pixel decodificado, não o arquivo (uma foto de 288 KB
  vira 3 MB). Um carrossel de 20 fotos dá ~56 MB. `--linked` economiza pouco (~5%),
  porque o custo é o canvas, não a origem.
- O `.fcproj` **não** embute mídia: caminho absoluto + fingerprint. Mover `_posts/`
  exige relink (o app faz sozinho se o arquivo voltar ao mesmo caminho).
- Vídeo sem faixa de áudio não gera problema no FilmCraft, mas também não gera trilha
  para reeditar.
- Não há campo de anotação de projeto nos dois apps; a legenda e o link vivem no
  `legenda.md` ao lado e no marcador do FilmCraft.
