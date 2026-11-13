# 08 — Plano da fase: tags no import, cortes, voz sem música, roteiros abertos, FilmCraft

Decisões tomadas com o Lucas (2026-11-13):

- **Tags**: lista fixa por marca (`config/marcas/<marca>/tags.toml`) **+ tags livres**; a IA
  sugere, a pessoa confirma.
- **Cortes**: mistura de três origens — frases da fala, mudança de cena e marcação manual — e
  são **só anotações** (entrada/saída + tags), nunca arquivos novos.
- **Separação voz/música**: automática quando houver música de fundo; dá para forçar por fonte.
- **Roteiros**: menos engessados, com espaço real para input humano.
- **Projetos**: edição integrada ao FilmCraft (ida e volta), não só geração.

Ordem de trabalho (cada uma num branch, com commit antes):

| # | branch | depende de | entrega |
|---|---|---|---|
| 1 | `fase/separacao-voz` | — | transcrição melhor já no próximo import |
| 2 | `fase/tags-import` | — | modelo de dados de mídia/corte/tag + aba importar nova |
| 3 | `fase/cortes` | 1, 2 | cortes automáticos (fala + cena) e manuais no preview |
| 4 | `fase/roteiros-abertos` | 2, 3 | roteiro editável por humano, busca usando tags e cortes |
| 5 | `fase/filmcraft-sync` | 4 | ler o `.fcproj` de volta e manter roteiro ↔ projeto em sincronia |

---

## 1. Separação de voz antes de transcrever

**Onde entra:** `src/transcricao/legendar.py::transcrever`, entre `audio_do_video()` e o
`faster-whisper`. Novo módulo `src/transcricao/separar.py`, rodando no `.venv-sep/`.

**Fluxo**

1. `audio_do_video()` → wav 16 kHz mono (já existe).
2. `tem_musica(wav)` — detecção barata, sem GPU: energia fora da faixa de voz + proporção de
   quadros "tonais" fora das regiões de voz do VAD (`voz.analisar` já dá as regiões). Se a
   fração musical passar de `separacao.limiar_musica`, separa. Cache do resultado por hash.
3. `separar(wav)` → `<cache>/sep/<hash>_voz.wav` com [`audio-separator`](https://github.com/nomadkaraoke/python-audio-separator)
   (modelos UVR/MDX/RoFormer). Modelo padrão: um RoFormer de vocal; alternativa leve
   `UVR-MDX-NET-Voc_FT` se faltar VRAM. Segmentos curtos para caber nos 4 GB; CPU como reserva.
4. O whisper e o `refinar_pela_voz` rodam na **voz isolada**; os tempos continuam valendo para
   o vídeo original (mesma duração, mesma taxa).
5. Grava no `words.json` de que áudio veio (`"fonte_audio": "separada" | "original"`) e o
   modelo, para poder re-transcrever só o que mudou.

**Config:** `config/padroes/separacao.toml` (já criado). Por fonte, em `fontes.json`:
`"separar": "auto" | "sempre" | "nunca"`.

**Ganho extra:** o mesmo stem de voz melhora o silencecut e o VAD; o stem de música pode virar
"trilha original" na montagem (opcional, depois).

**Testes:** `tem_musica` com sinais sintéticos (seno + ruído vs. só ruído modulado);
`separar` com mock do subprocess. Nada de modelo real nos testes.

## 2. Interface de tags no import

### Modelo de dados (sqlite em `dados/marcas/<marca>/midia.sqlite`)

```
midia(id, fonte_id, caminho_rel, tipo, duracao, largura, altura, hash_rapido, status_import)
tag(id, slug, nome, categoria, origem)          -- origem: marca | livre
midia_tag(midia_id, tag_id, por)                -- por: humano | ia_sugerida | ia_aceita
corte(id, midia_id, ini, fim, origem, titulo, nota, nota_ia, criado_em)
                                               -- origem: fala | cena | manual
corte_tag(corte_id, tag_id, por)
```

- `hash_rapido` (tamanho + primeiros/últimos MB) para reconhecer arquivo movido sem reprocessar.
- `status_import`: `novo → indexado → (separado) → transcrito → cortado → revisado`.
- O índice FTS de `achar/indice.py` ganha colunas de tags e cortes (busca por "tag:camp-nou").

### Fluxo na aba importar

1. Apontar pasta (como hoje) → os vídeos novos caem numa **fila de revisão**, não direto no índice.
2. Fila em grade (reaproveita `ui/grade.rs`): miniatura, duração, status; seleção múltipla.
3. Painel lateral de tags: categorias da marca como pastilhas + campo de tag livre com
   autocompletar; aplicar a N selecionados de uma vez. Sugestões da IA aparecem tracejadas;
   um clique aceita, outro descarta.
4. "Marcar como revisado" libera a mídia para roteiros e b-roll.

**Sugestão de tags (IA):** texto da transcrição + 3–4 quadros (os mesmos da tira do preview,
em 360 px) → Claude com a lista da marca no prompt; resposta JSON só com slugs da lista ou
tags livres marcadas como novas. Em lote, de forma assíncrona (fila de tarefas que já existe).

## 3. Cortes como anotação

Três geradores, todos escrevendo na tabela `corte` — nunca no disco do acervo:

| origem | como | para |
|---|---|---|
| `fala` | `plano/falas.frases_de()` agrupa frases em ideias (pausa > X s ou mudança de assunto pela IA) | falas |
| `cena` | PySceneDetect (`ContentDetector`) no proxy 360p, no `.venv-sep` ou no sistema | broll |
| `manual` | entrada/saída no preview (`I`/`O` na tira de quadros), com tags e nota | qualquer |

- Cortes automáticos nascem como **propostos**; no preview a pessoa ajusta borda, junta, divide,
  apaga. Um corte manual nunca é sobrescrito por reprocessamento.
- Tags da mídia são herdadas pelo corte; tags do corte são mais específicas.
- `projetos/gerar` e `roteiros` passam a aceitar `corte_id` onde hoje aceitam vídeo + tempo.

## 4. Roteiros menos engessados

Hoje: a IA escreve tudo, a pessoa só move/remove/troca candidato, e depois de aprovado trava.

Novo modelo — **o roteiro é um documento de trabalho conjunto**:

- **Começar de qualquer ponto:** da ideia da IA, de um texto livre do Lucas (briefing, tópicos),
  ou de cortes escolhidos à mão na grade ("montar roteiro com estes").
- **Partes livres:** adicionar parte em qualquer lugar; tipos `fala` (corte existente), `nova`
  (texto a gravar), `locucao`, `texto_na_tela`, `respiro` (só imagem/música). Duração editável.
- **Nota de direção por parte** (humano) e **por roteiro**; a IA lê as notas ao reescrever.
- **"Reescrever só esta parte"** / **"sugerir alternativas"**: a IA propõe 3 opções para uma
  parte, mantendo o resto travado. Partes podem ser marcadas como **fixas** (a IA não mexe).
- **Trocar fala por outra parecida:** busca no banco de falas + cortes por tags e semelhança.
- **Aparar fala:** ajustar entrada/saída da fala em palavras (a transcrição dá os tempos).
- **Versões:** cada salvamento grava `roteiros/<id>/v<n>.json`; dá para comparar e voltar.
- **Aprovado não trava:** aprovar gera o projeto; mudanças depois vão para o projeto pela
  sincronia (seção 5), com aviso quando o projeto foi editado à mão no FilmCraft.

Mudanças em `plano/roteiros.py`: `editar()` ganha `inserir`, `tipo`, `duracao`, `aparar`,
`nota`, `fixar`, `reescrever_parte`; formato de arquivo com `versao`. Prompts em
`plano/prompts.py` passam a receber notas e partes fixas.

## 5. Edição integrada com o FilmCraft

Hoje a ida é boa (`gerar`, `fcproj.ganho/legendas`), mas não há volta.

1. **Mapa roteiro ↔ timeline:** ao aprovar, cada clipe gerado recebe no `.fcproj` um marcador
   com `parte_id` (campo de nome/nota do clipe que o FilmCraft preserva — confirmar com
   `filmcraft-cli inspect`). Guardar também em `roteiros/<id>/mapa.json`.
2. **Ler de volta:** `linha_tempo.ler()` já lê o projeto; novo `projetos/sincronia.py` compara
   o projeto atual com o mapa e lista: partes cortadas, reordenadas, aparadas, clipes novos.
3. **Duas direções, sempre com confirmação:**
   - FilmCraft → roteiro: "o projeto mudou; atualizar o roteiro?" (aplica ordem e tempos).
   - roteiro → FilmCraft: aplicar só a parte mudada (trocar clipe, aparar), via `fcproj.salvar`
     com cópia e `inspect`. Nunca regerar o projeto inteiro se ele já foi editado à mão.
4. **Abrir no FilmCraft** a partir do painel, no tempo da parte (se o CLI aceitar `--seek`;
   senão só abrir o projeto).
5. Detectar edição externa por `mtime` + hash do `.fcproj`; mostrar no card do projeto.

**A investigar primeiro:** que campos do clipe o FilmCraft preserva ao salvar (para o marcador
`parte_id`) e o que o `filmcraft-cli` oferece além de `probe` e `inspect`.

---

## Perguntas em aberto

- Quantas tags livres viram categoria da marca? (revisar a cada ~50 mídias importadas)
- Cortes por fala: agrupar por pausa ou pedir à IA os limites de ideia? (começar por pausa)
- O stem de música deve ser guardado ou descartado depois da transcrição? (padrão: descartar)
