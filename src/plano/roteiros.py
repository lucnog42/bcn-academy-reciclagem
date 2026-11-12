#!/usr/bin/env python3
"""Roteiros recomendados: a partir do que já foi gravado (o banco de falas), a IA propõe vídeos
novos, com estrutura de história e uma função para cada parte.

  * ideias(tema)      -> 3–5 propostas (título, formato, por que funciona, o que procurar)
  * escrever(...)     -> o roteiro: partes em ordem; cada parte é uma FALA que já existe (vídeo e
                         tempo exatos) ou uma FALA NOVA para gravar/locutar; cada uma com função
                         (provar, clima, contraste, só a pessoa) e o que mostrar por cima, já com
                         candidatos do acervo
  * aprovar(id)       -> cria o projeto do FilmCraft com o primeiro corte (só falas e imagens do
                         acervo; nada gerado) e os momentos de cada parte, para trocar b-roll,
                         pôr motion ou gerar o que faltar
  * excluir(id)       -> vai para dados/.../roteiros/excluidos/ (dá para recuperar à mão)

Os roteiros ficam em dados/marcas/<marca>/roteiros/<id>.json.

    python3 src/plano/roteiros.py ideias ["tema"]
    python3 src/plano/roteiros.py escrever "tema" --formato depoimento --duracao 45
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess

from nucleo import caminhos, config  # noqa: E402
from plano import falas  # noqa: E402

FUNCOES_PADRAO = ("provar", "clima", "contraste", "so-a-pessoa")
PALAVRAS_POR_S = 2.6          # ritmo de fala para estimar a duração de uma fala nova


def pasta() -> str:
    return caminhos.dados("roteiros")


def formatos() -> dict:
    return (config.carregar().get("roteiros") or {}).get("formatos") or {}


def funcoes() -> dict:
    f = (config.carregar().get("funcoes") or {}).get("funcoes") or {}
    return f or {k: {"nome": k, "descricao": "", "pode_gerar": k in ("clima", "contraste")} for k in FUNCOES_PADRAO}


# ------------------------------------------------------------------ texto para a IA
def _sistema() -> str:
    cfg = config.carregar()
    m = cfg["marca"]
    fs = "\n".join(f"- {k}: {v.get('descricao', '')}" + ("" if v.get("pode_gerar") else " (só material verdadeiro)")
                   for k, v in funcoes().items())
    return f"""Você é roteirista de vídeos curtos verticais para Instagram de uma marca.
Marca: {config.descricao_marca()}
Pessoas reais da marca: {m.get('pessoas_reais') or 'só em material verdadeiro'}.

O vídeo novo é montado com FALAS QUE JÁ FORAM GRAVADAS (cada uma tem um id, e o texto dela não
muda: ela entra como foi dita) e, só quando faltar uma ligação, com FALAS NOVAS curtas para gravar
ou locutar. Prefira sempre as falas existentes; uma fala nova é a exceção.

Cada parte tem uma FUNÇÃO para a imagem que vai por cima da fala:
{fs}
E diz o que MOSTRAR: 2 a 5 palavras concretas para buscar no acervo (lugar, ação, objeto, evento).
Regras: não invente nome, número, clube, data ou promessa que não esteja nas falas; uma fala
existente não pode ser usada duas vezes; o gancho vem nos primeiros 3 segundos."""


def _listar_frases(fs: list[dict]) -> str:
    return "\n".join(f"[{f['id']}] ({f['fim'] - f['ini']:.0f}s · {f['item'].split('/')[-1][:30]}) {f['texto']}" for f in fs)


# ------------------------------------------------------------------ ideias
def ideias(tema: str = "", n: int = 4) -> list[dict]:
    from nucleo import ia
    from plano import momentos
    falas.garantir()
    base = falas.buscar(_termos(tema), 50) if tema.strip() else []
    vistas = {f["id"] for f in base}
    pool = base + [f for f in falas.amostra(110) if f["id"] not in vistas]
    fmts = "\n".join(f"- {k}: {v.get('nome')} — {v.get('descricao', '')}" for k, v in formatos().items())
    pedido = (f"Formatos possíveis:\n{fmts}\n\n"
              + (f"O usuário quer vídeos sobre: {tema}\n\n" if tema.strip() else "")
              + f"Falas disponíveis no acervo (amostra):\n{_listar_frases(pool[:140])}\n\n"
              f"Proponha {n} vídeos DIFERENTES que dá para montar com essas falas. Responda só com JSON:\n"
              '{"ideias": [{"titulo": "...", "formato": "<id do formato>", "objetivo": "o que o vídeo faz o público sentir/fazer", '
              '"gancho": "a primeira frase", "por_que": "por que funciona com este material", '
              '"buscas": ["2-4 palavras", "..."], "falas": ["ids das falas centrais"]}]}')
    r = momentos._json_de(ia.conversar([{"type": "text", "text": pedido}], _sistema(), 6000))
    out = []
    for i in r.get("ideias") or []:
        if not isinstance(i, dict) or not i.get("titulo"):
            continue
        fmt = i.get("formato") if i.get("formato") in formatos() else next(iter(formatos()), "depoimento")
        iid = hashlib.sha1(f"{i['titulo']}|{dt.datetime.now().isoformat()}".encode()).hexdigest()[:8]
        out.append({"id": iid, "titulo": str(i["titulo"]).strip(), "formato": fmt,
                    "objetivo": str(i.get("objetivo") or ""), "gancho": str(i.get("gancho") or ""),
                    "por_que": str(i.get("por_que") or ""), "buscas": [str(b) for b in i.get("buscas") or []][:5],
                    "falas": [str(x) for x in i.get("falas") or []][:12], "tema": tema})
    _gravar(os.path.join(pasta(), "ideias.json"), {"tema": tema, "criado_em": _agora(), "ideias": out})
    return out


def ler_ideias() -> list[dict]:
    try:
        with open(os.path.join(pasta(), "ideias.json"), encoding="utf-8") as fh:
            return json.load(fh).get("ideias") or []
    except (OSError, ValueError):
        return []


# ------------------------------------------------------------------ escrever
def escrever(tema: str = "", formato: str = "", duracao: int = 0, ideia: str = "") -> dict:
    from nucleo import ia
    from plano import momentos
    falas.garantir()
    idd = next((x for x in ler_ideias() if x["id"] == ideia), None) if ideia else None
    if idd:
        tema = tema or f"{idd['titulo']}. {idd['objetivo']}"
        formato = formato or idd["formato"]
    fmts = formatos()
    formato = formato if formato in fmts else next(iter(fmts), "depoimento")
    fmt = fmts.get(formato) or {}
    duracao = int(duracao or fmt.get("duracao") or 45)
    termos = _termos(tema) + [w for b in (idd or {}).get("buscas") or [] for w in _termos(b)]
    pool = falas.buscar(termos, 70) if termos else []
    centrais = falas.por_ids((idd or {}).get("falas") or [])
    vistas = {f["id"] for f in pool}
    pool = [f for f in centrais.values() if f["id"] not in vistas] + pool
    if len(pool) < 25:
        vistas = {f["id"] for f in pool}
        pool += [f for f in falas.amostra(80) if f["id"] not in vistas]
    if not pool:
        raise RuntimeError("o banco de falas está vazio: transcreva vídeos (Legendar ou aba Importar → transcrever)")
    estrutura = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(fmt.get("estrutura") or []))
    pedido = (f"Escreva o roteiro de um vídeo de cerca de {duracao} s.\n"
              f"Tema / pedido: {tema or 'o melhor vídeo possível com estas falas'}\n"
              f"Formato: {fmt.get('nome', formato)} — {fmt.get('descricao', '')}\nEstrutura:\n{estrutura}\n"
              + (f"Ideia de partida: {json.dumps(idd, ensure_ascii=False)}\n" if idd else "")
              + f"\nFalas disponíveis (use o id; a duração de cada uma está entre parênteses):\n{_listar_frases(pool[:110])}\n\n"
              "Responda só com JSON:\n"
              '{"titulo": "...", "resumo": "uma frase", "partes": [\n'
              ' {"parte": "gancho", "tipo": "fala", "id": "<id>", "funcao": "provar|clima|contraste|so-a-pessoa", '
              '"mostrar": "2-5 palavras", "por_que": "..."},\n'
              ' {"parte": "...", "tipo": "nova", "texto": "a fala nova, até 25 palavras", "quem": "locução ou quem deve gravar", '
              '"funcao": "...", "mostrar": "...", "por_que": "..."}\n]}')
    r = momentos._json_de(ia.conversar([{"type": "text", "text": pedido}], _sistema(), 8000))
    por_id = {f["id"]: f for f in pool}
    faltando = [str(p.get("id")) for p in r.get("partes") or [] if isinstance(p, dict) and p.get("tipo") == "fala"
                and str(p.get("id")) not in por_id]
    por_id.update(falas.por_ids(faltando))
    partes, usadas = [], set()
    fs_validas = funcoes()
    for p in r.get("partes") or []:
        if not isinstance(p, dict):
            continue
        funcao = p.get("funcao") if p.get("funcao") in fs_validas else "so-a-pessoa"
        base = {"parte": str(p.get("parte") or ""), "funcao": funcao, "mostrar": str(p.get("mostrar") or "").strip(),
                "por_que": str(p.get("por_que") or "")}
        if p.get("tipo") == "nova":
            texto = str(p.get("texto") or "").strip()
            if not texto:
                continue
            partes.append({**base, "tipo": "nova", "texto": texto, "quem": str(p.get("quem") or "locução"),
                           "dur": round(max(1.5, len(texto.split()) / PALAVRAS_POR_S), 1)})
        else:
            f = por_id.get(str(p.get("id")))
            if not f or f["id"] in usadas:
                continue
            usadas.add(f["id"])
            partes.append({**base, "tipo": "fala", "id": f["id"], "texto": f["texto"], "video": f["video"],
                           "ini": f["ini"], "fim": f["fim"], "item": f["item"], "fonte": f["fonte"],
                           "dur": round(f["fim"] - f["ini"], 1)})
    if not partes:
        raise RuntimeError("a IA não montou nenhuma parte com as falas do banco")
    usados: set[str] = set()
    for p in partes:
        p["cobertura"] = _cobertura(p)
        # a mesma imagem não cobre duas partes (se houver outra)
        livre = next((c for c in p["cobertura"] if c["arquivo"] not in usados), None) or (p["cobertura"] or [None])[0]
        p["escolhida"] = livre["id"] if livre else ""
        if livre:
            usados.add(livre["arquivo"])
    rid = base = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    n = 2
    while os.path.exists(_arq(rid)):          # dois roteiros no mesmo segundo
        rid, n = f"{base}-{n}", n + 1
    rot = {"id": rid, "titulo": str(r.get("titulo") or tema or "roteiro").strip(), "resumo": str(r.get("resumo") or ""),
           "tema": tema, "formato": formato, "duracao_alvo": duracao, "ideia": ideia,
           "duracao": round(sum(p["dur"] for p in partes), 1), "status": "sugerido", "criado_em": _agora(),
           "ia": ia.info()["nome"], "partes": partes}
    salvar(rot)
    return rot


def _cobertura(p: dict, n: int = 4) -> list[dict]:
    """Candidatos do acervo para o que a parte manda mostrar (nada para "só a pessoa")."""
    if p["funcao"] == "so-a-pessoa" or not p.get("mostrar"):
        return []
    from achar import broll, indice
    termos = broll._termos(p["mostrar"]) or p["mostrar"].split()
    vistos, out, por_item = set(), [], {}
    for r in indice.buscar(termos, 40):
        if r["arquivo"] == p.get("video"):
            continue
        k = (r["arquivo"], round(float(r["ini"]), 1))
        if k in vistos or por_item.get(r["item"], 0) >= 2:
            continue
        vistos.add(k)
        por_item[r["item"]] = por_item.get(r["item"], 0) + 1
        c = {"id": hashlib.sha1(f"{r['arquivo']}|{r['ini']}".encode()).hexdigest()[:10], "fonte": r["fonte"],
             "arquivo": r["arquivo"], "tipo": r["tipo"], "ini": round(float(r["ini"]), 2),
             "fim": round(float(r["fim"]), 2), "item": r["item"], "texto": r["texto"][:140]}
        c["miniatura"] = broll._miniatura(c)
        out.append(c)
        if len(out) >= n:
            break
    return out


# ------------------------------------------------------------------ guardar, listar, editar
def _agora() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _gravar(arq: str, d) -> None:
    tmp = arq + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, arq)


def _arq(rid: str) -> str:
    if not re.fullmatch(r"[0-9-]{6,32}", rid or ""):
        raise ValueError("roteiro inválido")
    return os.path.join(pasta(), f"{rid}.json")


def salvar(rot: dict) -> dict:
    rot["duracao"] = round(sum(p["dur"] for p in rot["partes"]), 1)
    _gravar(_arq(rot["id"]), rot)
    return rot


def ler(rid: str) -> dict:
    with open(_arq(rid), encoding="utf-8") as fh:
        return json.load(fh)


def listar() -> list[dict]:
    out = []
    for n in sorted(os.listdir(pasta()), reverse=True):
        if not re.fullmatch(r"[0-9-]+\.json", n):
            continue
        try:
            r = ler(n[:-5])
        except (OSError, ValueError):
            continue
        out.append({k: r.get(k) for k in ("id", "titulo", "resumo", "formato", "duracao", "duracao_alvo", "status",
                                          "criado_em", "pasta", "projeto")}
                   | {"partes": len(r.get("partes") or []),
                      "novas": sum(1 for p in r.get("partes") or [] if p.get("tipo") == "nova")})
    return out


def excluir(rid: str) -> None:
    lixo = caminhos.dados("roteiros", "excluidos")
    os.makedirs(lixo, exist_ok=True)
    shutil.move(_arq(rid), os.path.join(lixo, f"{rid}.json"))


def editar(rid: str, acao: str, i: int, valor=None) -> dict:
    """mover (valor = -1/+1), remover, texto (fala nova), escolher (id do candidato ou "")."""
    rot = ler(rid)
    if rot.get("status") == "aprovado" and acao != "escolher":
        raise ValueError("roteiro aprovado: mude no projeto (ou exclua e escreva de novo)")
    ps = rot["partes"]
    if not 0 <= i < len(ps):
        raise ValueError("parte inexistente")
    if acao == "mover":
        j = i + (1 if int(valor or 1) > 0 else -1)
        if 0 <= j < len(ps):
            ps[i], ps[j] = ps[j], ps[i]
    elif acao == "remover":
        ps.pop(i)
    elif acao == "texto":
        if ps[i]["tipo"] != "nova":
            raise ValueError("uma fala gravada não muda de texto")
        ps[i]["texto"] = str(valor or "").strip()
        ps[i]["dur"] = round(max(1.5, len(ps[i]["texto"].split()) / PALAVRAS_POR_S), 1)
    elif acao == "escolher":
        if valor and valor not in {c["id"] for c in ps[i].get("cobertura") or []}:
            raise ValueError("candidato inexistente")
        ps[i]["escolhida"] = valor or ""
    else:
        raise ValueError(f"ação desconhecida: {acao}")
    return salvar(rot)


# ------------------------------------------------------------------ aprovar: o primeiro corte
def _cartao_fala_nova(p: dict, alvo: str, w: int = 1080, h: int = 1920) -> str:
    """Um MP4 escuro com a fala nova escrita (o lugar dela no corte, até ser gravada), com som mudo."""
    if os.path.exists(alvo):
        return alvo
    texto = f"FALA NOVA ({p.get('quem') or 'locução'}):\n\n" + "\n".join(_quebrar(p["texto"], 26))
    txt = alvo + ".txt"
    with open(txt, "w", encoding="utf-8") as fh:
        fh.write(texto)
    base = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x15151b:s={w}x{h}:d={p['dur']:.2f}:r=30",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest"]
    fim = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-g", "30", alvo]
    r = subprocess.run(base + ["-vf", f"drawtext=textfile='{txt}':fontcolor=white:fontsize=54:line_spacing=18:"
                                      f"x=(w-text_w)/2:y=(h-text_h)/2"] + fim, capture_output=True, text=True)
    if r.returncode != 0:      # ffmpeg sem drawtext/fontconfig: o cartão sai só escuro
        subprocess.run(base + fim, capture_output=True, text=True, check=True)
    os.unlink(txt)
    return alvo


def _quebrar(t: str, largura: int) -> list[str]:
    linhas, atual = [], ""
    for w in t.split():
        if len(atual) + len(w) + 1 > largura and atual:
            linhas.append(atual)
            atual = w
        else:
            atual = f"{atual} {w}".strip()
    return linhas + ([atual] if atual else [])


def _janela(p: dict) -> tuple[float, float]:
    """Quanto da parte a imagem cobre: provar entra e sai por dentro da fala; clima e contraste cobrem mais."""
    d = p["dur"]
    if p["funcao"] == "provar":
        return 0.4, min(d - 0.4, 0.4 + 3.5)
    return 0.2, min(d - 0.2, 0.2 + 4.5)


def aprovar(rid: str) -> dict:
    """Projeto do FilmCraft com o primeiro corte (falas na ordem do roteiro, cartões no lugar das
    falas novas, b-roll do acervo por função) + um momento por parte, para seguir editando."""
    from achar import broll
    from plano import momentos
    from projetos import gerar
    from transcricao import legendar, legendas
    rot = ler(rid)
    cfg = config.carregar()
    nome = re.sub(r"[^\w-]+", "-", rot["titulo"].lower()).strip("-")[:48] or "roteiro"
    rel = os.path.join("_Roteiros", f"{rot['id'][:8]}_{nome}")
    destino = momentos._abs(rel)
    os.makedirs(destino, exist_ok=True)
    entradas = []
    for k, p in enumerate(rot["partes"]):
        if p["tipo"] == "nova":
            card = _cartao_fala_nova(p, os.path.join(destino, f"fala-nova-{k + 1:02d}.mp4"))
            p["video"] = momentos._rel(card)
            p["ini"], p["fim"] = 0.0, p["dur"]
            entradas.append({"video": card, "trechos": [(0.0, p["dur"])], "palavras": []})
            continue
        v = momentos._abs(p["video"])
        words = legendar.caminho_saida(v, ".words.json")
        ws = legendas.ler_words_json(words) if os.path.exists(words) else []
        a, b = max(0.0, p["ini"] - 0.12), p["fim"] + 0.25          # respiro nas bordas da frase
        entradas.append({"video": v, "trechos": [(a, b)], "palavras": ws})
        p["ini_corte"], p["fim_corte"] = a, b
    fmt = formatos().get(rot["formato"]) or {}
    ok, erro = gerar.gerar_de_entradas(nome, destino, entradas, rot["titulo"], fmt.get("nome") or "",
                                       logo=cfg["montagem"].get("logo") if os.path.exists(cfg["montagem"].get("logo") or "") else None,
                                       ending=cfg["montagem"].get("ending_padrao") if os.path.exists(cfg["montagem"].get("ending_padrao") or "") else None)
    if not ok:
        raise RuntimeError(erro)
    projeto = os.path.join(destino, f"{nome}.fcproj")
    # um momento por parte: a imagem escolhida já entra como b-roll aprovado (só acervo)
    for k, p in enumerate(rot["partes"]):
        ini0 = p.get("ini_corte", p["ini"]) if p["tipo"] == "fala" else 0.0
        a, b = _janela(p)
        tipo = "broll" if p["funcao"] in ("provar", "clima", "contraste") else "destaque"
        s = momentos.novo_momento(rel, p["video"], ini0 + a if p["tipo"] == "fala" else 0.0,
                                  ini0 + b if p["tipo"] == "fala" else p["dur"], tipo=tipo,
                                  texto=p.get("mostrar") or p.get("texto", "")[:60])
        escolhida = next((c for c in p.get("cobertura") or [] if c["id"] == p.get("escolhida")), None)

        def mudar(x: dict, p=p, escolhida=escolhida, k=k) -> None:
            x["motivo"] = f"roteiro · parte {k + 1} ({p.get('parte') or p['funcao']}) · função: {p['funcao']}"
            x["funcao"] = p["funcao"]
            x["parte"] = k
            x["apoio"] = p.get("por_que", "")
            x["broll"] = {"candidatos": p.get("cobertura") or [], "buscas": [p.get("mostrar") or ""],
                          "sequencia": []}
            if escolhida:
                x["broll"]["sequencia"] = [{"arquivo": escolhida["arquivo"], "tipo": escolhida["tipo"],
                                            "ini": escolhida["ini"], "dur": round(x["fim"] - x["ini"], 2)}]
                x["formato"] = "acervo"
                x["status"] = "aprovado"
        momentos._mudar_momento(rel, s["id"], mudar)
    d = momentos.ler_sugestoes(rel)
    d["itens"].sort(key=lambda x: (x.get("parte", 999), x["ini"]))
    momentos.gravar_sugestoes(rel, d)
    n = broll.inserir(rel, "projeto", momentos._rel(projeto))
    rot.update(status="aprovado", aprovado_em=_agora(), pasta=rel, projeto=momentos._rel(projeto), broll=n)
    salvar(rot)
    return rot


def exportar_md(rid: str) -> str:
    """O roteiro como texto (para mandar a quem vai gravar as falas novas)."""
    rot = ler(rid)
    fs = funcoes()
    linhas = [f"# {rot['titulo']}", "", rot.get("resumo") or "", "",
              f"Formato: {(formatos().get(rot['formato']) or {}).get('nome', rot['formato'])} · ~{rot['duracao']:.0f} s", ""]
    for k, p in enumerate(rot["partes"], 1):
        func = (fs.get(p["funcao"]) or {}).get("nome", p["funcao"])
        if p["tipo"] == "nova":
            linhas.append(f"{k}. **FALA NOVA** ({p.get('quem')}, ~{p['dur']:.0f} s) — {func}: mostrar {p.get('mostrar') or '-'}")
            linhas.append(f"   > {p['texto']}")
        else:
            linhas.append(f"{k}. {p['item'].split('/')[-1]} {p['ini']:.1f}–{p['fim']:.1f} s — {func}: mostrar {p.get('mostrar') or '-'}")
            linhas.append(f"   \"{p['texto']}\"")
    arq = os.path.join(pasta(), f"{rid}.md")
    with open(arq, "w", encoding="utf-8") as fh:
        fh.write("\n".join(linhas) + "\n")
    return arq


def _termos(t: str) -> list[str]:
    from achar import broll
    return broll._termos(t or "")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    i_ = sub.add_parser("ideias")
    i_.add_argument("tema", nargs="?", default="")
    e_ = sub.add_parser("escrever")
    e_.add_argument("tema", nargs="?", default="")
    e_.add_argument("--formato", default="")
    e_.add_argument("--duracao", type=int, default=0)
    e_.add_argument("--ideia", default="")
    a_ = sub.add_parser("aprovar")
    a_.add_argument("id")
    sub.add_parser("listar")
    a = ap.parse_args()
    if a.cmd == "ideias":
        print(json.dumps(ideias(a.tema), ensure_ascii=False, indent=1))
    elif a.cmd == "escrever":
        print(json.dumps(escrever(a.tema, a.formato, a.duracao, a.ideia), ensure_ascii=False, indent=1))
    elif a.cmd == "aprovar":
        print(json.dumps(aprovar(a.id), ensure_ascii=False, indent=1))
    else:
        for r in listar():
            print(f"{r['id']}  {r['status']:<9} {r['duracao']:>5.0f}s  {r['titulo']}")


if __name__ == "__main__":
    main()
