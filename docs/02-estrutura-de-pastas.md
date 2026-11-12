# 02 — Estrutura de pastas

## Árvore

```
plano-visual/
├── config/
│   ├── marca-ativa                 ← uma linha: o slug da marca em uso (ex.: bcn)
│   ├── padroes/                    do produto: vale para toda marca
│   │   ├── funcoes.yaml            provar | clima | contraste | so-a-pessoa | nenhuma
│   │   ├── formatos.yaml           b-roll tela cheia, cartão, grade, fundo (+ fase)
│   │   └── projeto-filmcraft.yaml  regras do modelo: legenda ≤4 palavras, corpo 40 pt…
│   ├── marcas/
│   │   └── bcn/                    tudo que é da BCN, e só isso
│   │       ├── marca.yaml          nome, @, site, idioma, fuso
│   │       ├── acervo.yaml         caminho do acervo + layout esperado
│   │       ├── pilares.yaml        taxonomia de pilares
│   │       ├── vocabulario.yaml    termos e pesos da classificação (hoje em bcnlib.py)
│   │       ├── identidade-visual.yaml  cores, logo, tipografia
│   │       ├── estilo.yaml         linha de estilo: época, cor, luz, textura
│   │       └── regras.yaml         regras aprendidas com as suas correções
│   └── schema/                     contratos JSON dos arquivos acima
├── src/
│   ├── nucleo/                     config, perfil de marca, caminhos, log, erros
│   ├── acervo/                     catálogo, organização, renomeação, índice de busca
│   ├── transcricao/                transcrição e tempo por palavra
│   ├── plano/                      formato da história, função por linha, listas
│   ├── achar/                      busca no acervo e busca externa com fonte
│   ├── criar/                      linha de estilo, lote, versões
│   ├── projetos/                   gera .fcproj/.pcraft e o modelo base
│   ├── composicao/                 formatos de imagem sobre a fala
│   ├── verificacao/                conferência do corte montado
│   ├── aprovacoes/                 as três paradas
│   └── painel/                     interface e servidor local
├── dados/
│   └── marcas/
│       └── bcn/                    estado de trabalho (fora do git)
│           ├── indice/             catalogo.csv, posts.csv, catalogo.sqlite
│           ├── fila/               projetos.csv
│           ├── marcacoes/          estados.json (NI, RP, aprovado)
│           └── historico/          movimentos.csv, renomeacoes.csv
├── assets/                         arquivos de apoio (não são código nem acervo)
│   ├── padroes/
│   │   └── modelo-base.fcproj      projeto base do FilmCraft
│   └── marcas/
│       └── bcn/                    logo, encerramento, faixas de música
├── entradas/
│   ├── roteiros/                   roteiro.md / fala.txt por vídeo
│   └── filmcraft/                  .fcproj / .pcraft que chegam
├── saidas/
│   └── <AAAA-MM>-<marca>-<slug>/   um job, com subpastas numeradas 00…90
├── testes/
├── scripts/
└── docs/
```

## O que pode e o que nunca pode entrar em cada pasta

### `config/padroes/` — o produto
Regras que valem para qualquer marca: quais funções existem, quais formatos de composição, o que
o modelo FilmCraft exige (4 palavras por cartela, 40 pt, abertura de 4 s com fala).
**Nunca:** nome de marca, caminho de máquina, cor de marca.

### `config/marcas/<marca>/` — a marca
É o único lugar onde a palavra `bcn` é legítima. Um arquivo por assunto, sempre YAML, sempre
comentado com a unidade de cada campo (px, s, dB).
**Nunca:** regra que valha para todas as marcas (isso é `config/padroes/`), nem código.

### `config/schema/` — o contrato
JSON Schema de `estilo.yaml`, `acervo.yaml`, `plano.yaml`. É o que permite o painel recusar um
arquivo malformado antes de rodar o pipeline inteiro.

### `src/nucleo/` — a base
Carrega `config/marca-ativa`, resolve caminhos do acervo e de `dados/`, expõe tipos
(`Funcao`, `Momento`, `ItemAchar`, `ItemCriar`), log e erros.
**Nunca:** regra de negócio de uma parte específica.

### `src/acervo/` — ler o acervo
`catalogo`, `organizar`, `renomear`, `buscar` (FTS5). Conhece o **layout** do acervo
(`_posts/<ano>/<post>/{imagens,videos,metadados}`, `_Cortes`, `transcricoes/`) porque o layout é
declarado em `acervo.yaml`, não fixado no código.

### `src/transcricao/` — fala
Transcrever e reescrever `.srt` com tempo por palavra. Saída em `dados/marcas/<marca>/` ou ao
lado do vídeo, conforme `acervo.yaml`.

### `src/plano/` — parte 1
Define o formato da história (`depoimento`, `linha-do-tempo`, `problema-solucao`, `convite`),
percorre a fala e emite função por trecho + listas `achar` e `criar`.
**Nunca:** escolher imagem. Só dizer o que é preciso e para quê.

### `src/achar/` — parte 2
Recebe a lista `achar` e devolve candidatos: primeiro do acervo, com legenda, pilar e fala;
depois externo, sempre com `fonte` (URL, autor, licença) anotada.
**Nunca:** gerar imagem (isso é `src/criar/`).

### `src/criar/` — parte 3
Monta prompt com a linha de estilo no fim, dispara lote de 3–4 versões, registra o que foi gerado
e com qual estilo. Recusa item cuja função não permite gerar ou que contenha pessoa real.

### `src/projetos/` — projetos dos apps
Gera `.fcproj` / `.pcraft` via CLI, com o modelo base, valida com `inspect`, mantém a fila.
**Nunca:** decidir conteúdo — só materializar o que veio do plano.

### `src/composicao/` — parte 4
Traduz "este momento recebe cartão ao lado do falante" em parâmetros de timeline/recorte.

### `src/verificacao/` — parte 5
Transcreve o corte pronto, compara com a fala original, procura palavra cortada, pausa longa,
quadro ruim na emenda. Emite `relatorio.md` + `resultado.json` (passou/falhou + onde).

### `src/aprovacoes/` — parte 6
As três paradas: plano, corte, abertura. Guarda quem aprovou, quando, e qual correção virou regra
em `config/marcas/<marca>/regras.yaml`.

### `src/painel/` — interface
Lê `dados/marcas/<marca>/` e escreve só por API do próprio sistema. Não conhece caminho de acervo.

### `assets/` — apoio
Modelo base do FilmCraft em `assets/padroes/`; logo, encerramento e biblioteca de faixas em
`assets/marcas/<marca>/`. São arquivos que o sistema **usa**, não que ele produz.
**Nunca:** mídia do acervo (essa fica no acervo externo) nem artefato de job (essa fica em `saidas/`).

### `dados/marcas/<marca>/` — estado
Índice, fila, marcações, histórico de movimentação. Fora do git, com backup. Recriável a partir
do acervo, **exceto** `marcacoes/estados.json` (curadoria humana, não recriável).

### `saidas/<job>/` — um vídeo
```
00-entrada/      cópia do roteiro + projeto usado
10-plano/        plano.yaml + aprovacao.yaml
20-achar/        candidatos.json + escolhas.yaml
30-criar/        prompts.jsonl + versoes/ + escolhidas.yaml
40-composicao/   corte montado (.fcproj)
50-verificacao/  resultado.json + relatorio.md
90-logs/         o que rodou, com data
```
Nada em `saidas/` é fonte de verdade: o que vale para o próximo vídeo sobe para `config/`.

## Por que os nomes são estes

- **`achar` e `criar`** em vez de `search`/`generate`: são as duas listas que o plano produz, e o
  nome da pasta é o nome da lista. Quem procura a etapa procura a mesma palavra em todo lugar.
- **`dados` e `saidas`** separados: `dados` é estado que se acumula (e se perde se apagado),
  `saidas` é artefato por job (recriável). Confundir os dois foi o que colocou `estados.json`
  dentro da pasta do código.
- **`config/padroes`** existe para o `src/` nunca precisar de um `if marca == ...`.
- **`docs/`** numerado: a ordem de leitura é a ordem dos arquivos.

## Teste de agnosticidade (a escrever na fase 1)

`testes/test_agnosticidade.py`:

1. nenhuma chave conhecida de marca aparece em `src/**`, `config/padroes/**`, `docs/**`
   (palavra banida lida de `config/marca-ativa` + todas as pastas de `config/marcas/`);
2. `src/` não lê caminho absoluto de acervo — só via `nucleo.caminhos`;
3. trocar `config/marca-ativa` para uma marca fictícia (`testes/fixtures/marca-teste/`) não
   quebra import nem cálculo de caminho.
