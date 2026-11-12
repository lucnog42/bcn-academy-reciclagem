#!/usr/bin/env python3
"""Coleção da marca: leitura dos .json do scraper (4K Stogram) e classificação por pilar.

O scraper grava um .json ao lado de cada mídia, com sufixo duplicado
("foto.webp.json"). O nome do arquivo de mídia é a chave; o json traz o resto
(legenda, data, curtidas, tipo, local, tags, coautores).
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import csv
import json
import os
import re
import statistics
from collections import Counter

from nucleo import caminhos, config  # noqa: E402

_CFG = config.carregar()
BASE = _CFG["acervo"]["raiz"]
EXTS_MIDIA = {".jpg", ".jpeg", ".webp", ".png", ".mp4", ".mov", ".m4v", ".webm"}
TRANSCRICOES = _CFG["acervo"].get("transcricoes") or os.path.join(BASE, "transcricoes")
PESO_FALA = 0.8      # fala transcrita: conteúdo rico, mas com erro de ASR

# ---------------------------------------------------------------- pilares
# Os pilares, os termos e os pesos são da MARCA (config/marcas/<marca>/pilares.toml).
# Rótulo vem da LEGENDA, não da ordem de uma lista. Cada pilar tem termos com
# peso (3 = específico do tema, 2 = contextual, 1 = fraco/ambíguo); o texto é
# lido em três zonas com multiplicadores diferentes:
#   1ª linha (gancho)  x2.0   — é onde o post diz do que trata
#   corpo              x1.0
#   hashtags           x1.2   — hashtag é rótulo declarado pelo autor
# Vence o pilar com maior evidência; a margem sobre o 2º vira `confianca`.
TERMOS: dict[str, dict[str, float]] = {k: {t: float(w) for t, w in v.items()}
                                       for k, v in _CFG["termos"].items()}
PILAR_FALLBACK = _CFG["pilares"].get("fallback") or "OUTROS"
SEM_LEGENDA = "SEM_LEGENDA"   # ausência de texto ≠ tema desconhecido
# último recurso, só quando a legenda não deu evidência suficiente
LOCAL_PILAR: dict[str, str] = dict(_CFG["local_pilar"])
EVIDENCIA_MINIMA = float(_CFG["pilares"].get("evidencia_minima") or 2.5)
# Nome da pasta que o usuário organizou à mão é curadoria humana: só entra quando
# a legenda não decidiu (OUTROS/SEM_LEGENDA), nunca por cima do texto.
# Lista ORDENADA, do mais específico ao mais genérico: vence o primeiro que casar.
PISTA_PASTA: tuple[tuple[str, str], ...] = tuple(_CFG["pista_pasta"])
# âncoras que tornam o post reaproveitável independente da data
EVERGREEN = list(_CFG["vocabulario"].get("evergreen") or [])
# tema da pasta de cortes -> pilar
TEMA_PILAR: dict[str, str] = dict(_CFG["tema_pilar"])
CORTE_PADRAO = _CFG["corte_padrao"] or PILAR_FALLBACK
PASTA_CODIGO = os.path.basename(caminhos.raiz())   # se o projeto estiver dentro do acervo, não varre


def pista_da_pasta(pasta: str) -> str:
    alvo = (pasta or "").lower()
    return next((pilar for chave, pilar in PISTA_PASTA if chave in alvo), "")


# chaves curtas precisam de fronteira de palavra: "dm" casaria dentro de
# "admin"/"admissão" e jogaria parte do acervo no pilar errado.
_RE_CHAVE: dict[str, re.Pattern] = {}


def _casar(texto: str, chave: str) -> bool:
    """Casa a chave como palavra/frase inteira. Sem isso, "direct" casaria em
    "eliminación directa", "marque" em "marcaram" e "dm" em "admissão"."""
    pad = _RE_CHAVE.get(chave)
    if pad is None:
        alvo = chave.lstrip("#")
        pad = re.compile(r"(?<!\w)" + re.escape(alvo) + r"(?!\w)")
        _RE_CHAVE[chave] = pad
    return bool(pad.search(texto))


def _zonas(legenda: str, transcricao: str = "") -> tuple[str, str, str, str]:
    """Separa gancho (1ª linha), corpo e hashtags. O gancho entra duas vezes
    no cálculo porque repete a intenção do post, não o rodapé do perfil."""
    linhas = [l.strip() for l in (legenda or "").splitlines() if l.strip()]
    gancho = linhas[0].lower() if linhas else ""
    corpo = " ".join(linhas[1:]).lower()
    tags = " ".join(re.findall(r"#\w+", (legenda or "").lower()))
    corpo = re.sub(r"#\w+", " ", corpo)
    return gancho, corpo, tags, (transcricao or "").lower()


def _rotular_base(legenda: str, local: str = "", transcricao: str = "") -> dict:
    """Rótulo principal + evidências. Retorna dict com pilar, score, confianca,
    secundarios e os termos que sustentaram a decisão."""
    gancho, corpo, tags, fala = _zonas(legenda, transcricao)
    escores: dict[str, float] = {}
    provas: dict[str, list[str]] = {}
    for pilar, termos in TERMOS.items():
        achados: list[tuple[float, str]] = []
        for termo, peso in termos.items():
            contrib = 0.0
            if _casar(gancho, termo):
                contrib += peso * 2.0
                achados.append((contrib, f"{termo}*2"))
            if termo in corpo and _casar(corpo, termo):
                contrib += peso
                achados.append((contrib, termo))
            if not termo.startswith("#") and termo in tags and _casar(tags, termo):
                contrib += peso * 1.2
                achados.append((contrib, f"#{termo}"))
            if fala and termo in fala and _casar(fala, termo):
                contrib += peso * PESO_FALA
                achados.append((contrib, f"fala:{termo}"))
        if not achados:
            continue
        # retorno decrescente: um termo forte vale mais que cinco fracos somados.
        # Sem isso, "treino" perdia para a soma de "obrigado"+"gratidão"+"experiência".
        achados.sort(key=lambda a: a[0], reverse=True)
        total = sum(c * (0.6 ** i) for i, (c, _) in enumerate(achados))
        escores[pilar] = round(total, 2)
        provas[pilar] = [nome for _, nome in achados[:5]]

    if not escores:
        l = (local or "").lower()
        vazio = not (legenda or "").strip()
        pilar = next((pl for ch, pl in LOCAL_PILAR.items() if ch in l),
                     SEM_LEGENDA if vazio else PILAR_FALLBACK)
        return {"pilar": pilar, "score": 0.0, "confianca": 0.0,
                "secundarios": "",
                "evidencias": "local" if pilar not in (PILAR_FALLBACK, SEM_LEGENDA) else ""}

    ranking = sorted(escores.items(), key=lambda kv: kv[1], reverse=True)
    pilar, score = ranking[0]
    if score < EVIDENCIA_MINIMA:      # legenda fraca (só um placar, uma sigla)
        l = (local or "").lower()
        por_local = next((pl for ch, pl in LOCAL_PILAR.items() if ch in l), None)
        if por_local:
            return {"pilar": por_local, "score": score, "confianca": 0.0,
                    "secundarios": pilar, "evidencias": "local"}
        return {"pilar": PILAR_FALLBACK, "score": score, "confianca": 0.0,
                "secundarios": pilar, "evidencias": ",".join(provas[pilar])}
    segundo = ranking[1][1] if len(ranking) > 1 else 0.0
    confianca = round(score / (score + segundo), 2) if score else 0.0
    secundarios = " ".join(p for p, s in ranking[1:] if s >= 0.4 * score)
    return {"pilar": pilar, "score": score, "confianca": confianca,
            "secundarios": secundarios, "evidencias": ",".join(provas[pilar])}


FALA_MINIMA = 4.0    # fala sozinha precisa de evidência clara: letra de música
                     # transcrita pelo Whisper casava termos por acidente


def _pontuar_fala(transcricao: str) -> tuple[str, float, str]:
    """Pilar sugerido só pela fala transcrita. Retorna (pilar, score, evidências)."""
    fala = (transcricao or "").lower()
    if not fala:
        return "", 0.0, ""
    escores, provas = {}, {}
    for pilar, termos in TERMOS.items():
        achados = [(peso * PESO_FALA, f"fala:{termo}")
                   for termo, peso in termos.items()
                   if termo in fala and _casar(fala, termo)]
        if not achados:
            continue
        achados.sort(key=lambda a: a[0], reverse=True)
        escores[pilar] = round(sum(c * (0.6 ** i) for i, (c, _) in enumerate(achados)), 2)
        provas[pilar] = [n for _, n in achados[:4]]
    if not escores:
        return "", 0.0, ""
    pilar = max(escores, key=escores.get)
    return pilar, escores[pilar], ",".join(provas[pilar])


def rotular(legenda: str, local: str = "", pasta: str = "", transcricao: str = "") -> dict:
    """Rótulo pela legenda; depois pela fala transcrita; pasta só como último recurso."""
    r = _rotular_base(legenda, local)
    if r["pilar"] in (PILAR_FALLBACK, SEM_LEGENDA):
        pilar_fala, score_fala, ev_fala = _pontuar_fala(transcricao)
        if pilar_fala and score_fala >= FALA_MINIMA:
            return {"pilar": pilar_fala, "score": score_fala,
                    "confianca": round(min(0.9, score_fala / (FALA_MINIMA * 2)), 2),
                    "secundarios": "", "evidencias": ev_fala,
                    "resgatado_por": "fala"}
        pista = pista_da_pasta(pasta)
        if pista:
            r = {**r, "pilar": pista, "confianca": 0.35,
                 "evidencias": f"pasta:{pasta}", "resgatado_por": "pasta"}
        return r
    # fala que confirma o rótulo da legenda vale confiança extra e fica na trilha
    pilar_fala, score_fala, ev_fala = _pontuar_fala(transcricao)
    if pilar_fala and score_fala >= FALA_MINIMA:
        if pilar_fala == r["pilar"]:
            r = {**r, "confianca": min(0.95, round(r["confianca"] + 0.15, 2)),
                 "evidencias": ", ".join(x for x in (r["evidencias"], ev_fala) if x),
                 "resgatado_por": "fala+legenda"}
        elif r["confianca"] < 0.45:
            # legenda ambígua + fala clara: quem manda é o que a pessoa diz
            r = {**r, "pilar": pilar_fala, "confianca": round(min(0.8, score_fala / 8), 2),
                 "evidencias": ev_fala, "resgatado_por": "fala (legenda ambigua)",
                 "secundarios": (r["pilar"] + " " + r["secundarios"]).strip()}
        elif r["confianca"] < 0.6:
            r = {**r, "secundarios": (r["secundarios"] + " " + pilar_fala).strip()}
    return r


def classificar(texto: str, local: str = "", pasta: str = "") -> str:
    return rotular(texto, local, pasta)["pilar"]


def classificar_prioridade(texto: str, local: str = "") -> str:
    """Método antigo (primeiro pilar da lista que casar). Mantido só para
    comparar quanto o rótulo por legenda mudou o resultado."""
    t = (texto or "").lower()
    for pilar, termos in TERMOS.items():
        if any(_casar(t, k) for k in termos):
            return pilar
    l = (local or "").lower()
    for chave, pilar in LOCAL_PILAR.items():
        if chave in l:
            return pilar
    return PILAR_FALLBACK


def formato(w, h) -> str:
    try:
        w, h = int(w), int(h)
    except (TypeError, ValueError):
        return "?"
    if not w or not h:
        return "?"
    r = w / h
    if abs(r - 1) < 0.03:
        return "1:1"
    if abs(r - 0.8) < 0.03:
        return "4:5"
    if abs(r - 9 / 16) < 0.04:
        return "9:16"
    if abs(r - 16 / 9) < 0.04:
        return "16:9"
    return f"{w}x{h}"


def hashtags(texto: str) -> str:
    return " ".join("#" + h.lower() for h in sorted({h.lower() for h in re.findall(r"#(\w+)", texto or "")}))


def primeiro_gancho(texto: str, limite: int = 110) -> str:
    for linha in (texto or "").splitlines():
        linha = linha.strip()
        if len(linha) > 3:
            return linha[:limite]
    return ""


def ler_json(caminho: str) -> dict | None:
    try:
        with open(caminho, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


_TRANS_CACHE: dict[str, str] | None = None


def carregar_transcricoes(base: str = BASE) -> dict[str, str]:
    """Mapa caminho_relativo_do_video -> transcrição.

    A pasta `transcricoes/` espelha a estrutura do acervo com .txt e .srt
    (`transcricoes/_posts/<ano>/<post>/videos/01.txt`).
    """
    global _TRANS_CACHE
    if _TRANS_CACHE is not None:
        return _TRANS_CACHE
    _TRANS_CACHE = {}
    raiz = TRANSCRICOES if base == BASE else os.path.join(base, os.path.basename(TRANSCRICOES))
    if not os.path.isdir(raiz):
        return _TRANS_CACHE
    for dir_atual, _dirs, arquivos in os.walk(raiz):
        for nome in arquivos:
            if not nome.endswith(".txt"):
                continue
            cam = os.path.join(dir_atual, nome)
            rel = os.path.relpath(cam, raiz)
            video = os.path.splitext(rel)[0] + ".mp4"
            try:
                with open(cam, encoding="utf-8") as fh:
                    texto = " ".join(fh.read().split())
            except Exception:
                continue
            if len(texto) >= 20:
                _TRANS_CACHE[video] = texto
    return _TRANS_CACHE


def _resumo_fala(texto: str, limite: int = 400) -> str:
    if len(texto) <= limite:
        return texto
    corte = texto[:limite]
    return corte[:corte.rfind(" ")] + " [...]"


_HIST_CACHE: dict[str, str] | None = None


def _historico_pastas() -> dict[str, str]:
    """destino -> pasta de origem, lido de movimentos.csv (log das organizações)."""
    global _HIST_CACHE
    if _HIST_CACHE is not None:
        return _HIST_CACHE
    _HIST_CACHE = {}
    caminho = caminhos.dados("historico", "movimentos.csv")
    if not os.path.exists(caminho):
        return _HIST_CACHE
    try:
        with open(caminho, encoding="utf-8") as fh:
            for linha in csv.DictReader(fh):
                origem, destino = linha.get("origem", ""), linha.get("destino", "")
                pasta = os.path.dirname(origem)
                if pasta and destino:
                    _HIST_CACHE[destino] = pasta
    except Exception:
        pass
    return _HIST_CACHE


def _entrada(d: dict, arquivo_rel: str, pasta_rel: str, num: int, total: int,
             organizado: bool, caminho: str) -> dict:
    """Monta o registro de uma mídia a partir do json do scraper."""
    try:
        tamanho = os.path.getsize(caminho)
    except OSError:
        tamanho = 0
    return {
        "arquivo": arquivo_rel,
        "pasta": pasta_rel,
        "organizado": organizado,
        # extensão do próprio arquivo: numa pasta organizada o post.json é um
        # só para o carrossel inteiro e a "extension" dele é a da 1ª mídia
        "ext": (os.path.splitext(arquivo_rel)[1].lstrip(".") or d.get("extension") or "").lower(),
        "bytes": tamanho,
        "post_id": str(d.get("post_id") or ""),
        "post_shortcode": d.get("post_shortcode") or "",
        "media_shortcode": d.get("shortcode") or "",
        "url": d.get("post_url") or "",
        "tipo": d.get("type") or "",
        "num": num,
        "total_midias": total,
        "data": (d.get("post_date") or d.get("date") or "")[:19],
        "curtidas": int(d.get("likes") or 0),
        "local": d.get("location_name") or "",
        "local_slug": d.get("location_slug") or "",
        "dono": d.get("username") or "",
        "audio": d.get("audio_title") or "",
        "w": d.get("width") or 0,
        "h": d.get("height") or 0,
        "legenda": d.get("description") or "",
        "tags": " ".join(t.get("username", "") for t in (d.get("tagged_users") or [])
                         if isinstance(t, dict)),
        "coautores": " ".join(c.get("username", "") for c in (d.get("coauthors") or [])
                              if isinstance(c, dict)),
        "fixado": bool(d.get("pinned")),
    }


def coletar(base: str = BASE, ignorar: tuple[str, ...] = ("_reciclagem", "transcricoes", "motion", "saidas")):
    """Varre a árvore e devolve (midias, orfaos, quebrados).

    Entende as duas estruturas:
      * organizada — pasta de post com `post.json` + `imagens/` e `videos/`
        (um json serve todas as mídias do carrossel);
      * crua — `<midia>.<ext>.json` ao lado da mídia, na raiz ou em subpasta.
    """
    midias, quebrados, vistos = [], [], set()
    for raiz, dirs, arquivos in os.walk(base):
        dirs[:] = [d for d in dirs if d not in ignorar]
        if "post.json" in arquivos and os.path.basename(raiz) not in ("_reciclagem", PASTA_CODIGO):
            d = ler_json(os.path.join(raiz, "post.json"))
            if d is None:
                quebrados.append({"json": os.path.relpath(raiz, base), "motivo": "post.json ilegivel"})
            else:
                lista = []
                for sub in ("imagens", "videos"):
                    dir_sub = os.path.join(raiz, sub)
                    if not os.path.isdir(dir_sub):
                        continue
                    lista += [(os.path.join(sub, n), n)
                              for n in sorted(os.listdir(dir_sub))
                              if os.path.splitext(n)[1].lower() in EXTS_MIDIA
                              and not eh_derivado(os.path.join(dir_sub, n))]
                for i, (rel, _nome) in enumerate(lista, 1):
                    caminho = os.path.join(raiz, rel)
                    vistos.add(os.path.abspath(caminho))
                    midias.append(_entrada(d, os.path.relpath(caminho, base), "", i,
                                           len(lista), True, caminho))
            dirs[:] = []          # pasta de post já resolvida: não descer de novo
            continue
        for nome in arquivos:
            if not nome.endswith(".json"):
                continue
            cam_json = os.path.join(raiz, nome)
            cam_midia = cam_json[:-5]
            d = ler_json(cam_json)
            if d is None:
                quebrados.append({"json": os.path.relpath(cam_json, base), "motivo": "json ilegivel"})
                continue
            if not os.path.exists(cam_midia):
                quebrados.append({"json": os.path.relpath(cam_json, base), "motivo": "midia ausente"})
                continue
            vistos.add(os.path.abspath(cam_midia))
            pasta_rel = os.path.relpath(raiz, base) if raiz != base else ""
            midias.append(_entrada(d, os.path.relpath(cam_midia, base), pasta_rel,
                                   int(d.get("num") or 1), int(d.get("count") or 1),
                                   False, cam_midia))

    orfaos = []
    for raiz, dirs, arquivos in os.walk(base):
        dirs[:] = [d for d in dirs if d not in ignorar]
        dirs[:] = [d for d in dirs if d not in PASTAS_IGNORADAS]
        for nome in arquivos:
            if os.path.splitext(nome)[1].lower() not in EXTS_MIDIA:
                continue
            cam = os.path.join(raiz, nome)
            if eh_derivado(cam):
                continue
            if os.path.abspath(cam) not in vistos:
                orfaos.append(os.path.relpath(cam, base))

    historico = _historico_pastas()
    falas = carregar_transcricoes(base)
    for m in midias:
        # pasta que a mídia tinha antes da fusão: curadoria humana que não se
        # perde, mesmo com a pasta já desmontada
        anterior = historico.get(m["arquivo"], "")
        m["transcricao"] = falas.get(os.path.splitext(m["arquivo"])[0] + ".mp4", "")
        m["fala"] = _resumo_fala(m["transcricao"])
        r = rotular(m["legenda"], m["local"], m["pasta"] or anterior, m["transcricao"])
        m["pilar"] = r["pilar"]
        m["confianca"] = r["confianca"]
        m["pilar_secundario"] = r["secundarios"]
        m["evidencias"] = r["evidencias"]
        m["resgatado_por"] = r.get("resgatado_por", "")
        m["formato"] = formato(m["w"], m["h"])
        m["ano"] = m["data"][:4]
        m["hashtags"] = hashtags(m["legenda"])
        m["gancho"] = primeiro_gancho(m["legenda"])
    return midias, orfaos, quebrados


ESTADOS = caminhos.dados("marcacoes", "estados.json")


def carregar_estados() -> dict[str, dict]:
    """{"<pasta do post>": {"nao_interessante": bool, "repostado": bool, "quando": iso}}"""
    if not os.path.exists(ESTADOS):
        return {}
    try:
        with open(ESTADOS, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def salvar_estados(dados: dict[str, dict]) -> None:
    tmp = ESTADOS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dados, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, ESTADOS)


CORTES = _CFG["acervo"].get("cortes") or os.path.join(BASE, "_Cortes")


def _duracao_srt(caminho: str) -> float:
    """Último fim de cue do .srt — aproxima a duração do corte sem decodificar."""
    try:
        with open(caminho, encoding="utf-8", errors="replace") as fh:
            marcas = re.findall(r"-->\s*(\d\d):(\d\d):(\d\d)[,.](\d{3})", fh.read())
    except OSError:
        return 0.0
    if not marcas:
        return 0.0
    h, m, s, ms = marcas[-1]
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


# o que os plugins e o FilmCraft gravam ao lado do material não é material novo
SUFIXOS_DERIVADOS = ("_norm", "_sem_silencio", "_cortado")
PASTAS_IGNORADAS = {"saidas", "Auto-Save", "quadros", "projetos_antigos"}


def eh_derivado(caminho: str) -> bool:
    """Vídeo gerado a partir de outro (plugin ou render do FilmCraft), não um corte novo:
    `x_norm.mp4`, `x_sem_silencio.mp4`, `x_cortado.mp4`, ou o render com o nome de um
    `.fcproj` da mesma pasta."""
    pasta, nome = os.path.split(caminho)
    raiz = os.path.splitext(nome)[0]
    if any(raiz.endswith(s) or f"{s}_" in raiz for s in SUFIXOS_DERIVADOS):
        return True
    if os.path.basename(pasta) in PASTAS_IGNORADAS:
        return True
    return os.path.exists(os.path.join(pasta, raiz + ".fcproj"))


def coletar_cortes(base: str = BASE) -> list[dict]:
    """Cortes: `_Cortes/<tema>/[subpasta/]<corte>.mp4` com `.srt` e `.txt` ao lado.
    Um item por vídeo (para o catálogo); o painel junta por pasta com `agrupar_cortes`."""
    raiz = CORTES if base == BASE else os.path.join(base, os.path.basename(CORTES))
    cortes = []
    if not os.path.isdir(raiz):
        return cortes
    for dir_atual, dirs, arquivos in os.walk(raiz):
        dirs[:] = sorted(d for d in dirs if d not in PASTAS_IGNORADAS)
        for nome in sorted(arquivos):
            if not nome.lower().endswith(".mp4"):
                continue
            cam = os.path.join(dir_atual, nome)
            if eh_derivado(cam):
                continue
            base_cam = os.path.splitext(cam)[0]
            tema_rel = os.path.relpath(dir_atual, raiz)
            tema = tema_rel.split(os.sep)[0]
            txt = base_cam + ".txt"
            fala = ""
            if os.path.exists(txt):
                try:
                    fala = " ".join(open(txt, encoding="utf-8", errors="replace").read().split())
                except OSError:
                    fala = ""
            pilar = next((p for chave, p in TEMA_PILAR.items() if chave in tema.lower()), "")
            if not pilar:
                # corte de entrevista: tema é o nome da pessoa, o rótulo vem da fala
                pilar = rotular(fala)["pilar"]
                if pilar in (PILAR_FALLBACK, SEM_LEGENDA):
                    pilar = CORTE_PADRAO
            partes = tema_rel.split(os.sep)
            cortes.append({
                "arquivo": os.path.relpath(cam, base).replace(os.sep, "/"),
                "tema": tema + (f" {'/'.join(partes[1:])}" if len(partes) > 1 else ""),
                "pilar": pilar,
                "segundos": round(_duracao_srt(base_cam + ".srt"), 1),
                "fala": fala,
                "gancho": primeiro_gancho(fala, 110),
                "bytes": os.path.getsize(cam),
                "tem_srt": os.path.exists(base_cam + ".srt"),
            })
    cortes.sort(key=lambda c: (c["tema"], c["arquivo"]))
    return cortes


def nome_da_pasta_de_cortes(pasta_rel: str) -> str:
    """`_Cortes/depoimentos hotel/27` -> `depoimentos-hotel_27` (nome do projeto)."""
    partes = pasta_rel.replace(os.sep, "/").split("/")
    if partes and partes[0] == os.path.basename(CORTES):
        partes = partes[1:]
    return "_".join(p.strip().replace(" ", "-") for p in partes if p) or "cortes"


def agrupar_cortes(cortes: list[dict]) -> list[dict]:
    """Uma pasta de `_Cortes` = um projeto: os vídeos dela, em ordem, numa timeline só."""
    por_pasta: dict[str, list[dict]] = {}
    for c in cortes:
        por_pasta.setdefault(c["arquivo"].rsplit("/", 1)[0], []).append(c)
    grupos = []
    for pasta, cs in por_pasta.items():
        cs = sorted(cs, key=lambda c: c["arquivo"])
        pilares = [c["pilar"] for c in cs]
        falas = [c["fala"] for c in cs if c["fala"]]
        grupos.append({
            "pasta": pasta,
            "nome": nome_da_pasta_de_cortes(pasta),
            "videos": [c["arquivo"] for c in cs],
            "tema": cs[0]["tema"],
            "pilar": max(set(pilares), key=pilares.count),
            "segundos": round(sum(c["segundos"] for c in cs), 1),
            "fala": " · ".join(falas),
            "gancho": next((c["gancho"] for c in cs if c["gancho"]), ""),
            "bytes": sum(c["bytes"] for c in cs),
            "tem_srt": all(c["tem_srt"] for c in cs),
        })
    grupos.sort(key=lambda g: (g["tema"], g["pasta"]))
    return grupos


def _pasta_de(m: dict) -> str:
    """Pasta do post: a manual, ou a pasta que contém imagens/ e videos/."""
    if m["pasta"]:
        return m["pasta"]
    partes = m["arquivo"].split(os.sep)
    if "imagens" in partes or "videos" in partes:
        return os.sep.join(partes[:-2])
    return ""


def agrupar_posts(midias: list[dict]) -> list[dict]:
    """Agrupa mídias de carrossel/foto múltipla em um registro por post."""
    grupos: dict[str, list[dict]] = {}
    for m in midias:
        grupos.setdefault(m["post_id"] or m["arquivo"], []).append(m)
    posts = []
    for pid, itens in grupos.items():
        itens.sort(key=lambda m: m["num"])
        p = dict(itens[0])
        p["n_midias"] = len(itens)
        p["midias"] = [m["arquivo"] for m in itens]
        p["formatos"] = " ".join(sorted({m["formato"] for m in itens}))
        p["exts"] = " ".join(sorted({m["ext"] for m in itens}))
        p["bytes"] = sum(m["bytes"] for m in itens)
        p["pilares"] = " ".join(sorted({m["pilar"] for m in itens}))
        p["pastas"] = " | ".join(sorted({_pasta_de(m) for m in itens} - {""}))
        # pilar do post: se a mídia de capa não decidiu, aproveita a que decidiu
        if p["pilar"] in (PILAR_FALLBACK, SEM_LEGENDA):
            candidatos = [m for m in itens if m["pilar"] not in (PILAR_FALLBACK, SEM_LEGENDA)]
            if candidatos:
                melhor = max(candidatos, key=lambda m: m["confianca"])
                p["pilar"] = melhor["pilar"]
                p["confianca"] = melhor["confianca"]
                p["evidencias"] = melhor["evidencias"]
        p["falas"] = [m["fala"] for m in itens if m.get("fala")]
        p["fala"] = max(p["falas"], key=len) if p["falas"] else ""
        p["tem_fala"] = bool(p["falas"])
        p["tem_video"] = any(m["ext"] == "mp4" for m in itens)
        p["tem_imagem"] = any(m["ext"] in ("jpg", "jpeg", "webp", "png") for m in itens)
        posts.append(p)
    posts.sort(key=lambda p: p["data"])
    return posts


# pesos do score de reciclagem (usados por reciclagem.py e pelo painel)
PESOS = {"alcance": 35, "evergreen": 20, "material": 20, "maturidade": 25,
         "penal_recente": -25, "penal_repetido": -20}
FAIXAS_MATURIDADE = ((1095, 25), (730, 20), (365, 14), (180, 7), (0, 0))


def pontuar(posts: list[dict], hoje=None) -> list[dict]:
    """Score de reciclagem 0-100 + os componentes que o explicam."""
    import datetime as _dt
    hoje = hoje or _dt.date.today()
    if not posts:
        return []
    ordenado = sorted(p["curtidas"] for p in posts)
    total, mediana = len(ordenado), max(statistics.median(ordenado), 1)
    for p in posts:
        pct = (ordenado.index(p["curtidas"]) + 0.5) / total
        idade = (hoje - _dt.date.fromisoformat(p["data"][:10])).days if p["data"] else 999
        alcance = PESOS["alcance"] * pct
        ever = PESOS["evergreen"] * min(1.0, sum((p["legenda"] or "").lower().count(k)
                                                 for k in EVERGREEN) / 3)
        material = min(PESOS["material"], 4 * p["n_midias"] + (8 if p["tem_video"] else 0))
        maturidade = next(v for limite, v in FAIXAS_MATURIDADE if idade >= limite)
        penal = PESOS["penal_recente"] if idade < 150 else 0
        if p.get("repetido", 1) > 1 and not p.get("melhor_do_grupo", True):
            penal += PESOS["penal_repetido"]
        p["score"] = round(alcance + ever + material + maturidade + penal, 1)
        p["idade_dias"] = idade
        p["percentil"] = round(pct * 100)
        p["vs_mediana"] = round(p["curtidas"] / mediana, 2)
        p["score_partes"] = {"alcance": round(alcance, 1), "evergreen": round(ever, 1),
                             "material": material, "maturidade": maturidade,
                             "penal": penal}
    return sorted(posts, key=lambda p: p["score"], reverse=True)


def marcar_repetidos(posts: list[dict]) -> list[dict]:
    """Marca posts que repetem a legenda de outro post. O perfil já reciclou esse
    material internamente — reaproveitar de novo é republicar pela terceira vez.
    Guarda também qual do grupo teve melhor desempenho, que é o que vale usar."""
    grupos: dict[str, list[dict]] = {}
    for p in posts:
        chave = re.sub(r"\s+", " ", (p["legenda"] or "").strip().lower())
        p["repetido"] = 1
        p["melhor_do_grupo"] = True
        if chave:
            grupos.setdefault(chave, []).append(p)
    for itens in grupos.values():
        if len(itens) < 2:
            continue
        melhor = max(itens, key=lambda p: p["curtidas"])
        for p in itens:
            p["repetido"] = len(itens)
            p["melhor_do_grupo"] = p is melhor
    return posts


def resumo(midias, orfaos, quebrados) -> str:
    posts = agrupar_posts(midias)
    c = Counter(m["pilar"] for m in midias)
    anos = Counter(m["ano"] for m in midias)
    gb = sum(m["bytes"] for m in midias) / 1e9
    linhas = [
        f"midias indexadas : {len(midias)}",
        f"posts unicos     : {len(posts)}",
        f"orfaos (sem json): {len(orfaos)}",
        f"quebrados        : {len(quebrados)}",
        f"tamanho total    : {gb:.1f} GB",
        f"periodo          : {min(anos)} .. {max(anos)}",
        "",
        "por pilar:",
    ]
    linhas += [f"  {k:<12} {v:>5}" for k, v in c.most_common()]
    linhas += ["", "por ano:"] + [f"  {k} {v:>5}" for k, v in sorted(anos.items())]
    return "\n".join(linhas)


if __name__ == "__main__":
    print(resumo(*coletar()))
