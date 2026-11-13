# CLAUDE.md — Video Automation NG3

Guia para quem (humano ou Claude) mexe neste repositório. Leia antes de qualquer mudança.

## Antes de mudar qualquer coisa

1. `git status` limpo. Se houver algo pendente, **commit primeiro** (regra do Lucas).
2. Trabalhe direto na instalação do SDD: `/run/media/doykoy/SDD/NG3-Video-Automation`.
3. Uma frente por branch: `fase/tags-import`, `fase/separacao-voz`, `fase/roteiros-abertos`,
   `fase/filmcraft-sync` (ver `docs/08-plano-fase-import-voz-roteiros.md`).
4. Rode os testes antes e depois: `python3 -m unittest discover -s testes`.

## O que é o projeto

Pipeline de vídeo para Instagram, **agnóstico de marca**. Painel nativo em Rust/Rune (`app/`)
conversa por JSON com o motor Python (`src/painel/api.py serve`). Plugins em Luau (`plugins/`).
Projetos de edição são `.fcproj` do FilmCraft, manipulados como JSON e validados com
`filmcraft-cli --project <p> inspect`.

```
config/padroes/*.toml   padrões do produto; cada arquivo vira cfg["<nome>"] (geral.toml vai na raiz)
config/marcas/<marca>/  tudo que é do cliente (nada de marca no código!)
config/local.toml       chaves e caminhos desta máquina (fora do git)
dados/marcas/<marca>/   estado: índices sqlite, transcrições, roteiros, filas, cache (fora do git)
src/nucleo/             config, caminhos, cliente da IA
src/acervo/             fontes (import), coleção, catálogo, mídia
src/transcricao/        legendar (faster-whisper), voz (VAD/refino), legendas
src/plano/              roteiros, falas (banco de frases), momentos, prompts
src/projetos/           gerar, modelo, fcproj (edição in-place), linha_tempo
src/painel/api.py       a ponte: toda ação do app passa aqui
app/src/ui/*.rs         uma aba por arquivo (importar.rs, roteiros.rs, preview.rs…)
```

## Regras que não mudam

- **Nada no acervo nem nas pastas importadas é apagado, sobrescrito ou criado.** Fontes são
  apontadas, não copiadas. Cortes e tags são **anotações** em `dados/`, nunca arquivos novos.
- Antes de gravar um `.fcproj`: cópia em `dados/marcas/<marca>/historico/projetos_antigos/` e
  validação com `filmcraft-cli inspect`; se recusar, a cópia volta (use `fcproj.salvar`).
- Chaves só por variável de ambiente ou `config/local.toml`; a API nunca as devolve.
- Pessoas reais da marca nunca são geradas nem reestilizadas por IA (`pessoas_reais`).
- Código e identificadores em **português**, como o resto do projeto (`fonte`, `corte`, `fala`).
- Nada de nome de marca no código: `testes/test_agnosticidade.py` falha se aparecer.
- Escrita de JSON sempre atômica (`.tmp` + `os.replace`), como em `fontes._gravar`.

## Máquina (limita as escolhas)

Ryzen 7 6800HS · **RTX 3050 4 GB VRAM** · **14 GB RAM (gargalo)** · acervo em HD USB SMR NTFS.
Consequências: modelos de IA em série (nunca dois na GPU ao mesmo tempo), lotes com
paralelismo 2–4, áudio extraído para `/tmp` em wav 16 kHz mono, build do Rust fora do SDD:

```
cd app && CARGO_TARGET_DIR=~/.cache/ng3-target cargo build --release
cp ~/.cache/ng3-target/release/ng3-painel ./ng3-painel
```

## Ambientes Python

| venv | para quê | requisitos |
|---|---|---|
| sistema `python3` | painel, api, roteiros, projetos | só stdlib + numpy |
| `.venv-asr/` | transcrição (faster-whisper, CUDA 12) | `requirements-asr.txt` |
| `.venv-sep/` | separação de voz/música | `requirements-separacao.txt` |
| `.venv-visao/` | V-JEPA 2 + SigLIP (tags) | `requirements-visao.txt` |

Venvs separados de propósito: torch/onnxruntime-gpu da separação brigam com as versões fixas
do ASR. O motor chama cada venv por subprocess, como `legendar.garantir_venv()` já faz.

## Como adicionar uma ação nova no painel

1. Função pura no módulo Python certo (testável sem app).
2. Ação em `src/painel/api.py` (validar entrada; caminhos só dentro de `_raizes_permitidas()`).
3. Chamada na aba `app/src/ui/<aba>.rs` via `ponte.rs`; estado em `app.rs`/`extra.rs`.
4. Teste em `testes/test_<area>.py` com dados falsos (sem GPU, sem rede, sem acervo real).

## Comandos úteis

```
python3 -m unittest discover -s testes            # testes (rápidos, sem GPU)
python3 src/acervo/fontes.py                       # lista fontes
python3 src/plano/roteiros.py ideias "tema"        # roteiros pela CLI
python3 src/projetos/fcproj.py legendas <p> <v>    # refaz só as legendas do projeto
cd app && cargo check                              # confere o Rust sem build completo
```
