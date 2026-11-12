# BCN Academy — reciclagem de mídia

Pipeline para transformar o acervo de Instagram da BCN Sports Academy
([@bcn_academy](https://www.instagram.com/bcn_academy/), baixado pelo 4K Stogram) em
material editável: catálogo, plano de reciclagem e projetos FilmCraft/PhotoCraft
gerados em lote.

O acervo em si (**~15 GB**, 3.199 mídias, 1.248 posts, 74 cortes) **não** está neste
repositório — só o código. Ele fica na máquina de trabalho, com esta estrutura:

```
arquivo/BCN/bcn_academy/
├── _posts/<ano>/<AAAA-MM-DD>_<PILAR>_<assunto>/    posts, um por pasta
├── _Cortes/<tema>/                                 material bruto para edição
├── _audio/musicas/                                 trilhas (Pixabay)
├── _endings/                                       vídeo de encerramento
├── transcricoes/                                   .txt/.srt espelhando _posts
└── _reciclagem/                                    ← este repositório
```

## O que tem aqui

| arquivo | papel |
|---|---|
| `catalogo.py` | indexa tudo em CSV + SQLite (posts, cortes, falas para busca full-text) |
| `organizar.py` | agrupa mídia solta em uma pasta por post |
| `renomear.py` | nome legível nas pastas: data + pilar + assunto da legenda |
| `plano.py` | ranking de reciclagem + calendário + moldes de legenda |
| `buscar.py` | busca no que é falado nos vídeos (FTS5) |
| `legendar.py` | reescreve os `.srt` com tempo por palavra (cartela de 4 palavras já no tempo real) |
| `gerar_projetos.py` | gera `.fcproj` / `.pcraft` em lote |
| `painel.py` | painel HTML offline: preview, marcações, fila de geração |
| `servidor.py` | servidor local que dá aos botões do painel poder de escrita |
| `renomear.py` | (idem acima) |
| `bcnlib.py` | núcleo: classificação por legenda, score, estados, cortes |
| `modelo_filmcraft.py` | construtor de projeto FilmCraft a partir do modelo base |
| `titulos.py` | título/subtítulo automáticos para o Lower Third |
| `MODELO_PROJETOS.md` | o modelo de projeto por tipo de post |
| `README.md` | manual completo do pipeline |

## Como rodar

```bash
python3 _reciclagem/catalogo.py                 # 1. índice
python3 _reciclagem/organizar.py                # 2. dry-run; --aplicar executa
python3 _reciclagem/renomear.py                 # 3. nomes legíveis
python3 _reciclagem/plano.py --n 40             # 4. plano + rascunhos
python3 _reciclagem/painel.py                   # 5. painel.html
python3 _reciclagem/servidor.py                 #    + botões com escrita
python3 _reciclagem/gerar_projetos.py --aplicar # 6. projetos
```

Nada é apagado em nenhuma etapa: `organizar.py --desfazer` e `renomear.py --desfazer`
revertem pelo log.

## Dependências

Python 3.11 (só stdlib) e os CLIs do ArtCraft instalados: `filmcraft-cli`,
`photocraft-cli`. O `gerar_projetos.py` aciona os apps para criar os projetos, então o
schema é sempre o da versão instalada.

## Licença

Uso interno da BCN Sports Academy. Sem licença aberta por enquanto.
