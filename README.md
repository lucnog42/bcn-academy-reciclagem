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
3. No painel, em "chaves e config" → "Marca (cliente)", escolha a marca (ou escreva o slug em
   `config/marca-ativa`, ou rode com `NG3_MARCA=<slug>`).

## Rodar

```
cd app && cargo build --release
./app/target/release/ng3-painel                 # acha a raiz pela pasta atual ou pelo executável
./app/target/release/ng3-painel --acervo <pasta>  # força outro acervo (NG3_ACERVO)
```

Variáveis: `NG3_RAIZ`, `NG3_MARCA`, `NG3_ACERVO`, `NG3_PYTHON`, `NG3_VIDEO_API_KEY`.

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
