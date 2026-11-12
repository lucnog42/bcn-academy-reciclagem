# Video Automation NG3

Pipeline de vídeo para o Instagram de qualquer marca: organiza o acervo publicado, transcreve,
monta projetos do FilmCraft, sugere motion graphics e b-roll a partir da timeline e gera vídeo
com IA, tudo num painel nativo (Rune) com plugins Luau.

O código não sabe qual é a marca. Tudo o que é de um cliente fica em `config/marcas/<marca>/`,
e o estado dele em `dados/marcas/<marca>/`.

## Estrutura

```
config/
  marca-ativa              a marca em uso (uma linha: o slug)
  padroes/*.toml           o que vale para toda marca (legenda, funções, formatos, FilmCraft)
  marcas/<marca>/*.toml    marca, acervo, identidade, estilo, pilares, vocabulário, regras
  marcas/exemplo/          molde para um cliente novo
  local.toml               chaves e caminhos desta máquina (fora do git, chmod 600)
assets/marcas/<marca>/     arquivos versionados da marca (modelo-base.fcproj...)
dados/marcas/<marca>/      estado (fora do git): marcações, filas, índices, motion, cache
src/
  nucleo/      config, caminhos, cliente da IA
  acervo/      coleção, catálogo, busca, organizar/renomear, títulos, reciclagem, mídia
  transcricao/ legendar, legendas, voz
  plano/       momentos (sugestões de motion/vídeo) e prompts da IA
  criar/       vídeo com IA (OpenRouter)
  projetos/    gerar projetos, modelo, .fcproj, linha do tempo
  verificacao/ conferir legendas
  painel/      api.py (a ponte JSON com o app)
plugins/       plugins Luau (+ scripts python deles)
app/           painel nativo (Rust/Rune): ng3-painel
scripts/       migrar_dados.py
testes/        python3 -m unittest discover -s testes
docs/          pesquisas e decisões
```

## Cliente novo

1. `cp -r config/marcas/exemplo config/marcas/<slug>` e troque os textos (marca, pilares,
   vocabulário, cores, estilo, a raiz do acervo).
2. Se o acervo estiver em outro caminho nesta máquina, sobrescreva em `config/local.toml`:
   ```toml
   [marcas.<slug>.acervo.publicado]
   raiz = "/caminho/do/acervo"
   ```
3. No painel, clique no nome do cliente (canto esquerdo do topo) e escolha a marca (ou escreva o slug em
   `config/marca-ativa`, ou rode com `NG3_MARCA=<slug>`).

## O que o painel faz

- **Cliente** (canto esquerdo do topo): troca de cliente ou cria um novo a partir do molde. Cada
  cliente tem o seu acervo, fontes, roteiros, motions e **chaves de API** (sem chave própria, usa
  a geral; em "chaves e config" você escolhe se a chave salva vale só para o cliente ou para todos).
- **posts / cortes**: o acervo publicado; **repost**: o ranking de reaproveitamento dos posts.
- **importar**: aponta pastas de qualquer disco (nada é copiado) com um tipo: `falas` (transcritas,
  entram nos roteiros e no b-roll), `broll`, `fotos` ou `referencias` (estilo e montagem de outros,
  nunca usadas como material). Índice e transcrições ficam em `dados/marcas/<marca>/`.
- **roteiros**: a IA propõe ideias e escreve roteiros com as **falas já gravadas** (texto e tempo
  exatos) e, onde faltar, **falas novas** para gravar. Cada parte tem uma função (provar, dar o
  clima, contraste, só a pessoa) e o que mostrar, já com candidatos do acervo. Você aprova ou exclui.
  **Aprovar** cria o projeto do FilmCraft com o primeiro corte (falas na ordem, um cartão no lugar
  de cada fala nova, b-roll do acervo por função; nada gerado) e um momento por parte, onde se
  troca o b-roll, se põe motion ou se gera o que faltar.
- **Motion com HyperFrames**: em cada momento, "gerar motion" faz a IA escrever uma composição HTML
  e o [HyperFrames](https://github.com/heygen-com/hyperframes) renderiza um MOV com transparência
  (fica em `dados/.../motion/hyperframes/<id>/` para ajustar à mão). "Usar um motion que já existe"
  reaproveita os do cliente. Precisa de Node 22+ e FFmpeg; na primeira vez o `npx` baixa o HyperFrames
  e um Chrome headless (ou aponte `HYPERFRAMES_BROWSER_PATH` para o Chrome/Chromium instalado).

## Rodar

```
cd app && cargo build --release
./app/target/release/ng3-painel                 # acha a raiz pela pasta atual ou pelo executável
./app/target/release/ng3-painel --acervo <pasta>  # força outro acervo (NG3_ACERVO)
```

Variáveis: `NG3_RAIZ`, `NG3_MARCA`, `NG3_ACERVO`, `NG3_PYTHON`, `NG3_VIDEO_API_KEY`, `HYPERFRAMES_BROWSER_PATH`.

No SDD (NTFS/exFAT) compile com a pasta de build fora dele e copie o executável para `app/`:

```
cd app && CARGO_TARGET_DIR=~/.cache/ng3-target cargo build --release
cp ~/.cache/ng3-target/release/ng3-painel ./ng3-painel
```

## Vindo do layout antigo (`<acervo>/_reciclagem/`)

```
python3 scripts/migrar_dados.py            # mostra o que vai copiar
python3 scripts/migrar_dados.py --aplicar  # copia para dados/marcas/<marca>/ (não apaga nada)
```

O `.venv-asr` da transcrição não é copiado: recrie em `.venv-asr/` na raiz do projeto.

## Regras que não mudam

- Chaves só por variável de ambiente ou `config/local.toml`; a API nunca as devolve.
- Nada no acervo é apagado ou sobrescrito; projetos têm cópia em `historico/projetos_antigos/`
  antes de qualquer mudança.
- Pessoas reais da marca nunca são geradas nem reestilizadas por IA (ver `pessoas_reais` em
  `marca.toml`).
