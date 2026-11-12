#!/usr/bin/env python3
"""Ponte entre o app (Rune) e o motor Python — uma linha JSON por mensagem.

    python3 src/painel/api.py serve                 # stdin/stdout, para o app
    python3 src/painel/api.py chamar posts          # uma chamada, imprime o JSON
    python3 src/painel/api.py chamar marcar '{"post": "...", "repostado": true}'

Pedido   {"id": 7, "metodo": "posts", "dados": {}}
Resposta {"id": 7, "ok": true, "resultado": ...}   |  {"id": 7, "ok": false, "erro": "..."}
Evento   {"evento": "tarefa", "tarefa": "t3", "linha": "..."}            (saída do processo)
         {"evento": "tarefa", "tarefa": "t3", "fim": true, "ok": true, "codigo": 0}

Cada pedido roda numa thread, então um `gerar` demorado não trava o `ping`.
Tarefas longas (gerar projeto, plugins) devolvem na hora o id da tarefa e
mandam a saída linha a linha como evento. Nada aqui apaga arquivo.
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import datetime as dt
import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import traceback
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from nucleo import caminhos  # noqa: E402
from acervo import colecao  # noqa: E402
from nucleo import config  # noqa: E402
from transcricao import legendas  # noqa: E402
from acervo import midia  # noqa: E402

BASE = colecao.BASE
RAIZ = caminhos.raiz()
SRC = caminhos.raiz("src")
VERSAO = "2"
PLUGINS = caminhos.raiz("plugins")

# o que um plugin (ou o app) pode rodar pela fila; python só scripts do projeto (src/, plugins/)
PERMITIDOS = {"ffmpeg", "ffprobe", "filmcraft-cli", "photocraft-cli", "python3"}

_SAIDA = threading.Lock()
_TAREFAS: dict[str, subprocess.Popen] = {}
_TRAVA_ESTADOS = threading.Lock()
_CACHE: dict[str, object] = {}
_contador = 0


def emitir(msg: dict) -> None:
    linha = json.dumps(msg, ensure_ascii=False)
    with _SAIDA:
        sys.stdout.write(linha + "\n")
        sys.stdout.flush()


def _novo_id() -> str:
    global _contador
    with _SAIDA:
        _contador += 1
        return f"t{_contador}"


def _raizes_permitidas() -> list[str]:
    """Onde o app pode ler/abrir: o acervo, os dados da marca e as fontes de b-roll ativas."""
    r = [BASE, caminhos.dados()]
    for f in config.carregar().get("fontes") or []:
        if f.get("raiz") and f.get("ativo", True):
            r.append(os.path.expanduser(f["raiz"]))
    return [os.path.realpath(x) for x in r if x]


def _abs(rel: str) -> str:
    """Caminho relativo ao acervo, ou absoluto dentro de uma raiz permitida."""
    alvo = os.path.realpath(os.path.join(BASE, os.path.expanduser(rel)))
    for raiz in _raizes_permitidas():
        if alvo == raiz or alvo.startswith(raiz + os.sep):
            return alvo
    raise ValueError(f"fora do acervo: {rel}")


def _script(rel: str) -> str:
    """Script python do projeto: `src/...` ou `plugins/...` (relativo à raiz do projeto)."""
    alvo = os.path.realpath(os.path.join(RAIZ, rel))
    if not (alvo.startswith(os.path.realpath(SRC) + os.sep) or alvo.startswith(os.path.realpath(PLUGINS) + os.sep)):
        raise ValueError("python3 só roda scripts do projeto (src/ ou plugins/)")
    return alvo


# ------------------------------------------------------------------ dados
def _info_chave() -> dict:
    from nucleo import ia
    return ia.info()


def m_ping(_):
    cfg = config.carregar()
    return {"versao": VERSAO, "base": BASE, "raiz": RAIZ, "plugins": PLUGINS,
            "marca": caminhos.marca(), "marcas": caminhos.marcas(), "nome_marca": cfg["marca"].get("nome", ""),
            "pilares": list(cfg["pilares"].get("ordem") or []), **_info_chave()}


def m_trocar_marca(d):
    """Troca a marca ativa (config/marca-ativa). O app reinicia o motor em seguida."""
    m = str(d.get("marca") or "").strip()
    if m not in caminhos.marcas():
        raise ValueError(f"marca desconhecida: {m}")
    with open(caminhos.raiz("config", "marca-ativa"), "w", encoding="utf-8") as fh:
        fh.write(m + "\n")
    return {"marca": m}


def m_chave(d):
    """Escolhe a IA (provedor, modelo, endereço) e/ou grava a chave dela ("" tira), e confere
    se funciona. A chave nunca volta."""
    from nucleo import ia
    if d.get("so_chave"):
        # só guarda uma chave (ex.: a do vídeo), sem trocar a IA das sugestões
        config.salvar_chave(d.get("chave") or "", d["so_chave"])
        return {**ia.testar(), "so_chave": d["so_chave"]}
    if d.get("provedor"):
        config.salvar_ia(d["provedor"], d.get("modelo") or "", d.get("base_url") or "")
    if "chave" in d and (d.get("chave") or d.get("remover")):
        config.salvar_chave(d.get("chave") or "", d.get("provedor"))
    return ia.testar()


def m_chave_testar(_):
    """Uma consulta sem custo para ver se o endereço e a chave da IA escolhida valem."""
    from nucleo import ia
    return ia.testar()

def m_config(_):
    return config.carregar()


def _lista_com_cache(nome: str, montar, recarregar: bool):
    """Posts e cortes abrem na hora a partir do cache em disco da última vez; a lista
    fresca é montada em segundo plano e, se mudou, o app recebe `posts_atualizados`."""
    arq = os.path.join(midia.cache_dir("listas"), f"{nome}.json")
    if recarregar or not os.path.exists(arq):
        dados = montar()
        _gravar_json(arq, dados)
        _CACHE[nome] = dados
        return dados
    if nome not in _CACHE:
        with open(arq, encoding="utf-8") as fh:
            _CACHE[nome] = json.load(fh)

        def atualizar():
            novo = montar()
            if novo != _CACHE.get(nome):
                _gravar_json(arq, novo)
                _CACHE[nome] = novo
                emitir({"evento": "posts_atualizados", "lista": nome})
        threading.Thread(target=atualizar, daemon=True).start()
    return _CACHE[nome]


def _gravar_json(arq: str, dados) -> None:
    tmp = arq + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dados, fh, ensure_ascii=False)
    os.replace(tmp, arq)


def m_posts(d):
    from acervo import listas
    return _lista_com_cache("posts", listas.montar_dados, bool(d.get("recarregar")))


def m_cortes(d):
    from acervo import listas
    return _lista_com_cache("cortes", listas.montar_cortes, bool(d.get("recarregar")))


def m_estados(_):
    return colecao.carregar_estados()


def m_marcar(d):
    post = str(d.get("post") or "")
    if not post:
        raise ValueError("post vazio")
    with _TRAVA_ESTADOS:
        estados = colecao.carregar_estados()
        atual = estados.setdefault(post, {})
        for campo in ("nao_interessante", "repostado"):
            if campo in d:
                atual[campo] = bool(d[campo])
        if not any(atual.get(c) for c in ("nao_interessante", "repostado")):
            estados.pop(post, None)
        else:
            atual["quando"] = dt.datetime.now().isoformat(timespec="seconds")
        colecao.salvar_estados(estados)
    return estados


# ------------------------------------------------------------------ mídia
def m_info(d):
    return midia.info(_abs(d["arquivo"]))


def m_miniatura(d):
    return midia.miniatura(_abs(d["arquivo"]), d.get("px"), d.get("t"))


def m_tira(d):
    return midia.tira(_abs(d["arquivo"]), int(d.get("n", 12)), int(d.get("px", 240)))


def m_quadros(d):
    return midia.quadros(_abs(d["arquivo"]), int(d.get("n", 16)), int(d.get("px", 720)))


def m_exportar_quadro(d):
    caminho = midia.exportar_quadro(_abs(d["arquivo"]), float(d.get("t", 0)))
    return {"arquivo": caminho, "relativo": os.path.relpath(caminho, BASE)}


def m_abrir(d):
    """Abre um projeto (.fcproj no FilmCraft, .pcraft no PhotoCraft) ou uma pasta."""
    alvo = _abs(d["arquivo"])
    if not os.path.exists(alvo):
        raise ValueError(f"não existe: {d['arquivo']}")
    ext = os.path.splitext(alvo)[1].lower()
    apps = {".fcproj": ["filmcraft"], ".pcraft": ["photocraft"]}.get(ext, [])
    import shutil as _sh
    for app in apps + ["xdg-open"]:
        if _sh.which(app):
            subprocess.Popen([app, alvo], cwd=BASE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return {"com": app, "arquivo": alvo}
    raise RuntimeError("não achei o FilmCraft/PhotoCraft nem o xdg-open")


def m_palavras(d):
    """Palavras com tempo (já refinadas pela voz) do vídeo, se transcrito."""
    from transcricao import legendar
    video = _abs(d["video"])
    w = legendar.caminho_saida(video, ".words.json")
    return legendas.ler_words_json(w) if os.path.exists(w) else []


def m_legendas(d):
    from transcricao import legendar
    return legendas.ler_srt(legendar.caminho_saida(_abs(d["video"]), ".srt"))


# ---------------------------------------------------------------- tarefas
def _rodar(tid: str, cmd: list[str], dono: str, ao_fim=None) -> None:
    emitir({"evento": "tarefa", "tarefa": tid, "inicio": True, "dono": dono,
            "comando": " ".join(shlex.quote(c) for c in cmd)})
    try:
        p = subprocess.Popen(cmd, cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    except OSError as e:
        emitir({"evento": "tarefa", "tarefa": tid, "fim": True, "ok": False, "codigo": -1,
                "linha": f"não deu para rodar {cmd[0]}: {e}"})
        return
    _TAREFAS[tid] = p
    for linha in p.stdout:
        emitir({"evento": "tarefa", "tarefa": tid, "linha": linha.rstrip("\n")})
    codigo = p.wait()
    _TAREFAS.pop(tid, None)
    extra = {}
    if ao_fim:
        try:
            extra = ao_fim(codigo) or {}
        except Exception as e:                  # pragma: no cover
            extra = {"erro_pos": str(e)}
    emitir({"evento": "tarefa", "tarefa": tid, "fim": True, "ok": codigo == 0,
            "codigo": codigo, **extra})


def _iniciar(cmd: list[str], dono: str, ao_fim=None) -> dict:
    tid = _novo_id()
    threading.Thread(target=_rodar, args=(tid, cmd, dono, ao_fim), daemon=True).start()
    return {"tarefa": tid, "comando": " ".join(shlex.quote(c) for c in cmd)}


def m_gerar(d):
    """Gera os projetos dos posts (ou cortes) escolhidos, como tarefa."""
    itens = [str(p) for p in (d.get("posts") or d.get("cortes") or [])]
    if not itens:
        raise ValueError("nada selecionado")
    py = sys.executable
    script = os.path.join(SRC, "projetos", "gerar.py")
    if d.get("cortes"):
        cmd = [py, script, "--tipo", "corte", "--aplicar"]
        for c in itens:
            cmd += ["--corte", c]
    else:
        fh = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump({"posts": itens}, fh, ensure_ascii=False)
        fh.close()
        cmd = [py, script, "--selecao", fh.name, "--aplicar"]
    if d.get("linked", True):
        cmd.append("--linked")
    if d.get("forcar"):
        cmd.append("--forcar")

    def fim(_codigo):
        _CACHE.pop("posts", None)
        _CACHE.pop("cortes", None)
        return {"recarregar": True}
    return _iniciar(cmd, "gerar", fim)


def m_processo(d):
    """Roda um comando da lista permitida na fila (é o que os plugins usam)."""
    cmd = [str(c) for c in d.get("cmd") or []]
    if not cmd or os.path.basename(cmd[0]) not in PERMITIDOS:
        raise ValueError(f"comando não permitido: {cmd[:1]} (permitidos: {sorted(PERMITIDOS)})")
    if os.path.basename(cmd[0]) == "python3":
        if len(cmd) < 2:
            raise ValueError("python3 precisa de um script")
        cmd = [sys.executable, _script(cmd[1]), *cmd[2:]]
    return _iniciar(cmd, str(d.get("dono") or "plugin"))


def m_cancelar(d):
    p = _TAREFAS.get(str(d.get("tarefa")))
    if p:
        p.terminate()
    return {"cancelada": bool(p)}


# ------------------------------------------------------------------ claude
def m_claude(d):
    """Uma mensagem para a IA escolhida (Claude ou outra). A chave nunca sai daqui."""
    from nucleo import ia
    texto = ia.conversar([{"type": "text", "text": d["prompt"]}], d.get("sistema") or "",
                         int(d.get("max_tokens") or config.carregar()["claude"]["max_tokens"]))
    if d.get("json"):
        posicoes = [i for i in (texto.find("{"), texto.find("[")) if i >= 0]
        if not posicoes:
            raise ValueError(f"resposta sem JSON: {texto[:200]}")
        ini, fim = min(posicoes), max(texto.rfind("}"), texto.rfind("]"))
        return json.loads(texto[ini:fim + 1])
    return texto


# ------------------------------------------------------------------ motion
def m_motion(d):
    """O estado do motion de um item: contexto, referências, momentos sugeridos/aprovados/prontos."""
    from plano import momentos
    _abs(d["pasta"])
    return momentos.estado(d["pasta"])


def m_motion_contexto(d):
    from plano import momentos
    _abs(d["pasta"])
    return momentos.salvar_contexto(d["pasta"], str(d.get("texto", "")))


def m_motion_referencias(d):
    """Copia imagens (arrastadas de qualquer pasta) para as referências do item."""
    from plano import momentos
    _abs(d["pasta"])
    novos = momentos.adicionar_referencias(d["pasta"], [str(a) for a in d.get("arquivos") or []])
    if d.get("abrir"):
        m_abrir({"arquivo": os.path.relpath(os.path.join(momentos.pasta_motion(d["pasta"]), "referencias"), BASE)})
        return {"novos": novos, "abrir": True}
    return {"novos": novos}


def m_motion_quadro(d):
    """O quadro escolhido no preview vira uma referência."""
    from plano import momentos
    _abs(d["pasta"])
    _abs(d["video"])
    return momentos.quadro_como_referencia(d["pasta"], d["video"], float(d.get("t", 0)))


def m_motion_tirar(d):
    from plano import momentos
    _abs(d["pasta"])
    _abs(d["arquivo"])
    return momentos.tirar_referencia(d["pasta"], d["arquivo"])


def m_motion_marcar(d):
    from plano import momentos
    _abs(d["pasta"])
    return momentos.marcar(d["pasta"], d["id"], d.get("mudancas") or {})


def m_motion_ref(d):
    """Referências de um momento: acao = adicionar | quadro | alternar | tirar | pasta."""
    from plano import momentos
    _abs(d["pasta"])
    if d.get("arquivo"):
        _abs(d["arquivo"])
    if d.get("video"):
        _abs(d["video"])
    s = momentos.ref_momento(d["pasta"], d["id"], d["acao"], [str(a) for a in d.get("arquivos") or []],
                           d.get("arquivo", ""), d.get("video", ""), float(d.get("t", 0)))
    if d["acao"] == "pasta":
        m_abrir({"arquivo": os.path.relpath(momentos.pasta_refs_momento(d["pasta"], d["id"]), BASE)})
    return s


def m_motion_novo(d):
    """Um momento novo no quadro escolhido (para um b-roll gerado ou um motion à mão)."""
    from plano import momentos
    _abs(d["pasta"])
    _abs(d["video"])
    ini = float(d.get("ini", 0))
    return momentos.novo_momento(d["pasta"], d["video"], ini, d.get("fim"), d.get("tipo") or "broll",
                               str(d.get("texto") or ""))


def m_video_modelos(_):
    """Modelos de vídeo do OpenRouter (duração, resolução, formato, preço)."""
    from criar import video as video_ia
    return video_ia.modelos()


def m_video_prompt(d):
    """Um prompt inicial para o vídeo de um momento (o usuário edita antes de gerar)."""
    from plano import momentos
    from criar import video as video_ia
    _abs(d["pasta"])
    s = next((x for x in momentos.ler_sugestoes(d["pasta"]).get("itens", []) if x["id"] == d["id"]), None)
    if s is None:
        raise ValueError("momento não encontrado")
    return s.get("prompt_video") or video_ia.prompt_inicial(d["pasta"], s)


def m_video_gerar(d):
    """Gera o vídeo do momento no OpenRouter (tarefa: de 30 s a vários minutos)."""
    _abs(d["pasta"])
    if not config.chave("video"):
        raise ValueError("sem a chave do vídeo: no botão da IA, em \"Vídeo com IA\", cole a chave do OpenRouter")
    cmd = [sys.executable, os.path.join(SRC, "criar", "video.py"), "gerar", d["pasta"], d["id"],
           "--modelo", str(d["modelo"]), "--prompt", str(d.get("prompt") or ""),
           "--formato", str(d.get("formato") or "9:16"), "--refs", str(d.get("refs") or "primeiro_quadro")]
    if d.get("duracao"):
        cmd += ["--duracao", str(int(d["duracao"]))]
    if d.get("resolucao"):
        cmd += ["--resolucao", str(d["resolucao"])]
    if d.get("audio"):
        cmd.append("--audio")
    return _iniciar(cmd, "video-ia", lambda _c: {"motion": d["pasta"]})


def m_prompt_ia(d):
    """A IA das sugestões escreve/melhora o briefing do motion ou o prompt do vídeo de um momento."""
    from plano import prompts as prompts_ia
    _abs(d["pasta"])
    return prompts_ia.pedir(d["pasta"], d["id"], d["alvo"], str(d.get("atual") or ""), str(d.get("modelo") or ""),
                            "abordagens" if d.get("abordagens") else "melhorar")


def m_broll_candidatos(d):
    """3–5 candidatos de b-roll do acervo (todas as fontes ativas) para um momento, com miniatura."""
    from achar import broll
    _abs(d["pasta"])
    return broll.candidatos(d["pasta"], d["id"], int(d.get("n") or 5), bool(d.get("ia")))


def m_broll_sequencia(d):
    """Grava a sequência escolhida (1–3 pedaços: arquivo, tipo, ini, dur) e, se `aprovar`, aprova o momento."""
    from achar import broll
    from plano import momentos
    _abs(d["pasta"])
    for i in d.get("itens") or []:
        _abs(i["arquivo"])
    s = broll.sequencia(d["pasta"], d["id"], list(d.get("itens") or []))
    if d.get("aprovar") and (s.get("broll") or {}).get("sequencia"):
        s = momentos.marcar(d["pasta"], d["id"], {"status": "aprovado"})
    return s


def m_broll_indexar(d):
    """Refaz o índice de b-roll (todas as fontes ativas, ou só `fonte`)."""
    from achar import indice
    return indice.indexar(d.get("fonte") or None)


def m_modelos_prompt(d):
    """Os modelos de prompt (estilos prontos) de um alvo (motion/video), filtrados pelo tipo do momento."""
    from plano import modelos
    return modelos.listar(str(d.get("alvo") or ""), str(d.get("tipo") or ""))


def m_modelo_aplicar(d):
    """Escreve o briefing/prompt de um momento a partir de um modelo e guarda a escolha."""
    from plano import modelos
    _abs(d["pasta"])
    return modelos.aplicar(d["pasta"], d["id"], d["modelo"])


def m_motion_salvar(d):
    """Grava um campo de texto de um momento (briefing, prompt do vídeo, texto) sem mudar o status."""
    from plano import momentos
    _abs(d["pasta"])
    campos = {k: v for k, v in (d.get("campos") or {}).items() if k in ("briefing", "prompt_video", "texto", "apoio")}
    return momentos.marcar(d["pasta"], d["id"], campos)


def m_motion_sugerir(d):
    """Pede os momentos ao Claude (tarefa: leva de 10 a 60 s)."""
    _abs(d["pasta"])
    from nucleo import ia
    if not ia.info()["claude"]:
        raise ValueError("sem chave da API: abra o botão da IA no topo do painel")
    cmd = [sys.executable, os.path.join(SRC, "plano", "momentos.py"), "sugerir", d["pasta"],
           "--max", str(int(d.get("max", 4)))]
    return _iniciar(cmd, "motion", lambda _c: {"motion": d["pasta"]})


METODOS = {nome[2:]: f for nome, f in globals().items() if nome.startswith("m_") and callable(f)}


def atender(pedido: dict) -> dict:
    pid = pedido.get("id")
    metodo = METODOS.get(pedido.get("metodo", ""))
    if not metodo:
        return {"id": pid, "ok": False, "erro": f"método desconhecido: {pedido.get('metodo')}"}
    try:
        return {"id": pid, "ok": True, "resultado": metodo(pedido.get("dados") or {})}
    except Exception as e:
        return {"id": pid, "ok": False, "erro": f"{type(e).__name__}: {e}",
                "detalhe": traceback.format_exc(limit=3)}


def _em_lote(pedido: dict) -> bool:
    """Miniaturas da grade (pedidas às centenas ao rolar) vão para uma fila própria, para
    não atrasar o que a pessoa acabou de clicar (preview, quadro, marcação)."""
    d = pedido.get("dados") or {}
    return pedido.get("metodo") == "miniatura" and d.get("t") is None and int(d.get("px") or 0) <= 400


def serve() -> None:
    emitir({"evento": "pronto", "versao": VERSAO, "base": BASE})
    with ThreadPoolExecutor(max_workers=6) as rapido, ThreadPoolExecutor(max_workers=3) as lote:
        for linha in sys.stdin:
            linha = linha.strip()
            if not linha:
                continue
            try:
                pedido = json.loads(linha)
            except json.JSONDecodeError:
                emitir({"ok": False, "erro": "json inválido"})
                continue
            (lote if _em_lote(pedido) else rapido).submit(lambda p=pedido: emitir(atender(p)))


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "serve":
        serve()
    elif len(sys.argv) >= 3 and sys.argv[1] == "chamar":
        dados = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        r = atender({"id": 0, "metodo": sys.argv[2], "dados": dados})
        print(json.dumps(r, ensure_ascii=False, indent=1))
        sys.exit(0 if r["ok"] else 1)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
