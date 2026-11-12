#!/usr/bin/env python3
"""B-roll do acervo para um momento: vários candidatos, de várias fontes, e uma sequência curta.

1. `candidatos(pasta, id)`: monta as buscas do momento (o texto dele, a fala ao redor e, se pedir,
   as buscas que a IA escreve), procura no índice (achar/indice.py) e devolve 3–5 candidatos
   diferentes (no máximo 2 do mesmo item), cada um com miniatura. Ficam em `broll.candidatos`.
2. `sequencia(pasta, id, itens)`: você escolhe 1–3 candidatos, em ordem, com a duração de cada
   um; a soma cobre o momento. Fica em `broll.sequencia`, e o momento passa a `formato = "acervo"`.
3. `inserir(pasta, onde)`: põe as sequências aprovadas numa faixa "B-roll" do projeto do
   FilmCraft (refeita a cada vez, só ela) e/ou grava `saidas/<vídeo>_broll.mp4`.
   Vídeo entra como referência ao original (com o ponto de entrada); imagem vira um clipe curto
   com zoom lento em dados/marcas/<marca>/broll/ (o original não é tocado).

    python3 src/achar/broll.py candidatos <pasta> <id> [--ia] [-n 5]
    python3 src/achar/broll.py inserir <pasta> [--onde "projeto e arquivo"]
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess

from achar import indice  # noqa: E402
from nucleo import caminhos, config  # noqa: E402
from plano import momentos  # noqa: E402

MAX_SEQ = 3
PARADAS = set("""a o as os um uma uns umas de da do das dos em na no nas nos por para pra com sem que
e é ou se eu tu ele ela nós vocês eles elas me te lhe isso isto aquilo esse essa este esta aqui ali lá
muito muita mais menos já ainda também então quando onde como porque pois mas meu minha seu sua
nosso nossa ser estar ter ir foi era são está tá vai vou tem tinha gente coisa assim aí né""".split())


def _momento(pasta: str, sid: str) -> dict:
    s = next((x for x in momentos.ler_sugestoes(pasta).get("itens", []) if x["id"] == sid), None)
    if s is None:
        raise ValueError("momento não encontrado")
    return s


def _termos(texto: str) -> list[str]:
    ws = re.findall(r"[\wÀ-ÿ]+", (texto or "").lower())
    return [w for w in ws if len(w) >= 4 and w not in PARADAS and not w.isdigit()]


def _fala_ao_redor(s: dict, folga: float = 2.0) -> str:
    try:
        return " ".join(t for a, b, t in momentos._palavras(s["video"]) if b >= s["ini"] - folga and a <= s["fim"] + folga)
    except Exception:
        return ""


def consultas_ia(pasta: str, s: dict) -> list[str]:
    """A IA das sugestões escreve 3 buscas curtas (o que MOSTRAR, não o que é dito)."""
    from nucleo import ia
    cfg = config.carregar()
    pilares = ", ".join(cfg["pilares"].get("ordem") or [])
    texto = (f"Marca: {config.descricao_marca()}\nMomento ({s.get('tipo')}): {s.get('texto', '')}"
             f"{' / ' + s['apoio'] if s.get('apoio') else ''}\nFala ao redor: {_fala_ao_redor(s)}\n"
             f"Contexto do item: {momentos.ler_contexto(pasta).get('texto', '')}\nPilares do acervo: {pilares}")
    sistema = ("Você procura b-roll num acervo de fotos e vídeos de uma marca. O índice tem legendas de posts, "
               "nomes de pastas e o que é falado nos vídeos, em português. Escreva 3 buscas curtas (2 a 4 palavras "
               "cada) com o que deveria APARECER na imagem para ilustrar o momento: lugar, ação, objeto, evento. "
               'Responda só com JSON: {"buscas": ["...", "...", "..."]}')
    r = momentos._json_de(ia.conversar([{"type": "text", "text": texto}], sistema, 300))
    return [str(x).strip() for x in r.get("buscas") or [] if str(x).strip()][:3]


def _sobrepoe(c: dict, s: dict) -> bool:
    """O próprio trecho do momento não serve de b-roll para ele mesmo."""
    return c["arquivo"] == s["video"] and (c["fim"] == 0 or (c["ini"] < s["fim"] + 1 and c["fim"] > s["ini"] - 1))


def _miniatura(c: dict) -> str:
    from acervo import midia
    try:
        alvo = c["arquivo"] if os.path.isabs(c["arquivo"]) else momentos._abs(c["arquivo"])
        t = (c["ini"] + 0.5) if c["tipo"] == "video" else None
        return midia.miniatura(alvo, 320, t) if t is not None else midia.miniatura(alvo, 320)
    except Exception:
        return ""


def candidatos(pasta: str, sid: str, n: int = 5, usar_ia: bool = False, db: str | None = None) -> dict:
    if indice.precisa_indexar(db):
        indice.indexar(db=db)
    s = _momento(pasta, sid)
    base = _termos(f"{s.get('texto', '')} {s.get('apoio', '')}")
    fala = _termos(_fala_ao_redor(s))
    buscas: list[list[str]] = []
    ia_buscas: list[str] = []
    if usar_ia:
        ia_buscas = consultas_ia(pasta, s)
        buscas += [_termos(b) or b.split() for b in ia_buscas]
    if base:
        buscas.append(base)
    if fala:
        buscas.append(fala[:10])
    vistos: dict[tuple, dict] = {}
    for peso, termos in zip([1.0, 0.9, 0.8, 0.7, 0.6], buscas):
        for r in indice.buscar(termos, 60, db):
            if _sobrepoe(r, s):
                continue
            k = (r["arquivo"], round(float(r["ini"]), 1))
            r = {**r, "score": r["score"] * peso}
            if k not in vistos or vistos[k]["score"] < r["score"]:
                vistos[k] = r
    por_item: dict[str, int] = {}
    escolhidos = []
    for r in sorted(vistos.values(), key=lambda r: -r["score"]):
        if por_item.get(r["item"], 0) >= 2:
            continue
        por_item[r["item"]] = por_item.get(r["item"], 0) + 1
        cid = hashlib.sha1(f"{r['arquivo']}|{r['ini']}".encode()).hexdigest()[:10]
        escolhidos.append({"id": cid, "fonte": r["fonte"], "arquivo": r["arquivo"], "tipo": r["tipo"],
                           "ini": round(float(r["ini"]), 2), "fim": round(float(r["fim"]), 2),
                           "item": r["item"], "texto": r["texto"][:160], "score": round(r["score"], 2)})
        if len(escolhidos) >= n:
            break
    for c in escolhidos:
        c["miniatura"] = _miniatura(c)

    def mudar(x: dict) -> None:
        b = x.setdefault("broll", {})
        b["candidatos"] = escolhidos
        b["buscas"] = ia_buscas or [" ".join(t) for t in buscas]
    momentos._mudar_momento(pasta, sid, mudar)
    return {"candidatos": escolhidos, "buscas": ia_buscas or [" ".join(t) for t in buscas]}


def sequencia(pasta: str, sid: str, itens: list[dict]) -> dict:
    """1–3 pedaços em ordem: {arquivo, tipo, ini (no original), dur}. Sem dur, divide o momento."""
    s = _momento(pasta, sid)
    itens = [i for i in itens if i.get("arquivo")][:MAX_SEQ]
    total = max(1.0, s["fim"] - s["ini"])
    sem = [i for i in itens if not i.get("dur")]
    livre = max(0.0, total - sum(float(i["dur"]) for i in itens if i.get("dur")))
    seq = []
    for i in itens:
        dur = float(i.get("dur") or (livre / len(sem) if sem else total / len(itens)))
        seq.append({"arquivo": i["arquivo"], "tipo": i.get("tipo") or ("imagem" if os.path.splitext(i["arquivo"])[1].lower()
                                                                     in indice.IMAGEM else "video"),
                    "ini": round(float(i.get("ini") or 0.0), 2), "dur": round(max(0.5, dur), 2)})

    def mudar(x: dict) -> None:
        x.setdefault("broll", {})["sequencia"] = seq
        if seq:
            x["formato"] = "acervo"
        elif x.get("formato") == "acervo":
            x["formato"] = "video" if x.get("tipo") == "broll" else "motion"
    return momentos._mudar_momento(pasta, sid, mudar)


# ------------------------------------------------------------------ montar
def _abs(arq: str) -> str:
    return arq if os.path.isabs(arq) else momentos._abs(arq)


def clipe_de_imagem(arq: str, dur: float, w: int = 1080, h: int = 1920) -> str:
    """A foto vira um MP4 curto, cobrindo o quadro, com zoom lento (o original fica como está)."""
    chave = hashlib.sha1(f"{arq}|{os.path.getmtime(arq)}|{dur:.2f}|{w}x{h}".encode()).hexdigest()[:12]
    alvo = caminhos.dados("broll", f"{chave}.mp4")
    if os.path.exists(alvo):
        return alvo
    quadros = max(1, int(dur * 30))
    vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
          f"zoompan=z='min(1+0.0008*on,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={quadros}:s={w}x{h}:fps=30,"
          "format=yuv420p")
    r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-loop", "1", "-i", arq, "-t", f"{dur:.2f}",
                        "-vf", vf, "-c:v", "libx264", "-crf", "18", "-an", alvo], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-300:])
    return alvo


def _pecas(s: dict, w: int, h: int) -> list[dict]:
    """Os pedaços da sequência prontos para montar: arquivo, entrada no original, duração."""
    out = []
    for p in (s.get("broll") or {}).get("sequencia") or []:
        arq = _abs(p["arquivo"])
        if not os.path.exists(arq):
            continue
        if p.get("tipo") == "imagem":
            out.append({"arquivo": clipe_de_imagem(arq, p["dur"], w, h), "ini": 0.0, "dur": p["dur"]})
        else:
            out.append({"arquivo": arq, "ini": p.get("ini", 0.0), "dur": p["dur"]})
    return out


def inserir_no_projeto(projeto: str, momentos_: list[dict]) -> int:
    """Uma faixa "B-roll" (logo acima do vídeo principal), refeita a cada vez; só ela muda."""
    from projetos import fcproj
    from projetos import modelo as MF
    proj = fcproj.carregar(projeto)
    k = fcproj.sequencia(proj)
    itens = proj["project"]["items"]
    usados = MF._usados(proj)

    def novo() -> int:
        n = max(max(usados) + 1, 7000)
        usados.add(n)
        return n

    k["video_tracks"] = [t for t in k["video_tracks"] if t.get("name") != "B-roll"]
    base_trilha = k["video_tracks"][0]
    base_clipe = base_trilha["items"][0]
    modelo_item = itens[str(base_clipe["item"])]
    cw = int(k["settings"].get("width") or 1080)
    ch = int(k["settings"].get("height") or 1920)
    clipes, fim_ultimo = [], -1
    for m in sorted(momentos_, key=lambda m: m["_t"]):
        t = MF.ticks(m["_t"])
        for p in _pecas(m, cw, ch):
            info = MF.probe(p["arquivo"])
            iid = novo()
            it = MF.item_midia(modelo_item, p["arquivo"], info)
            it["id"] = iid
            if "created" in it:
                it["created"] = iid
            itens[str(iid)] = it
            proj["project"]["root"]["children"].append({"Item": iid})
            ini = max(t, fim_ultimo)
            dur = MF.ticks(p["dur"])
            cl = copy.deepcopy(base_clipe)
            cl.update(id=novo(), item=iid, name=os.path.basename(p["arquivo"]), start=ini, duration=dur,
                      source_in=MF.ticks(p["ini"]), link=None, group=None, gain_db=-96.0, markers=[])
            v = info.get("video") or {}
            MF.preencher_quadro(cl, int(v.get("width") or cw), int(v.get("height") or ch), cw, ch)
            clipes.append(cl)
            fim_ultimo = ini + dur
            t = fim_ultimo
    if clipes:
        trilha = copy.deepcopy(base_trilha)
        trilha.update(id=novo(), name="B-roll", items=clipes, transitions=[])
        trilha["sync_lock"] = False
        trilha["locked"] = False
        k["video_tracks"].insert(1, trilha)
    proj["project"]["next_id"] = max(usados) + 1
    fcproj.salvar(proj, projeto)
    return len(clipes)


def renderizar(video_rel: str, momentos_: list[dict]) -> str:
    """`saidas/<vídeo>_broll.mp4`: a sequência de cada momento cobrindo a imagem; o som é o original."""
    from acervo import midia
    v = momentos._abs(video_rel)
    info = midia.info(v)
    w, h = int(info["largura"]), int(info["altura"])
    pai = os.path.dirname(v)
    raiz = os.path.dirname(pai) if os.path.basename(pai) == "videos" else pai
    saida = os.path.join(raiz, "saidas", os.path.splitext(os.path.basename(v))[0] + "_broll.mp4")
    os.makedirs(os.path.dirname(saida), exist_ok=True)
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", v]
    filtros, atual, i = [], "[0:v]", 0
    for m in sorted(momentos_, key=lambda m: m["ini"]):
        t = m["ini"]
        for p in _pecas(m, w, h):
            i += 1
            cmd += ["-ss", f"{p['ini']:.3f}", "-t", f"{p['dur']:.3f}", "-i", p["arquivo"]]
            filtros.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                           f"setpts=PTS-STARTPTS+{t:.3f}/TB[b{i}]")
            filtros.append(f"{atual}[b{i}]overlay=0:0:eof_action=pass:enable='between(t,{t:.3f},{t + p['dur']:.3f})'[v{i}]")
            atual = f"[v{i}]"
            t += p["dur"]
    if not filtros:
        raise RuntimeError("nenhum pedaço de b-roll encontrado")
    cmd += ["-filter_complex", ";".join(filtros), "-map", atual, "-map", "0:a?",
            "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "copy", saida]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-400:])
    return saida


def aprovados(pasta: str) -> list[dict]:
    return [s for s in momentos.ler_sugestoes(pasta).get("itens", [])
            if s.get("formato") == "acervo" and s.get("status") in ("aprovado", "pronto")
            and (s.get("broll") or {}).get("sequencia")]


def inserir(pasta: str, onde: str = "projeto e arquivo", projeto: str | None = None) -> int:
    ms = aprovados(pasta)
    if not ms:
        return 0
    print(f"▶ {len(ms)} b-roll(s) do acervo aprovado(s)", flush=True)
    if "projeto" in onde:
        proj = momentos._abs(projeto) if projeto else momentos.projeto_do_item(pasta)
        if not proj or not os.path.exists(proj):
            print("sem projeto do item: gere o projeto primeiro", flush=True)
        else:
            for m in ms:
                m["_t"] = momentos.tempo_na_timeline(proj, m["video"], m["ini"])
            n = inserir_no_projeto(proj, [m for m in ms if m["_t"] is not None])
            print(f"projeto: {n} pedaço(s) na faixa B-roll de {os.path.basename(proj)}", flush=True)
    if "arquivo" in onde:
        por_video: dict[str, list] = {}
        for m in ms:
            por_video.setdefault(m["video"], []).append(m)
        for v, lista in por_video.items():
            print(f"arquivo: {momentos._rel(renderizar(v, lista))}", flush=True)
    return len(ms)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidatos")
    c.add_argument("pasta")
    c.add_argument("id")
    c.add_argument("-n", type=int, default=5)
    c.add_argument("--ia", action="store_true")
    i = sub.add_parser("inserir")
    i.add_argument("pasta")
    i.add_argument("--onde", default="projeto e arquivo")
    a = ap.parse_args()
    if a.cmd == "candidatos":
        print(json.dumps(candidatos(a.pasta, a.id, a.n, a.ia), ensure_ascii=False, indent=1))
    else:
        if not inserir(a.pasta, a.onde):
            print("nenhum b-roll do acervo aprovado neste item", flush=True)


if __name__ == "__main__":
    main()
