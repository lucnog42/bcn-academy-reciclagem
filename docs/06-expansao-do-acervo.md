# 06 — Expansão do acervo: plano

Escopo: chegam mais arquivos, e o acervo precisa (a) entrar sem duplicar, (b) ser fatiado em
clipes por corte de cena, (c) ganhar contexto por IA de visão, (d) ser catalogado em massa por
você, sem revisar 3.000 itens um por um.

Nada aqui é executado ainda. É plano, com as decisões que travam cada etapa.

## O problema real da expansão

Quatro riscos, em ordem de estrago:

1. **Duplicata silenciosa.** Reimportar o acervo antigo junto com o novo é o erro mais provável —
   e o mais caro, porque contamina o plano de reciclagem com o mesmo post duas vezes.
2. **Mídia sem fala e sem legenda.** No acervo atual: 69 posts sem legenda, 23 vídeos nunca
   transcritos, 84 transcritos vazios (música/silêncio). É justamente aí que a IA de visão paga.
3. **Fila de revisão maior que a sua paciência.** Se cada item exigir 20 segundos de atenção,
   3.199 mídias = 18 horas. Sem atalho de teclado e agrupamento, a catalogação em massa morre na
   segunda sessão.
4. **Custo de visão em tudo.** Descrever cada frame de cada clipe pode custar mais caro que o
   valor do catálogo. Tem que ser por amostragem, com medição em lote pequeno antes.

## As quatro capacidades

### A. Ingestão (`src/acervo/ingestao/`)

Recebe uma pasta de arquivos novos (ou um `.zip`) e coloca no layout do acervo sem tocar no que
já existe.

- **idempotente por hash**: `sha256` do arquivo identifica "já tenho"; `dhash` perceptual pega
  repost e recompressão (mesma foto, outro JPEG).
- **lote** com id (`AAAA-MM-DD-<origem>`) gravado em `dados/marcas/<marca>/historico/ingestao.csv`
  — é o que permite desfazer uma importação inteira e o que agrupa a revisão depois.
- **nunca move nem apaga o original**: copia, ou registra o caminho externo (`--referenciar`).
- dry-run por padrão, como `organizar.py` já faz hoje.

Saída: candidatos a post/mídia, com pilar provável, mais o relatório do que foi ignorado e por quê.

### B. Segmentação por corte de cena (`src/acervo/segmentacao/`)

Divide cada vídeo em clipes por mudança de cena, e **guarda referência, não arquivo**.

```
clipe = { video: <arquivo>, inicio_s: 12.4, fim_s: 15.8, frame_hash, cena_score }
```

- Detecção offline, sem GPU: `ffmpeg select='gt(scene,X)'` ou PySceneDetect (content detector),
  com dois parâmetros por marca em `config/padroes/segmentacao.yaml`:
  `sensibilidade` e `duracao_minima_s`. Corte de câmera em vídeo de jogo e em depoimento pedem
  limiares diferentes — daí ser configuração, não constante.
- **por que não recortar arquivo**: 491 vídeos já são parte dos 15 GB; recortar em clipes
  multiplicaria o acervo em disco e criaria duas fontes de verdade (o clipe e o vídeo). O clipe é
  uma linha no índice.
- **proxy 360p só para revisão**, gerado uma vez por vídeo, para o painel abrir clipe sem carregar
  1080p do disco de rede.
- clipes entram no catálogo como **candidatos a b-roll** — é isso que liga esta etapa à parte 2
  (`src/achar/`): "treino no Marcet" passa a devolver trechos, não só posts.

Saída: tabela `clipes` no `catalogo.sqlite`, com `video_id`, tempos, thumbnail e hash de frame.

### C. Contexto por IA de visão (`src/acervo/visao/`)

Para cada clipe (e para cada imagem sem legenda), extrai frame e pede uma descrição.

- **dois campos separados, de propósito**:
  - `descricao` — texto livre, para busca ("jogador de costas comemorando no gramado molhado");
  - `pilar_sugerido` + `confianca` — taxonomia fechada, do mesmo jeito que o `bcnlib` já faz com
    legenda e fala.
- **a visão é a terceira pista, com o menor peso.** A lição da música transcrita pelo Whisper vale
  igual: a IA de visão **nunca sobrescreve** legenda legível. Ela decide só onde legenda e fala
  não decidiram (`OUTROS`, `SEM_LEGENDA`) e escreve em coluna própria (`via_visao=1`).
- **amostragem**: 1 frame por clipe com duração ≤ 8 s; 3 frames (início/meio/fim) para clipes
  longos. Não é vídeo, é frame — custo por item, não por segundo.
- **embeddings** (CLIP) dos mesmos frames: busca por semelhança sem gerar texto, roda em CPU e
  serve para "me dá todos os clipes parecidos com este".
- **prompt fixo e versionado** em `config/padroes/visao.yaml`: o mesmo frame, com o mesmo prompt,
  em qualquer modelo, dá resultados comparáveis. Mudar o prompt = nova versão, e os itens antigos
  ficam marcados com a versão usada.

Saída: `descricoes` e `embeddings` no índice, com `modelo`, `versao_prompt`, `custo_estimado`.

### D. Catalogação em massa (`src/acervo/catalogacao/`)

O que transforma descrição automática em catálogo de verdade: fila de revisão desenhada para
velocidade.

- **ordem da fila**: (1) sem legenda, (2) confiança baixa (`< 0.6`, o mesmo limiar do `bcnlib`),
  (3) lote novo, (4) o resto. O que você revisa primeiro é o que a máquina não resolveu.
- **um item, uma decisão**: aceitar sugestão com uma tecla, trocar pilar com outra, descartar com
  outra. Sem formulário, sem campo obrigatório.
- **revisão por grupo**: aprovar o pilar de 40 clipes do mesmo lote de uma vez, quando a sugestão
  for unânime. É o único jeito de 3.000 itens não virarem 18 horas.
- **a marcação vira regra**: cada correção sua grava linha em `config/marcas/<marca>/regras.yaml`
  (ex.: "clipe de arquibancada em vídeo de jogo é BASTIDOR, não JOGO"), igual à parada de plano.
- **progresso persistente**: `dados/marcas/<marca>/marcacoes/revisao.json`, retomável, com
  contagem por lote e por pilar.

## O que muda na estrutura

Novas pastas, todas dentro do que já existe (nenhuma quebra de princípio):

```
src/acervo/ingestao/      A
src/acervo/segmentacao/   B
src/acervo/visao/         C
src/acervo/catalogacao/   D
config/padroes/ingestao.yaml
config/padroes/segmentacao.yaml     sensibilidade, duracao_minima_s, proxy
config/padroes/visao.yaml           modelo, frames por clipe, prompt versionado, teto de custo
dados/marcas/<marca>/indice/        catalogo.sqlite ganha: clipes, descricoes, embeddings
dados/marcas/<marca>/historico/ingestao.csv
dados/marcas/<marca>/marcacoes/revisao.json
```

Tudo isso é **do produto**, não da marca: quem troca de marca muda `acervo.yaml`, não a pasta.
A única coisa por marca é a taxonomia (que já é `pilares.yaml`) e os limiares de segmentação.

## Volume, para dimensionar antes de decidir

Números do acervo atual (medidos, do README):

| | hoje | se amostrar 1 frame por clipe |
|---|---|---|
| mídias | 3.199 (2.689 img + 491 vídeo) | — |
| posts | 1.248 | — |
| vídeos de post | 491 | estimativa de 3–8 clipes por vídeo → **1.500 a 3.900 clipes** |
| cortes brutos | 74 arquivos (65 min) | 1 clipe a cada 3 s ≈ **1.300 clipes** |
| imagens sem legenda | parte dos 69 posts `SEM_LEGENDA` | 1 frame cada |

Ou seja: o catálogo passa de ~3.200 para ~6.000–7.000 itens. **A estimativa de clipes ainda não é
medição** — o primeiro passo real é rodar segmentação em 20 vídeos e extrapolar com o número
verdadeiro.

## Ordem e dependências

1. **Ingestão** primeiro. Sem ela, cada arquivo novo entra por fora do índice e o acervo vira dois.
2. **Segmentação**. Depende do índice existir; não depende da visão.
3. **Visão**. Depende de segmentação (para clipes) e do índice. É a etapa que custa dinheiro.
4. **Catalogação em massa**. Depende da visão para ter sugestão, mas pode começar antes com fila
   manual (pilar vazio, sem sugestão) — assim a interface é testada antes do modelo.
5. **Busca por clipe em `src/achar/`**. Só depois de 2 e 3: é o que a parte 2 do sistema consome.

## Decisões que travam o plano

### 1. Onde roda a visão?
- **local** (Ollama + modelo de visão pequeno): custo zero por item, privacidade total, mais lento
  e qualidade menor em cena esportiva;
- **API** (modelo de visão barato, um frame por chamada): qualidade bem melhor, custo por item, e
  manda frame de menor de idade para fora — **isto é decisão sua, não técnica**.

Recomendo **local para triagem em massa + API só para o que a triagem não resolveu** (os `OUTROS`
e `SEM_LEGENDA`). O acervo tem criança e adolescente identificável: mandar 3.000 frames para fora
sem necessidade é risco que não precisa ser corrido.

### 2. Clipe referenciado ou arquivo recortado?
Recomendo **referenciar** (só in/out no índice + proxy 360p). Recortar duplica 15 GB e cria duas
fontes de verdade.

### 3. Quantos frames por clipe?
Recomendo **1 frame por clipe até 8 s, 3 frames acima disso**, e sempre o frame do meio como
thumbnail. Mede-se o custo num lote de 50 antes de rodar em tudo.

### 4. A IA pode mudar o pilar de um post que já tem pilar?
Recomendo **não**. Visão só decide onde não há decisão (o mesmo corte do `EVIDENCIA_MINIMA`).
Mexer em pilar já classificado invalidaria o plano de reciclagem inteiro.

### 5. Limiar de corte de cena
Precisa de dois valores, um por tipo: depoimento (corte seco, limiar alto — não quero fatiar
cabeça falando) e jogo/bastidor (limiar baixo — quero o lance). Recomendo começar em 0.30 e 0.15,
respectivamente, e ajustar olhando 20 vídeos de cada tipo.

## O que eu preciso de você antes de qualquer código

1. Onde a visão roda (local, API, ou os dois) — e se mandar frame de menor de idade para API está
   fora de questão.
2. Os arquivos novos: quantos, de onde vêm (outro download, HD, celular) e se podem ser
   **referenciados** em vez de copiados para o acervo.
3. Se existe GPU na máquina de trabalho — muda o que dá para rodar local sem virar madrugada.
4. Limiar de custo aceitável para a etapa de visão (um teto em reais, não "o que for preciso").
