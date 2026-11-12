#!/usr/bin/env python3
"""A IA das sugestões (a escolhida no painel: Claude, DeepSeek, OpenRouter...) escrevendo ou
melhorando o texto que guia cada geração:

  * motion  -> o briefing do filme Motion (o que o Claude anima: layout, entrada e saída,
               tipografia, cores, ritmo), que vai junto do pedido na fila
  * video   -> o prompt do vídeo gerado no OpenRouter (cena, ação, câmera, luz, estilo)

A IA vê o momento (fala, tempos, tipo), o contexto do item, as imagens do momento e o quadro do
vídeo naquele instante. Dois modos:

  * melhorar   -> uma versão principal (gravada no momento) e duas alternativas
  * abordagens -> três caminhos DIFERENTES, com nome, para você escolher antes de gerar (nada é gravado)

Se o momento tem um modelo de prompt escolhido (plano/modelos.py), a IA escreve no estilo dele.

    python3 src/plano/prompts.py <pasta> <id> motion|video ["texto atual"] [--modelo google/veo-3.1] [--abordagens]
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import argparse
import json
import os
import sys

from plano import momentos  # noqa: E402
from nucleo import config  # noqa: E402

_SISTEMA = {
    "motion": """Você escreve o briefing de um motion graphic curto para a marca abaixo.
{marca}
O motion é feito em código (Claude Motion) e entra POR CIMA do vídeo, com fundo transparente: o
falante continua visível. O briefing diz ao animador o que fazer, em português, de forma concreta:
- composição e lugar na tela (o terço de baixo é da legenda; use o alto ou o meio, margens de 6%);
- o texto exato que aparece (não invente nome, número, clube nem data além do que foi dado);
- entrada, permanência e saída, com tempos que caibam na duração do momento;
- tipografia (peso, tamanho relativo, caixa), cores (tiradas das imagens de referência quando houver;
  cores da marca: {cores}) e elementos gráficos simples;
- nada piscando mais de 3 vezes por segundo, nada que pareça propaganda de outra marca.
No máximo 120 palavras por briefing.""",
    "video": """Você escreve prompts para modelos de geração de vídeo (Veo, Seedance, Wan, Hailuo...).
{marca}
O vídeo gerado é um b-roll que cobre a imagem por alguns segundos enquanto a fala continua.
Um bom prompt, em inglês (os modelos entendem melhor), diz em frases diretas:
- o sujeito e a ação, o lugar, a hora e a luz;
- o movimento de câmera (dolly, pan lento, drone, handheld) e a lente/enquadramento vertical 9:16;
- o estilo (realista, cinematográfico, cores naturais) e o clima; termine com a linha de estilo
  da marca: {estilo}
- o que evitar: texto, letreiros, logos, marcas d'água, legendas, rostos reconhecíveis de pessoas
  reais ({pessoas}).
Se houver imagem marcada como primeiro quadro, descreva o movimento que parte DELA, sem trocar a cena.
Não prometa o que não foi dito (nada de lugar famoso específico se o usuário não pediu).
No máximo 90 palavras por prompt.""",
}


def sistema(alvo: str) -> str:
    cfg = config.carregar()
    m = cfg["marca"]
    return (_SISTEMA[alvo].replace("{marca}", config.descricao_marca())
            .replace("{cores}", m.get("cores_texto") or ", ".join(cfg.get("cores", {}).values()) or "as da marca")
            .replace("{estilo}", cfg["estilo"].get("linha") or "natural, realistic")
            .replace("{pessoas}", m.get("pessoas_reais") or "só em material verdadeiro"))


SISTEMA = _SISTEMA   # nomes de alvo válidos

FORMATO = """Responda só com JSON:
{"principal": "...", "alternativas": ["...", "..."], "nota": "uma frase sobre o que mudou ou por quê"}"""

FORMATO_ABORDAGENS = """Proponha TRÊS abordagens realmente diferentes (não variações de palavras: muda a ideia visual,
o tipo de animação ou de cena, o ritmo). Cada uma com um nome curto, a ideia em uma frase e o texto completo.
Responda só com JSON:
{"opcoes": [{"nome": "...", "ideia": "...", "texto": "..."}, {...}, {...}]}"""


def _momento(pasta: str, sid: str) -> dict:
    s = next((x for x in momentos.ler_sugestoes(pasta).get("itens", []) if x["id"] == sid), None)
    if s is None:
        raise ValueError("momento não encontrado")
    return s


def pedir(pasta: str, sid: str, alvo: str, atual: str = "", modelo_video: str = "",
          modo: str = "melhorar") -> dict:
    from nucleo import ia
    from plano import modelos
    if alvo not in SISTEMA:
        raise ValueError("alvo é motion ou video")
    s = _momento(pasta, sid)
    ctx = momentos.ler_contexto(pasta).get("texto", "").strip()
    fala = []
    for a, b, t in momentos._palavras(s["video"]):
        if b >= s["ini"] - 3 and a <= s["fim"] + 3:
            fala.append(t)
    texto = [f"Momento: tipo {s.get('tipo')}, de {s['ini']:.1f}s a {s['fim']:.1f}s "
             f"(duração {s['fim'] - s['ini']:.1f}s), posição sugerida: {s.get('posicao', 'alto')}.",
             f"Texto do momento: {s.get('texto', '')}" + (f" / apoio: {s['apoio']}" if s.get("apoio") else ""),
             f"Fala ao redor (±3 s): {' '.join(fala) or '(sem transcrição)'}"]
    if s.get("motivo"):
        texto.append(f"Por que este momento: {s['motivo']}")
    no_proj = momentos._no_projeto(pasta, s)
    if no_proj.get("t_projeto"):
        a, b = no_proj["t_projeto"]
        texto.append(f"No projeto do FilmCraft (o vídeo como vai ao ar): {a:.1f}–{b:.1f} s da timeline. "
                     f"Já na tela nesse trecho: {no_proj['na_tela']}. Legenda na tela: \"{no_proj['legenda_na_tela']}\". "
                     f"Respeite o que já ocupa a tela (posição, cores, não cobrir o título).")
    elif no_proj.get("na_tela"):
        texto.append(f"Atenção: {no_proj['na_tela']}.")
    if ctx:
        texto.append(f"Contexto do usuário (vale como fato): {ctx}")
    if alvo == "video" and modelo_video:
        texto.append(f"Modelo de vídeo escolhido: {modelo_video}.")
    guia = modelos.guia(s.get("modelo_motion" if alvo == "motion" else "modelo_video") or "")
    if guia and modo != "abordagens":
        texto.append(guia)
    if modo == "abordagens":
        if atual.strip():
            texto.append(f"O que o usuário já escreveu (só como pista do que ele quer):\n{atual.strip()}")
    elif atual.strip():
        texto.append(f"Versão atual escrita pelo usuário (melhore mantendo a intenção dele):\n{atual.strip()}")
    else:
        texto.append("Ainda não há texto: escreva do zero.")
    conteudo: list = [{"type": "text", "text": "\n".join(texto)}]
    refs = [r for r in s.get("referencias") or [] if os.path.exists(momentos._abs(r))]
    for i, r in enumerate(refs[:4]):
        b = momentos._imagem_bloco(momentos._abs(r), 768)
        if b:
            rot = "primeiro quadro / referência principal" if i == 0 else "referência"
            conteudo += [{"type": "text", "text": f"Imagem do momento ({rot}): {os.path.basename(r)}"}, b]
    try:
        from acervo import midia
        q = midia.miniatura(momentos._abs(s["video"]), 512, s["ini"] + 0.3)
        b = momentos._imagem_bloco(q, 512)
        if b:
            conteudo += [{"type": "text", "text": "Quadro do vídeo neste instante (o que está na tela por baixo):"}, b]
    except Exception:
        pass
    if modo == "abordagens":
        resp = momentos._json_de(ia.conversar(conteudo, sistema(alvo) + "\n\n" + FORMATO_ABORDAGENS, 2000))
        opcoes = [{"nome": str(o.get("nome") or f"opção {i + 1}").strip(), "ideia": str(o.get("ideia") or "").strip(),
                   "texto": str(o.get("texto") or "").strip()}
                  for i, o in enumerate(resp.get("opcoes") or []) if isinstance(o, dict) and str(o.get("texto") or "").strip()][:3]
        if not opcoes:
            raise RuntimeError("a IA não devolveu abordagens")
        return {"opcoes": opcoes, "ia": ia.info()["nome"]}
    resp = momentos._json_de(ia.conversar(conteudo, sistema(alvo) + "\n\n" + FORMATO, 1500))
    principal = str(resp.get("principal") or "").strip()
    alternativas = [str(x).strip() for x in resp.get("alternativas") or [] if str(x).strip()][:3]
    if not principal:
        raise RuntimeError("a IA não devolveu texto")
    out = {"principal": principal, "alternativas": alternativas, "nota": str(resp.get("nota") or ""),
           "ia": ia.info()["nome"]}
    # o briefing do motion fica gravado no momento (vai para a fila junto); o prompt do vídeo também,
    # para reabrir o formulário com ele
    chave = "briefing" if alvo == "motion" else "prompt_video"
    momentos.marcar(pasta, sid, {chave: principal})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pasta")
    ap.add_argument("id")
    ap.add_argument("alvo", choices=["motion", "video"])
    ap.add_argument("atual", nargs="?", default="")
    ap.add_argument("--modelo", default="")
    ap.add_argument("--abordagens", action="store_true")
    a = ap.parse_args()
    print(json.dumps(pedir(a.pasta, a.id, a.alvo, a.atual, a.modelo, "abordagens" if a.abordagens else "melhorar"),
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
