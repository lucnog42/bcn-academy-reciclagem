#!/usr/bin/env python3
"""Motion para os vídeos: sugerir momentos, aprovar, fila para o Claude, inserir no projeto.

Por item (pasta de post ou pasta de cortes), em `dados/marcas/<marca>/motion/itens/<item>/`:

    contexto.json        o que você quer dizer a mais: {"texto": "..."}
    referencias/         imagens que você deu (logo de clube, foto, print, quadro do vídeo)
    sugestoes.json       os momentos sugeridos, com o status de cada um

Na marca, em `dados/marcas/<marca>/motion/`:

    fila.json            os aprovados que ainda viram filme (a skill de motion lê daqui)
    quadros/<id>.png     o quadro do vídeo no momento, de referência para o filme
    prontos/<id>.mov     o motion exportado (MOV com fundo transparente), que o app insere

Os tempos ficam no tempo do VÍDEO ORIGINAL: se o silêncio for cortado depois, o motion
anda junto com a fala na hora de inserir.

    python3 momentos.py sugerir <pasta> [--max 4]
    python3 momentos.py inserir <pasta> [--onde "projeto e arquivo"] [--projeto <.fcproj>]
    python3 momentos.py fila
    python3 momentos.py teste        # motion/teste_transparencia.mov, para conferir no FilmCraft
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import argparse
import base64
import copy
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
from acervo import colecao  # noqa: E402
from nucleo import config  # noqa: E402
from transcricao import legendas  # noqa: E402

BASE = colecao.BASE
from nucleo import caminhos  # noqa: E402
DIR_MOTION = caminhos.dados("motion")
FILA = os.path.join(DIR_MOTION, "fila.json")
PRONTOS = os.path.join(DIR_MOTION, "prontos")
EXTS_IMG = (".jpg", ".jpeg", ".png", ".webp")
EXTS_PRONTO = (".mov", ".webm", ".mp4")
TIPOS = ("destaque", "numero", "nome", "lugar", "chamada", "broll")
_TRAVA = threading.Lock()


# ------------------------------------------------------------------ caminhos
def _abs(rel: str) -> str:
    return rel if os.path.isabs(rel) else os.path.join(BASE, rel)


def _rel(p: str) -> str:
    """Relativo ao acervo quando está nele; absoluto quando está em dados/ (ou em outra fonte)."""
    r = os.path.relpath(p, BASE)
    return os.path.abspath(p) if r.startswith("..") else r.replace(os.sep, "/")


def chave_item(pasta: str) -> str:
    """`_posts/2025/x` -> `_posts__2025__x`: o nome da pasta de trabalho do item em dados/."""
    return os.path.relpath(_abs(pasta), BASE).replace(os.sep, "__").replace("/", "__").strip("_.") or "raiz"


def pasta_motion(pasta: str) -> str:
    d = os.path.join(DIR_MOTION, "itens", chave_item(pasta))
    os.makedirs(d, exist_ok=True)
    return d


def _ler(caminho: str, padrao):
    try:
        with open(caminho, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return padrao


def _gravar(caminho: str, dados) -> None:
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dados, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)


def videos_da_pasta(pasta: str) -> list[str]:
    """Os vídeos do item, em ordem (os mesmos que o projeto usa), relativos ao acervo."""
    p = _abs(pasta)
    sub = os.path.join(p, "videos")
    onde = sub if os.path.isdir(sub) else p
    return [_rel(os.path.join(onde, n)) for n in sorted(os.listdir(onde))
            if os.path.splitext(n)[1].lower() in (".mp4", ".mov", ".m4v")
            and not colecao.eh_derivado(os.path.join(onde, n))]


# ------------------------------------------------------------------ contexto
def referencias(pasta: str) -> list[str]:
    d = os.path.join(pasta_motion(pasta), "referencias")
    if not os.path.isdir(d):
        return []
    return [_rel(os.path.join(d, n)) for n in sorted(os.listdir(d))
            if os.path.splitext(n)[1].lower() in EXTS_IMG]


def ler_contexto(pasta: str) -> dict:
    return _ler(os.path.join(pasta_motion(pasta), "contexto.json"), {"texto": ""})


def salvar_contexto(pasta: str, texto: str) -> dict:
    d = ler_contexto(pasta)
    d["texto"] = texto
    _gravar(os.path.join(pasta_motion(pasta), "contexto.json"), d)
    return d


def adicionar_referencias(pasta: str, arquivos: list[str]) -> list[str]:
    """Copia imagens (de qualquer lugar do computador) para `motion/referencias/`."""
    d = os.path.join(pasta_motion(pasta), "referencias")
    os.makedirs(d, exist_ok=True)
    novos = []
    for a in arquivos:
        if os.path.splitext(a)[1].lower() not in EXTS_IMG or not os.path.isfile(a):
            continue
        alvo = os.path.join(d, os.path.basename(a))
        k = 2
        while os.path.exists(alvo):
            raiz, ext = os.path.splitext(os.path.basename(a))
            alvo = os.path.join(d, f"{raiz}-{k}{ext}")
            k += 1
        shutil.copy2(a, alvo)
        novos.append(_rel(alvo))
    return novos


def tirar_referencia(pasta: str, arquivo_rel: str) -> str:
    """Tira uma imagem das referências (vai para `referencias/_tiradas/`, nada é apagado)."""
    origem = _abs(arquivo_rel)
    d = os.path.join(pasta_motion(pasta), "referencias")
    if os.path.dirname(os.path.realpath(origem)) != os.path.realpath(d):
        raise ValueError("não é uma referência deste item")
    destino = os.path.join(d, "_tiradas")
    os.makedirs(destino, exist_ok=True)
    alvo = os.path.join(destino, os.path.basename(origem))
    if os.path.exists(alvo):
        raiz, ext = os.path.splitext(alvo)
        alvo = f"{raiz}-{dt.datetime.now():%H%M%S}{ext}"
    shutil.move(origem, alvo)
    return _rel(alvo)


def quadro_como_referencia(pasta: str, video_rel: str, t: float) -> str:
    from acervo import midia
    d = os.path.join(pasta_motion(pasta), "referencias")
    return _rel(midia.exportar_quadro(_abs(video_rel), t, d))


# ------------------------------------------------------------------ sugestões
def ler_sugestoes(pasta: str) -> dict:
    return _ler(os.path.join(pasta_motion(pasta), "sugestoes.json"), {"itens": []})


def gravar_sugestoes(pasta: str, d: dict) -> None:
    _gravar(os.path.join(pasta_motion(pasta), "sugestoes.json"), d)


def _id(pasta: str, video: str, ini: float, texto: str) -> str:
    return "m" + hashlib.sha1(f"{pasta}|{video}|{ini:.2f}|{texto}".encode()).hexdigest()[:10]


def _palavras(video_rel: str) -> list:
    from transcricao import legendar
    w = legendar.caminho_saida(_abs(video_rel), ".words.json")
    return legendas.ler_words_json(w) if os.path.exists(w) else []


def transcricao_com_tempos(videos: list[str]) -> str:
    """Uma linha por cartela: `[v1 12.3–14.0] frase`. Curto e com tempo exato da fala."""
    linhas = []
    for i, v in enumerate(videos, 1):
        ws = _palavras(v)
        if not ws:
            linhas.append(f"[v{i}] (sem transcrição)")
            continue
        for a, b, t in legendas.cartelas(ws, maximo=10, dur_max=5.0):
            linhas.append(f"[v{i} {a:.1f}–{b:.1f}] {t}")
    return "\n".join(linhas)


def _imagem_bloco(caminho: str, px: int = 1024) -> dict | None:
    """Imagem reduzida (lado maior `px`) em base64, como a API pede."""
    from acervo import midia
    try:
        jpg = midia.miniatura(caminho, px)
        with open(jpg, "rb") as fh:
            dados = base64.b64encode(fh.read()).decode()
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": dados}}
    except Exception:
        return None


_SISTEMA = """Você é o diretor de motion da marca abaixo.
{marca}
Você recebe a fala de um vídeo, com o tempo de cada trecho, e escolhe os momentos onde um motion
graphic sobreposto ao vídeo ajuda quem assiste: reforçar uma frase forte, mostrar um número,
apresentar quem fala (nome e função), situar o lugar ou o clube, ou fechar com uma chamada.

Cada momento sai de um de dois jeitos (campo "formato"):
- "motion": gráfico transparente por cima do vídeo (o falante continua visível). Para informação
  que se lê: nome e função, número, frase forte, lugar/clube, chamada final.
- "video": b-roll gerado por IA que cobre a imagem por alguns segundos (a fala continua). Só quando
  a fala cita algo que NÃO aparece na imagem (um estádio, uma cidade, uma viagem, um treino) e uma
  cena ajudaria. Nunca para mostrar pessoas reais da marca nem para texto ({pessoas}). Use "tipo": "broll" e, em
  "texto", descreva a cena em poucas palavras.
Na dúvida, "motion". Depoimento bem enquadrado vale mais que b-roll: use "video" com parcimônia.

Regras:
- O texto na tela sai do que é dito ou do contexto dado pelo usuário. Nunca invente nome,
  número, clube, data ou resultado.
- Curto: até 6 palavras no texto principal; `apoio` (opcional) até 8.
- Cada momento dura de 2 a 5 s e começa junto com a fala que ele reforça (use os tempos dados).
- Momentos não se sobrepõem e ficam a pelo menos 4 s um do outro.
- A legenda fica no terço de baixo: o motion vai em "alto" ou "meio", nunca "baixo".
- Prefira menos e melhores. Se nada vale um motion, devolva lista vazia.
- Português do Brasil.

Responda só com JSON:
{"momentos": [{"video": 1, "ini": 12.3, "fim": 15.0, "formato": "motion|video",
  "tipo": "destaque|numero|nome|lugar|chamada|broll",
  "texto": "...", "apoio": "...", "posicao": "alto|meio", "motivo": "por que aqui, em uma frase",
  "referencia": "nome do arquivo de referência a usar, se algum"}]}"""


def sistema() -> str:
    m = config.carregar()["marca"]
    return (_SISTEMA.replace("{marca}", config.descricao_marca())
            .replace("{pessoas}", m.get("pessoas_reais") or "só em material verdadeiro"))


def _chamar_claude(conteudo: list, sistema: str, max_tokens: int = 3000) -> str:
    """A IA escolhida no painel (Claude, DeepSeek, OpenRouter, Ollama...)."""
    from nucleo import ia
    return ia.conversar(conteudo, sistema, max_tokens)


def _json_de(texto: str) -> dict:
    ini, fim = texto.find("{"), texto.rfind("}")
    if ini < 0 or fim < ini:
        raise ValueError(f"resposta sem JSON: {texto[:200]}")
    return json.loads(texto[ini:fim + 1])


SISTEMA_PROJETO = """
ESTE PEDIDO VEM DO PROJETO DO FILMCRAFT: a fala, as legendas e as camadas já montadas estão no
tempo da TIMELINE do projeto (o vídeo como vai ao ar: silêncios cortados, abertura, logo, ending).
- Use "ini" e "fim" em segundos da timeline (não precisa do campo "video").
- Não ponha motion por cima da abertura (título) nem do logo, nem no encerramento; um momento não
  atravessa uma emenda (corte) entre trechos de fala.
- Considere os motions que já estão no projeto: não repita o mesmo tipo logo em seguida.
- "posicao" leva em conta o que já está na tela naquele instante."""


def linha_do_item(pasta: str):
    """A linha do tempo do projeto do item, se o projeto existe (senão None: usa o vídeo cru)."""
    from projetos import linha_tempo
    proj = projeto_do_item(pasta)
    if not proj or not os.path.exists(proj):
        return None
    try:
        l = linha_tempo.ler(proj)
        return l if l["pecas"] else None
    except Exception:
        return None


def montar_pedido(pasta: str, maximo: int = 4) -> tuple[list, list[str]]:
    """O conteúdo da mensagem: contexto, legenda, transcrição com tempos, referências e
    alguns quadros do vídeo (para o Claude ver a composição)."""
    from acervo import midia
    videos = videos_da_pasta(pasta)
    ctx = ler_contexto(pasta)
    legenda = ""
    for nome in ("legenda.md",):
        c = os.path.join(_abs(pasta), nome)
        if os.path.exists(c):
            legenda = open(c, encoding="utf-8", errors="replace").read()[:1500]
    refs = referencias(pasta)
    conteudo: list = []
    texto = [f"Item: {os.path.basename(_abs(pasta))}",
             f"Vídeos: {len(videos)} (v1 = o primeiro). Máximo de momentos: {maximo}."]
    if ctx.get("texto", "").strip():
        texto.append("Contexto do usuário (vale como fato):\n" + ctx["texto"].strip())
    if legenda.strip():
        texto.append("Legenda do post no Instagram:\n" + legenda.strip())
    linha = linha_do_item(pasta)
    if linha:
        from projetos import linha_tempo
        texto.append("Linha do tempo do projeto do FilmCraft (segundos da timeline):\n" + linha_tempo.resumo(linha))
    else:
        texto.append("Fala com tempos (segundos de cada vídeo):\n" + transcricao_com_tempos(videos))
    conteudo.append({"type": "text", "text": "\n\n".join(texto)})
    for r in refs[:8]:
        b = _imagem_bloco(_abs(r))
        if b:
            conteudo.append({"type": "text", "text": f"Referência do usuário: {os.path.basename(r)}"})
            conteudo.append(b)
    # três quadros: do projeto (no tempo da timeline, levados ao arquivo) ou do 1º vídeo
    if linha:
        from projetos import linha_tempo
        for frac in (0.15, 0.5, 0.85):
            t = linha["fim_video"] * frac
            fonte = linha_tempo.para_fonte(linha, t)
            if not fonte:
                continue
            try:
                b = _imagem_bloco(midia.miniatura(_abs(fonte[0]), 512, fonte[1]), 512)
            except Exception:
                b = None
            if b:
                conteudo.append({"type": "text", "text": f"Quadro do projeto em {t:.1f} s da timeline"})
                conteudo.append(b)
    elif videos:
        try:
            qs = midia.quadros(_abs(videos[0]), 16, 720)
            for k in (1, 8, 14):
                b = _imagem_bloco(qs[k], 512)
                if b:
                    conteudo.append({"type": "text", "text": f"Quadro do v1 ({k + 1}/16 da duração)"})
                    conteudo.append(b)
        except Exception:
            pass
    return conteudo, videos


def sugerir(pasta: str, maximo: int = 4) -> dict:
    conteudo, videos = montar_pedido(pasta, maximo)
    if not videos:
        raise ValueError("o item não tem vídeo")
    from nucleo import ia
    qual = ia.info()
    print(f"▶ pedindo a {qual['nome']} ({qual['modelo']}) até {maximo} momentos ({len(conteudo)} blocos, "
          f"{sum(1 for c in conteudo if c['type'] == 'image')} imagens)", flush=True)
    linha = linha_do_item(pasta)
    if linha:
        print(f"  base: projeto {linha['projeto']} ({linha['duracao']:.1f} s de timeline, "
              f"{len(linha['camadas'])} camadas, {len(linha['legendas'])} legendas)", flush=True)
    else:
        print("  base: o vídeo (o item ainda não tem projeto)", flush=True)
    resp = _json_de(_chamar_claude(conteudo, sistema() + (SISTEMA_PROJETO if linha else "")))
    anterior = {s["id"]: s for s in ler_sugestoes(pasta).get("itens", [])}
    # o que já foi aprovado (ou já está pronto) fica; o resto é trocado pelas sugestões novas
    # e também as sugestões em que você já pôs imagens de referência
    manter = [s for s in anterior.values()
              if s.get("status") in ("aprovado", "pronto") or s.get("referencias")]
    itens = list(manter)
    for m in resp.get("momentos", [])[:maximo]:
        t_proj = None
        try:
            ini, fim = float(m["ini"]), float(m["fim"])
            if linha:
                # tempo da timeline -> vídeo e tempo no arquivo (é assim que o momento é guardado:
                # se o projeto for refeito, ele continua preso à fala)
                from projetos import linha_tempo
                fonte = linha_tempo.para_fonte(linha, ini)
                if not fonte:
                    continue
                t_proj = [round(ini, 2), round(fim, 2)]
                video, src = fonte
                ini, fim = src, src + (fim - ini)
            else:
                k = int(m.get("video", 1)) - 1
                video = videos[max(0, min(k, len(videos) - 1))]
        except (KeyError, ValueError, TypeError):
            continue
        fim = max(fim, ini + 2.0)
        texto = str(m.get("texto", "")).strip()
        if not texto:
            continue
        sid = _id(pasta, video, ini, texto)
        if any(s["id"] == sid for s in itens):
            continue
        itens.append({"id": sid, "video": video, "ini": round(ini, 2), "fim": round(min(fim, ini + 6), 2),
                      "tipo": m.get("tipo") if m.get("tipo") in TIPOS else "destaque",
                      "texto": texto, "apoio": str(m.get("apoio") or "").strip(),
                      "posicao": m.get("posicao") if m.get("posicao") in ("alto", "meio") else "alto",
                      "motivo": str(m.get("motivo") or ""), "referencia": str(m.get("referencia") or ""),
                      "formato": "video" if m.get("formato") == "video" or m.get("tipo") == "broll" else "motion",
                      "base": "projeto" if linha else "video",
                      "status": "sugerido"})
    itens.sort(key=lambda s: (videos.index(s["video"]) if s["video"] in videos else 99, s["ini"]))
    d = {"gerado_em": dt.datetime.now().isoformat(timespec="seconds"),
         "modelo": f"{qual['provedor']}/{qual['modelo']}", "itens": itens}
    gravar_sugestoes(pasta, d)
    for s in itens:
        print(f"  {s['status']:<9} v{videos.index(s['video']) + 1 if s['video'] in videos else '?'} "
              f"{s['ini']:6.1f}–{s['fim']:<6.1f} {s['tipo']:<9} {s['texto']}", flush=True)
    return d


def novo_momento(pasta: str, video: str, ini: float, fim: float | None = None,
                 tipo: str = "broll", texto: str = "") -> dict:
    """Um momento criado à mão (por exemplo, para um b-roll gerado por IA), no quadro escolhido."""
    fim = fim if fim and fim > ini else ini + 4.0
    with _TRAVA:
        d = ler_sugestoes(pasta)
        sid = _id(pasta, video, ini, texto or f"manual-{dt.datetime.now():%H%M%S%f}")
        s = {"id": sid, "video": video, "ini": round(ini, 2), "fim": round(fim, 2), "tipo": tipo,
             "texto": texto, "apoio": "", "posicao": "meio", "motivo": "criado à mão",
             "formato": "video" if tipo == "broll" else "motion",
             "referencias": [], "status": "sugerido"}
        d.setdefault("itens", []).append(s)
        vs = videos_da_pasta(pasta)
        d["itens"].sort(key=lambda x: (vs.index(x["video"]) if x["video"] in vs else 99, x["ini"]))
        gravar_sugestoes(pasta, d)
        return s


# ------------------------------------------------------------------ fila
def ler_fila() -> list[dict]:
    return _ler(FILA, [])


def pronto_de(sid: str) -> str | None:
    """O arquivo pronto do momento: o MOV do Claude ou o MP4 gerado por IA — o mais recente."""
    cands = [os.path.join(PRONTOS, sid + ext) for ext in EXTS_PRONTO]
    cands = [c for c in cands if os.path.exists(c)]
    return max(cands, key=os.path.getmtime) if cands else None


def marcar(pasta: str, sid: str, mudancas: dict) -> dict:
    """Aprova, descarta ou edita (texto, apoio, ini, fim, posicao, tipo) um momento e mantém a fila."""
    with _TRAVA:
        d = ler_sugestoes(pasta)
        s = next((x for x in d["itens"] if x["id"] == sid), None)
        if s is None:
            raise ValueError("momento não encontrado")
        if mudancas.get("formato") in ("motion", "video", "acervo"):
            s["formato"] = mudancas["formato"]
        for k in ("texto", "apoio", "posicao", "tipo", "briefing", "prompt_video", "modelo_motion", "modelo_video"):
            if k == "tipo" and mudancas.get(k) not in TIPOS:
                continue
            if k in mudancas:
                s[k] = str(mudancas[k])
        for k in ("ini", "fim"):
            if k in mudancas:
                s[k] = round(float(mudancas[k]), 2)
        if s["fim"] - s["ini"] < 1.0:
            s["fim"] = round(s["ini"] + 2.0, 2)
        if "status" in mudancas:
            s["status"] = mudancas["status"]
        gravar_sugestoes(pasta, d)
        fila = [p for p in ler_fila() if p["id"] != sid]
        # a fila é do Claude Motion: b-roll do acervo e vídeo gerado não entram nela
        if s["status"] in ("aprovado", "pronto") and s.get("formato", "motion") == "motion":
            fila.append(_pedido(pasta, s))
        _gravar(FILA, fila)
        return s


# ------------------------------------------------------------------ referências por momento
def pasta_refs_momento(pasta: str, sid: str) -> str:
    return os.path.join(pasta_motion(pasta), "referencias", sid)


def _mudar_momento(pasta: str, sid: str, mudar) -> dict:
    """Aplica `mudar(momento)` e, se ele já está aprovado, atualiza o pedido na fila."""
    with _TRAVA:
        d = ler_sugestoes(pasta)
        s = next((x for x in d["itens"] if x["id"] == sid), None)
        if s is None:
            raise ValueError("momento não encontrado")
        s.setdefault("referencias", [])
        mudar(s)
        gravar_sugestoes(pasta, d)
        if s.get("status") in ("aprovado", "pronto"):
            fila = [p for p in ler_fila() if p["id"] != sid]
            fila.append(_pedido(pasta, s))
            _gravar(FILA, fila)
        return s


def ref_momento(pasta: str, sid: str, acao: str, arquivos: list[str] | None = None,
                arquivo: str = "", video: str = "", t: float = 0.0) -> dict:
    """Imagens de referência de UM momento (o logo daquele clube, a foto daquela pessoa):
      adicionar  copia imagens do computador para `motion/referencias/<id>/`
      quadro     o quadro do vídeo no instante `t` vira referência deste momento
      alternar   liga/desliga uma referência geral do item neste momento
      tirar      tira a imagem deste momento (a cópia dele vai para `_tiradas/`; nada é apagado)
    """
    destino = pasta_refs_momento(pasta, sid)

    def mudar(s: dict) -> None:
        refs = s["referencias"]
        if acao == "adicionar":
            os.makedirs(destino, exist_ok=True)
            for a in arquivos or []:
                if os.path.splitext(a)[1].lower() not in EXTS_IMG or not os.path.isfile(a):
                    continue
                alvo = os.path.join(destino, os.path.basename(a))
                k = 2
                while os.path.exists(alvo):
                    raiz, ext = os.path.splitext(os.path.basename(a))
                    alvo = os.path.join(destino, f"{raiz}-{k}{ext}")
                    k += 1
                shutil.copy2(a, alvo)
                refs.append(_rel(alvo))
        elif acao == "quadro":
            from acervo import midia
            refs.append(_rel(midia.exportar_quadro(_abs(video or s["video"]), t, destino)))
        elif acao == "alternar":
            if arquivo in refs:
                refs.remove(arquivo)
            elif arquivo in referencias(pasta):
                refs.append(arquivo)
            else:
                raise ValueError("não é uma referência do item")
        elif acao == "tirar":
            if arquivo in refs:
                refs.remove(arquivo)
            origem = _abs(arquivo)
            if os.path.dirname(os.path.realpath(origem)) == os.path.realpath(destino) and os.path.exists(origem):
                lixo = os.path.join(destino, "_tiradas")
                os.makedirs(lixo, exist_ok=True)
                shutil.move(origem, os.path.join(lixo, os.path.basename(origem)))
        elif acao == "pasta":
            os.makedirs(destino, exist_ok=True)
        else:
            raise ValueError(f"ação desconhecida: {acao}")
    return _mudar_momento(pasta, sid, mudar)


def _no_projeto(pasta: str, s: dict) -> dict:
    """Onde o momento cai na timeline do projeto e o que já está na tela ali (para o filme)."""
    linha = linha_do_item(pasta)
    if not linha:
        return {}
    from projetos import linha_tempo
    t = linha_tempo.para_timeline(linha, s["video"], s["ini"])
    if t is None:
        return {"t_projeto": None, "na_tela": "este trecho foi cortado do projeto"}
    t1 = t + s["fim"] - s["ini"]
    n = linha_tempo.na_tela(linha, t, t1)
    desc = [f"{c['o_que'] or c['faixa']} ({c['t0']:.1f}–{c['t1']:.1f} s)" for c in n["camadas"]]
    return {"t_projeto": [round(t, 2), round(t1, 2)], "projeto": linha["projeto"],
            "na_tela": "; ".join(desc) or "só o vídeo e a legenda",
            "legenda_na_tela": " ".join(n["legendas"])}


def _pedido(pasta: str, s: dict) -> dict:
    """O que a skill de motion precisa para fazer o filme, sem abrir mais nada."""
    from acervo import midia
    os.makedirs(os.path.join(DIR_MOTION, "quadros"), exist_ok=True)
    quadro = os.path.join(DIR_MOTION, "quadros", s["id"] + ".png")
    if not os.path.exists(quadro):
        try:
            tmp = midia.exportar_quadro(_abs(s["video"]), s["ini"] + 0.3, os.path.join(DIR_MOTION, "quadros"))
            os.replace(tmp, quadro)
        except Exception:
            quadro = ""
    info = {}
    try:
        info = midia.info(_abs(s["video"]))
    except Exception:
        pass
    ctx = ler_contexto(pasta).get("texto", "")
    proprias = [r for r in s.get("referencias") or [] if os.path.exists(_abs(r))]
    # as imagens deste momento vêm primeiro: são as que valem para este filme
    refs = proprias + [r for r in referencias(pasta) if r not in proprias]
    return {"id": s["id"], "pasta": pasta, "video": s["video"],
            "ini": s["ini"], "fim": s["fim"], "duracao": round(s["fim"] - s["ini"], 2),
            "tipo": s["tipo"], "texto": s["texto"], "apoio": s.get("apoio", ""),
            "briefing": s.get("briefing", ""),
            **_no_projeto(pasta, s),
            "posicao": s.get("posicao", "alto"),
            "largura": info.get("largura") or 1080, "altura": info.get("altura") or 1920,
            "contexto": ctx, "referencias": refs, "referencias_momento": proprias,
            "referencia_escolhida": s.get("referencia", ""),
            "quadro": _rel(quadro) if quadro else "",
            "saida": f"_motion/prontos/{s['id']}.mov",
            "status": "pronto" if pronto_de(s["id"]) else "na_fila",
            "aprovado_em": dt.datetime.now().isoformat(timespec="seconds")}


def atualizar_prontos(pasta: str | None = None) -> int:
    """Quem já tem `_motion/prontos/<id>.mov` passa a `pronto` (na fila e no item)."""
    fila = ler_fila()
    n = 0
    pastas = {pasta} if pasta else {p["pasta"] for p in fila}
    for p in fila:
        if pronto_de(p["id"]) and p.get("status") != "pronto":
            p["status"] = "pronto"
            n += 1
    if n:
        _gravar(FILA, fila)
    for ps in pastas:
        d = ler_sugestoes(ps)
        mudou = False
        for s in d.get("itens", []):
            if s.get("status") == "aprovado" and pronto_de(s["id"]):
                s["status"] = "pronto"
                mudou = True
        if mudou:
            gravar_sugestoes(ps, d)
    return n


def _tem_ia() -> bool:
    from nucleo import ia
    return bool(ia.info()["claude"])


def estado(pasta: str) -> dict:
    """Tudo que o app mostra na seção Motion do preview."""
    atualizar_prontos(pasta)
    d = ler_sugestoes(pasta)
    linha = linha_do_item(pasta)
    for s in d.get("itens", []):
        p = pronto_de(s["id"])
        s["arquivo_pronto"] = _rel(p) if p else ""
        s["t_projeto"] = None
        if linha:
            from projetos import linha_tempo
            t = linha_tempo.para_timeline(linha, s["video"], s["ini"])
            s["t_projeto"] = None if t is None else [t, round(t + s["fim"] - s["ini"], 2)]
    return {"contexto": ler_contexto(pasta).get("texto", ""), "referencias": referencias(pasta),
            "sugestoes": d.get("itens", []), "gerado_em": d.get("gerado_em", ""),
            "videos": videos_da_pasta(pasta), "chave": _tem_ia(),
            "projeto": linha["projeto"] if linha else "", "duracao_projeto": linha["duracao"] if linha else 0,
            "na_fila": sum(1 for p in ler_fila() if p.get("status") == "na_fila")}


# ------------------------------------------------------------------ inserir
def _dur(arquivo: str) -> float:
    from acervo import midia
    return float(midia.info(arquivo)["duracao"])


def tempo_na_timeline(projeto: str, video_rel: str, t: float) -> float | None:
    """Tempo do vídeo original -> tempo na timeline do projeto (vários vídeos, silêncio cortado)."""
    from projetos import modelo as MF
    from projetos import fcproj
    lado = fcproj.lado_do_projeto(projeto)
    if isinstance(lado, dict) and lado.get("videos"):
        off = 0.0
        for v in lado["videos"]:
            trechos = [(x[0], x[1]) for x in v["trechos"]] if v.get("trechos") else None
            if os.path.realpath(_abs(v["video"])) == os.path.realpath(_abs(video_rel)):
                return off + (MF.mapear_tempo(t, trechos) if trechos else t)
            off += sum(b - a for a, b in trechos) if trechos else float(v.get("duracao") or 0)
        return None
    if isinstance(lado, list) and lado:
        return MF.mapear_tempo(t, [(x[0], x[1]) for x in lado])
    return t


def inserir_no_projeto(projeto: str, momentos: list[dict]) -> int:
    """Uma faixa "Motion" no topo, com cada MOV no seu tempo. Refeita a cada vez (só ela)."""
    from projetos import modelo as MF
    from projetos import fcproj
    proj = fcproj.carregar(projeto)
    k = fcproj.sequencia(proj)
    itens = proj["project"]["items"]
    usados = MF._usados(proj)

    def novo() -> int:
        n = max(max(usados) + 1, 6000)
        usados.add(n)
        return n

    k["video_tracks"] = [t for t in k["video_tracks"] if t.get("name") != "Motion"]
    base_trilha = k["video_tracks"][0]
    base_clipe = base_trilha["items"][0]
    modelo_item = itens[str(base_clipe["item"])]
    canvas_w = int(k["settings"].get("width") or 1080)
    canvas_h = int(k["settings"].get("height") or 1920)
    clipes = []
    fim_ultimo = -1
    for m in sorted(momentos, key=lambda m: m["_t"]):
        arq = m["_arquivo"]
        iid = novo()
        info = MF.probe(arq)
        it = MF.item_midia(modelo_item, arq, info)
        it["id"] = iid
        if "created" in it:
            it["created"] = iid
        itens[str(iid)] = it
        proj["project"]["root"]["children"].append({"Item": iid})
        ini = max(MF.ticks(m["_t"]), fim_ultimo)
        dur = min(info["duration"], MF.ticks(max(1.0, m["fim"] - m["ini"]) + 1.0))
        cl = copy.deepcopy(base_clipe)
        cl.update(id=novo(), item=iid, name=os.path.basename(arq), start=ini, duration=dur,
                  source_in=0, link=None, group=None, gain_db=0.0, markers=[])
        v = info.get("video") or {}
        MF.preencher_quadro(cl, int(v.get("width") or canvas_w), int(v.get("height") or canvas_h),
                            canvas_w, canvas_h)
        clipes.append(cl)
        fim_ultimo = ini + dur
    if clipes:
        trilha = copy.deepcopy(base_trilha)
        trilha.update(id=novo(), name="Motion", items=clipes, transitions=[])
        trilha["sync_lock"] = False
        trilha["locked"] = False
        k["video_tracks"].append(trilha)
    proj["project"]["next_id"] = max(usados) + 1
    fcproj.salvar(proj, projeto)
    return len(clipes)


def renderizar(video_rel: str, momentos: list[dict]) -> str:
    """`saidas/<vídeo>_motion.mp4`: cada motion por cima do vídeo original, no seu tempo."""
    from acervo import midia
    v = _abs(video_rel)
    info = midia.info(v)
    pai = os.path.dirname(v)
    raiz = os.path.dirname(pai) if os.path.basename(pai) == "videos" else pai
    saida = os.path.join(raiz, "saidas", os.path.splitext(os.path.basename(v))[0] + "_motion.mp4")
    os.makedirs(os.path.dirname(saida), exist_ok=True)
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", v]
    filtros, atual = [], "[0:v]"
    for i, m in enumerate(momentos, 1):
        cmd += ["-i", m["_arquivo"]]
        fim = m["ini"] + _dur(m["_arquivo"])
        filtros.append(f"[{i}:v]format=rgba,scale={info['largura']}:{info['altura']},"
                       f"setpts=PTS-STARTPTS+{m['ini']:.3f}/TB[m{i}]")
        filtros.append(f"{atual}[m{i}]overlay=0:0:eof_action=pass:enable='between(t,{m['ini']:.3f},{fim:.3f})'[v{i}]")
        atual = f"[v{i}]"
    cmd += ["-filter_complex", ";".join(filtros), "-map", atual, "-map", "0:a?",
            "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-c:a", "copy", saida]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-400:])
    return saida


def projeto_do_item(pasta: str) -> str | None:
    p = _abs(pasta)
    cands = [os.path.join(p, f) for f in os.listdir(p) if f.endswith(".fcproj")]
    nome = os.path.basename(p)
    pref = os.path.join(p, f"{nome}.fcproj")
    if os.path.exists(pref):
        return pref
    corte = os.path.join(p, colecao.nome_da_pasta_de_cortes(_rel(p)) + ".fcproj")
    if os.path.exists(corte):
        return corte
    return cands[0] if len(cands) == 1 else None


def inserir(pasta: str, onde: str = "projeto e arquivo", projeto: str | None = None) -> None:
    atualizar_prontos(pasta)
    momentos = []
    for s in ler_sugestoes(pasta).get("itens", []):
        arq = pronto_de(s["id"])
        if s.get("status") in ("aprovado", "pronto") and arq:
            momentos.append({**s, "_arquivo": arq})
    from achar import broll
    n_broll = broll.inserir(pasta, onde, projeto)
    if not momentos:
        if not n_broll:
            print("nenhum motion pronto: exporte os filmes para dados/marcas/<marca>/motion/prontos/<id>.mov", flush=True)
        return
    print(f"▶ {len(momentos)} motion(s) pronto(s)", flush=True)
    if "projeto" in onde:
        proj = _abs(projeto) if projeto else projeto_do_item(pasta)
        if not proj or not os.path.exists(proj):
            print("sem projeto do item: gere o projeto primeiro", flush=True)
        else:
            for m in momentos:
                m["_t"] = tempo_na_timeline(proj, m["video"], m["ini"])
            dentro = [m for m in momentos if m["_t"] is not None]
            n = inserir_no_projeto(proj, dentro)
            print(f"projeto: {n} motion(s) na faixa Motion de {os.path.basename(proj)}", flush=True)
    if "arquivo" in onde:
        por_video: dict[str, list] = {}
        for m in momentos:
            por_video.setdefault(m["video"], []).append(m)
        for v, ms in por_video.items():
            print(f"arquivo: {_rel(renderizar(v, sorted(ms, key=lambda m: m['ini'])))}", flush=True)


def teste_transparencia() -> str:
    """Um MOV ProRes 4444 com fundo transparente (faixa vermelha e branca no alto, 4 s):
    arraste para o FilmCraft sobre um vídeo e veja se o fundo some."""
    os.makedirs(DIR_MOTION, exist_ok=True)
    alvo = os.path.join(DIR_MOTION, "teste_transparencia.mov")
    r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi",
                        "-i", "color=c=black@0.0:s=1080x1920:d=4,format=rgba",
                        "-vf", "drawbox=x=90:y=260:w=900:h=240:color=0xE30613@0.92:t=fill:replace=1,"
                               "drawbox=x=90:y=520:w=600:h=90:color=0xFFFFFF@0.85:t=fill:replace=1",
                        "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", alvo],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-300:])
    return alvo


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sugerir")
    s.add_argument("pasta")
    s.add_argument("--max", type=int, default=4)
    i = sub.add_parser("inserir")
    i.add_argument("pasta")
    i.add_argument("--onde", default="projeto e arquivo")
    i.add_argument("--projeto")
    sub.add_parser("fila")
    sub.add_parser("teste")
    a = ap.parse_args()
    if a.cmd == "sugerir":
        sugerir(a.pasta, a.max)
    elif a.cmd == "inserir":
        inserir(a.pasta, a.onde, a.projeto)
    elif a.cmd == "teste":
        print(teste_transparencia())
    else:
        atualizar_prontos()
        for p in ler_fila():
            print(f"{p['status']:<8} {p['id']}  {p['pasta']}  {p['ini']:.1f}s  {p['tipo']:<9} {p['texto']}")


if __name__ == "__main__":
    main()
