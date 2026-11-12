# 07 — Diagnóstico de hardware e espaço: `/run/media/doykoy/F2A084D7A084A3A7/BCN`

Medido nesta máquina, em 12/11/2026. Todo número aqui foi medido, não estimado — a origem de cada
um está anotada. O que não foi medido está marcado como **estimativa**.

## 1. O que a pasta é

Varredura completa (`find -printf`, 4 min 14 s): **201.090 arquivos, 1.900 GB**.

| grupo | GB | % | conteúdo |
|---|---|---|---|
| Vídeo (mp4/mov/mts) | 863 | 45% | 3.515 arquivos, **54,1 h** de gravação |
| RAW (nef/dng) | 823 | 43% | 53.466 arquivos em 46 sessões de foto |
| JPG/TIFF/HEIC | 116 | 6% | 9.095 arquivos (muitos são exportação final) |
| Cache | 75 | 4% | `.lrprev`, `.lrcat-data`, `.pek`, `.cfa`, Auto-Save |
| Outros | 22 | 1% | 14.088 `.xmp`, 620 `.XML`, 578 `.srt/.txt`, `.db` |

Vídeo por codec (3.459 de 3.464 medidos com `ffprobe`): h264 1.565 · hevc 1.187 · prores 704 ·
781 arquivos em 4K · média **31 Mbps**. O mais longo tem 4 h; a mediana é 24 s.

Comparação com o acervo que o plano conhece: este não é o acervo de 15 GB. É o **arquivo bruto** —
1,9 TB, 63× o volume, 63× o número de mídias.

## 2. Categorias e o melhor método para cada uma

A regra que economiza mais tempo não é paralelizar: é **não ler o que não precisa ser lido**.

| # | categoria | volume | método | por que | custo medido |
|---|---|---|---|---|---|
| A | Catálogo Lightroom (`.lrcat`) | 485 MB (2 arquivos) | abrir como SQLite **antes de qualquer outra coisa** | 1 arquivo dá rating, cor e palavra-chave de 38.373 fotos | 2 min de cópia |
| B | RAW `.nef` | 53.466 / 815 GB | extrair **preview JPEG embutido** (`exiv2 -ep3`), nunca decodificar o RAW | preview de 1,2 MB vs 15 MB; sai thumb + dhash do mesmo arquivo | **39 ms/arq** com processo por arquivo → ~15–25 ms em processo vivo |
| C | JPG exportado | 9.095 / 116 GB | thumb 512 com `draft()`, sem decode completo | mesma saída do B | **428 ms/arq** em processo vivo (vs 2.841 ms com um processo por arquivo) |
| D | Vídeo | 3.515 / 863 GB / 54,1 h | `ffprobe` só cabeçalho → **uma passada de decode** que gera proxy 360p *e* amostra frames | duas passadas de decode custam o dobro | ffprobe: **25 min** para todos · proxy 1080p h264: **7,1×** tempo real · 4K60 HEVC 10-bit: **0,34×** (software) / **1,5×** (`-hwaccel cuda`) |
| E | Exportações (`Projetos/`, 160 GB) | 930+ arquivos | catalogar como “pronto”, não reprocessar | são o resultado, não a matéria-prima | 0 |
| F | Cache Adobe/Lightroom | 75 GB | excluir do índice por regra de caminho | 100% derivado, recriável | 0 |
| G | Sidecars (`.xmp`, `.XML`, `.srt`) | 14.708 arquivos | ler como metadado, 4 KB cada | `.xmp` = curadoria já feita; `.XML` Sony = timecode; `.srt` = transcrição pronta | 0,6 s/arq em acesso aleatório |

Dois achados que mudam o plano:

1. **A curadoria humana de parte das fotos já existe.** O catálogo Lightroom tem 38.373 imagens com
   rating e cor (`Verde`, `Vermelho`, `Amarelo`) e 35.367 palavras-chave (`Infantil`, `Juvenil`,
   `12A`, `13B`, `treino`, nomes de atleta). Ressalva honesta: só **1.551 fotos (4%)** têm rating ou
   cor — o catálogo serve para **agrupar**, não para decidir. Já as palavras-chave cobrem quase tudo
   e dão a taxonomia de graça.
2. **`Videos Mic/Depoimentos` já tem `.srt` e `.txt`** (289 de cada): não re-transcrever.

## 3. A regra de ouro: uma passada, na ordem das pastas

O acesso aleatório neste disco é o inimigo. Medições:

| operação | resultado |
|---|---|
| `stat` de 201.090 arquivos (metadado puro) | **4 min 14 s** → 790 arq/s |
| 80 `.xmp` sorteados (4 KB cada) | 47 s → **0,6 s/arquivo** |
| leitura sequencial de trecho já em cache | **101 MB/s** |
| leitura fria, mesma faixa, sem cache | **4–5 MB/s** |
| 300 `.xmp` sorteados | >10 min (abortado) |

Consequência prática: um processo Python **vivo**, percorrendo as pastas em ordem, lendo cada
arquivo uma única vez. Trocar isso por “um processo por arquivo” custou 6,6× no teste de JPG
(2.841 ms → 428 ms). Trocar por acesso sorteado custa 10× ou mais.

E **cuidado com leitura concorrente**. Mesmo teste (30 JPGs, mesmo código), três condições:

| condição | ms/arquivo |
|---|---|
| sozinho, disco ocioso | 428 ms |
| com 3 leitores sequenciais em paralelo (`dd` em vídeos) | 422–646 ms |
| com 6 `ffprobe` varrendo arquivos de até 26 GB em paralelo | ~2.584 ms |

Leitura sequencial concorrente quase não atrapalha; **seek concorrente destrói** — abrir 6 arquivos
gigantes ao mesmo tempo no mesmo prato é o pior padrão possível neste disco. Regra: um leitor
sequencial; threads só para CPU (hash, thumb, encode), alimentadas por uma fila que lê em série.
As 6 threads do `ffprobe` acima foram erro meu — o lote cheio roda em série.

Bytes que o tratamento realmente precisa ler, com esse método:

| etapa | bytes lidos | % do acervo |
|---|---|---|
| catálogo LR + XMP + XML + srt | ~1 GB | 0,05% |
| previews NEF (≈1,5 MB dos 15 MB) | ~80 GB | 4% |
| JPG inteiros | 116 GB | 6% |
| vídeo (decode para proxy e corte) | 863 GB | 45% |
| cache | **0** | 0% |
| **total** | **~1,06 TB** | **56%** |

## 4. A interface humana é a estrutura de pastas

A pasta já é o lote. Não existe tela de 200 mil itens.

Unidades de revisão (contadas):

- **46 sessões de foto** (`Fotos Mic 2024/` 23 + `Fotos Mic 2025/` 23 — `Catalogo Mic 2024` não é sessão, é cache);
- **17 sessões de vídeo** (`Videos Mic/` 15 + `Videos Mic 2025/` 2);
- **19 de projeto** (`Projetos/`).

Distribuição das sessões de foto: 5 acima de 60 GB, 14 entre 10 e 60 GB, **27 abaixo de 10 GB**.
Ou seja: metade do acervo cabe em lotes pequenos, que são baratos de aprovar.

Desenho da fila:

- **um cartão por sessão**: nome, nº de itens, GB, palavras-chave dominantes do Lightroom,
  pilar sugerido + confiança, e três botões — `[Aceitar lote]` `[Revisar N piores]` `[Ignorar]`;
- **dentro da sessão**: grade de contatos, uma tecla por decisão (`1–5` pilar, `X` descarta,
  `Enter` aceita a sugestão, `→` próximo). Filtro padrão: confiança mais baixa primeiro;
- **regra de lote**: se ≥80% dos itens da sessão concordam com a sugestão, um clique fecha o lote —
  é o que evita 46 sessões virarem 46 noites;
- **progresso por sessão** em `marcacoes/revisao.json` (status por sessão, não por item): retomável
  e legível em uma tela;
- **cada correção vira regra** em `config/marcas/bcn/regras.yaml`, como já previsto no doc 06.

Custo humano estimado: 46 + 17 cartões × ~2 min = **~2 h de decisão de lote**, mais os ~15% de
confiança baixa (~9 mil itens × 1,5 s ≈ 4 h) revisados só onde a máquina não decidiu. Total
**4–6 h**, contra as 18 h do plano original.

## 5. Espaço em disco

| saída | tamanho | onde |
|---|---|---|
| índice `catalogo.sqlite` + FTS | ~0,5 GB | `dados/marcas/bcn/indice/` (no projeto) |
| thumbs 512 webp (62,5 mil × ~20 KB) | 1,3 GB | SDD |
| proxy 360p (54,1 h @ 700 kbps) | **17 GB** | SDD |
| frames para visão (~8 mil × 250 KB, temporário) | 2 GB | SDD (apagável) |
| embeddings CLIP (512-d float32) | 20 MB | junto do índice |
| **total** | **~21 GB** (reservar 30 GB) | |

Onde não colocar:

- **root `/`**: 24 GB livres, 96% cheio. Não cabe com folga e ainda é o disco do sistema.
- **o próprio acervo (NTFS, 210 GB livres, 95% cheio)**: cabe, mas ler e escrever no mesmo disco
  USB corta a velocidade pela metade — e não é lugar de artefato derivado.
- **`/run/media/doykoy/SDD` (exFAT, 701 GB livres)**: é o destino certo para proxy, thumbs e frames.

## 6. Hardware: o que aguenta e o que trava

| componente | estado | veredito |
|---|---|---|
| CPU | Ryzen 7 6800HS, 8C/16T | suficiente; `ffmpeg` e o indexador não pedem mais |
| GPU | RTX 3050 Laptop, **4 GB** VRAM | dá nvenc (7,1× tempo real) e um modelo de visão 2B quantizado; **não** dá 7B |
| RAM | 14 GB, 12 em uso, **2,6 GB disponíveis**, zram 14,9 GB com 7,5 GB usados | **é o gargalo** — paralelismo 2–4, não 16; fechar Chromium/Hermes nos lotes longos |
| Disco do acervo | WD easystore 4 TB, USB 3.0 (link 5 Gbps, confirmado), SMR, NTFS | **define o cronograma**: 4–25 MB/s frio, 100 MB/s em cache |
| Disco de trabalho | NVMe 745 GB exFAT, 701 GB livres | 2,6 GB/s; folga de sobra |
| `ffmpeg` 9.0.2 | com `nvenc`, `nvdec`, `cuda` | usar `-hwaccel cuda` no lote (não testado ainda — validar em 1 vídeo antes) |

Nenhum upgrade de hardware resolve o gargalo: o limite é a leitura do SMR por USB. O que resolve é
ler menos (seções 2 e 3) e não duplicar arquivo (clipe referenciado, não recortado).

## 7. Cronograma (máquina desassistida)

| etapa | tempo | medida? |
|---|---|---|
| varredura + índice de caminhos | 5 min | ✅ medido |
| catálogo LR + XMP + XML | 5 min | ✅ medido |
| `ffprobe` dos 3.464 vídeos | 25 min | ✅ medido |
| thumbs + dhash das imagens (62,5 mil) | 1,5–2,5 h | estimativa sobre 39 ms/428 ms medidos |
| proxy 360p **+** amostragem de frames na mesma passada (54,1 h) | 10–14 h **com** `-hwaccel cuda` · **~40 h sem** | medido: 4K10bit 0,34× software vs 1,5× cuda |
| visão nos clipes (6–12 mil) | 2–4 h local · 30 min API | estimativa |
| revisão humana por sessão | 4–6 h (você) | estimativa |
| **total** | **~16–20 h de máquina + 1 dia seu** (com hwaccel) | |

## 7.1 Não existe corte de cena neste material (medido)

Detecção de cena em 4 amostras de 120 s (limiares 0,08 / 0,15 / 0,30):

| amostra | cortes > 0,15 | cortes > 0,30 |
|---|---|---|
| jogo 1080p60 (`C0314.MP4`) | 1 | 0 |
| jogo 4K (`DSC_2321.MP4`) | 0 | 0 |
| bastidor (`C0356.MP4`) | 0 | 0 |
| export 4K (`Projetos/Evento/…mp4`) | 0 | 0 |
| depoimento (`Depoimentos/Para Editar/Uteis/20260402_190526.mp4`) | 0 | 0 |

São gravações contínuas de câmera única — não há corte para detectar. O “clipe por corte de cena”
do doc 06 (1.500–3.900 clipes) **não descreve este acervo**: aqui o clipe tem de nascer de
**amostragem por tempo** (ou de pico de movimento), e o número passa a ser decisão de projeto, não
consequência do material. 54,1 h divididas em janelas de 8 s = 24.340 frames; de 20 s = 9.736.

## 7.2 Custo de API para visão

Preço em 12/11/2026 (USD/BRL 5,5813). Frame enviado a 512 px; prompt fixo 60 tok, saída 90 tok
(descrição + pilar + confiança); margem de 10% para retry.

| modelo | US$/1M in | US$/1M out | 1.000 frames | 24.340 frames (54 h em janelas de 8 s) |
|---|---|---|---|---|
| qwen3-vl-8b | 0,08 | 0,50 | **US$ 0,13** (R$ 0,75) | **R$ 18** |
| gpt-5.4-nano | 0,20 | 1,25 | US$ 0,20 (R$ 1,14) | R$ 28 |
| gemini-2.5-flash | 0,30 | 2,50 | US$ 0,35 (R$ 1,97) | R$ 48 |
| claude-haiku-4.5 | 1,00 | 5,00 | US$ 0,90 (R$ 5,02) | R$ 122 |

Outras contas, mesmos preços:

| trabalho | frames | nano | qwen3-vl | flash | haiku |
|---|---|---|---|---|---|
| vídeo, janelas de 8 s | 24.340 | R$ 28 | R$ 18 | R$ 48 | R$ 122 |
| vídeo, janelas de 20 s | 9.736 | R$ 11 | R$ 7 | R$ 19 | R$ 49 |
| fotos (62,5 mil) | 62.500 | R$ 71 | R$ 47 | R$ 123 | R$ 313 |
| **só o que a local não resolveu (25%)** | 6.085 | **R$ 7** | **R$ 5** | R$ 12 | R$ 31 |

Conclusão: a visão por API **não é o custo relevante deste projeto** — R$ 18 a R$ 48 para descrever
as 54 h de vídeo. O custo real é tempo de máquina (16–20 h) e revisão humana (4–6 h). Com batch
(50% de desconto na OpenAI e no Google) e frame de 384 px, o total do vídeo cai para ~R$ 10.


## 8. O que continua travando (as decisões do doc 06, agora com número)

1. **Onde roda a visão** — com 4 GB de VRAM: local serve para triagem em massa; API só para o que
   a triagem não resolveu. Mandar frame de menor para fora continua sendo decisão sua.
2. **Referenciar ou copiar os arquivos novos** — copiar 1,9 TB a 4–20 MB/s leva **27 a 130 h**.
   Referenciar custa zero.
3. **GPU** — existe, mas 4 GB: limita o modelo local a ~2B quantizado.
4. **Teto de custo da visão** — R$ 18–48 para o vídeo inteiro (24.340 frames), R$ 5–7 se a API só
   pegar o que a triagem local não resolveu. Um teto de R$ 100 cobre vídeo + fotos com folga.

## 9. Próximo passo sugerido (barato, antes de qualquer código novo)

Rodar as etapas já medidas como um “diagnóstico de 1 hora”: catálogo LR → `ffprobe` → thumbs de
**uma** sessão de foto e proxy+corte de **um** vídeo de cada tipo (depoimento, jogo, 4K). Isso
confirma os tempos acima com o dado real da máquina antes de comprometer as 16–20 h do lote cheio.
