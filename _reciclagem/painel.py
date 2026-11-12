#!/usr/bin/env python3
"""Passo 5 — gera `painel.html`: preview, marcação e fila de geração, offline.

    python3 _reciclagem/painel.py                 # gera <acervo>/painel.html
    python3 _reciclagem/servidor.py               # + botões que escrevem no disco

O HTML é autocontido (CSS/JS/dados embutidos) e aponta a mídia por caminho
relativo — abre com duplo clique. Sem o servidor, as marcações ficam no navegador
(localStorage) e saem por "exportar marcações"; com `servidor.py`, o painel grava
direto em `_reciclagem/estados.json` e gera os projetos pelo botão.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bcnlib  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = bcnlib.BASE
SAIDA = os.path.join(BASE, "painel.html")

TAMANHOS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350),
            "16:9": (1920, 1080)}
EXTS_VIDEO = ("mp4", "mov", "m4v")


def montar_dados(limite_fala: int = 260, limite_legenda: int = 400) -> list[dict]:
    midias, _, _ = bcnlib.coletar(BASE)
    org = [m for m in midias if m.get("organizado")]
    posts = bcnlib.marcar_repetidos(bcnlib.agrupar_posts(org))
    bcnlib.pontuar(posts, dt.date.today())
    por_post = {p["post_id"]: p for p in posts}
    itens_por_post: dict[str, list[dict]] = {}
    for m in org:
        itens_por_post.setdefault(m["post_id"], []).append(m)

    dados = []
    for pid, p in por_post.items():
        itens = sorted(itens_por_post[pid],
                       key=lambda m: (0 if "imagens" in m["arquivo"] else 1, m["num"]))
        pasta = os.sep.join(itens[0]["arquivo"].split(os.sep)[:-2])
        nome = os.path.basename(pasta)
        videos = [m for m in itens if m["ext"] in EXTS_VIDEO]
        imagens = [m for m in itens if m["ext"] not in EXTS_VIDEO]
        fmt = itens[0]["formato"] if itens[0]["formato"] in TAMANHOS else ""
        larg, alt = TAMANHOS.get(fmt, (1080, 1080))
        alvo = os.path.join(BASE, pasta, f"{nome}.{'fcproj' if videos else 'pcraft'}")
        dados.append({
            "id": pid,
            "pasta": pasta.replace(os.sep, "/"),
            "nome": nome,
            "data": p["data"][:10],
            "ano": p["data"][:4],
            "pilar": p["pilar"],
            "conf": p["confianca"],
            "curtidas": p["curtidas"],
            "score": p["score"],
            "partes": p["score_partes"],
            "percentil": p["percentil"],
            "idade": p["idade_dias"],
            "repetido": p.get("repetido", 1),
            "tipo": "fcproj" if videos else "pcraft",
            "seq": f"{larg}×{alt}",
            "n_video": len(videos),
            "n_img": len(imagens),
            "midias": [m["arquivo"].replace(os.sep, "/") for m in imagens + videos],
            "thumb": (imagens[0]["arquivo"].replace(os.sep, "/") if imagens else ""),
            "url": p["url"],
            "gancho": (p["legenda"] or "").strip()[:limite_legenda],
            "fala": (p["fala"] or "")[:limite_fala],
            "projeto": os.path.exists(alvo),
            "peso": round(len(imagens) * 3.2 + len(videos) * 0.01, 1),
            "mb": round(sum(m["bytes"] for m in itens) / 1e6, 1),
        })
    dados.sort(key=lambda d: d["data"], reverse=True)
    return dados


HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>bcn_academy — painel</title>
<style>
  :root{--bg:#0e1013;--card:#171a1f;--card2:#1e222a;--linha:#2a2f39;--txt:#e8eaee;
        --dim:#98a0ae;--acento:#4ad3a0;--alerta:#e2b04a;--erro:#e2695f;--rep:#7aa2f7}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
       font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  header{position:sticky;top:0;z-index:20;background:rgba(14,16,19,.97);
         border-bottom:1px solid var(--linha);padding:10px 16px 9px;backdrop-filter:blur(8px)}
  .topo{display:flex;gap:14px;align-items:center;flex-wrap:wrap}
  h1{margin:0;font-size:15px;font-weight:600}
  h1 span{color:var(--dim);font-weight:400}
  .abas{display:flex;gap:4px;background:var(--card2);border:1px solid var(--linha);
        border-radius:9px;padding:3px}
  .abas button{background:none;border:0;color:var(--dim);padding:5px 12px;border-radius:6px;
        font-size:13px;cursor:pointer}
  .abas button.on{background:var(--acento);color:#07201a;font-weight:600}
  .modo{font-size:11.5px;color:var(--dim);margin-left:auto;display:flex;gap:8px;align-items:center}
  .led{width:7px;height:7px;border-radius:50%;background:var(--alerta)}
  .led.on{background:var(--acento)}
  .filtros{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:9px}
  input[type=search],select{background:var(--card2);border:1px solid var(--linha);
        color:var(--txt);border-radius:7px;padding:6px 9px;font-size:13px}
  input[type=search]{min-width:300px}
  button{background:var(--card2);border:1px solid var(--linha);color:var(--txt);
         border-radius:7px;padding:6px 11px;font-size:13px;cursor:pointer}
  button:hover{border-color:#3d4653}
  button.primario{background:var(--acento);border-color:var(--acento);color:#07201a;font-weight:600}
  button.on{background:#12312a;border-color:var(--acento);color:var(--acento)}
  button:disabled{opacity:.35;cursor:default}
  .pill{display:inline-flex;gap:6px;align-items:center;background:var(--card2);
        border:1px solid var(--linha);border-radius:999px;padding:4px 10px;font-size:12px;
        cursor:pointer;user-select:none}
  .pill.on{background:#12312a;border-color:var(--acento);color:var(--acento)}
  main{padding:14px 16px 94px}
  #grade{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(215px,1fr))}
  .card{background:var(--card);border:1px solid var(--linha);border-radius:11px;
        overflow:hidden;position:relative;cursor:pointer}
  .card:hover{border-color:#3d4653}
  .card.sel{border-color:var(--acento);box-shadow:0 0 0 1px var(--acento) inset}
  .card.nao{opacity:.45}
  .card.rep{border-color:#2d3a52}
  .thumb{aspect-ratio:1/1;background:#0a0c0f;display:flex;align-items:center;
         justify-content:center;overflow:hidden;position:relative}
  .thumb img{width:100%;height:100%;object-fit:cover;display:block}
  .thumb video{width:100%;height:100%;object-fit:cover}
  .ph{width:100%;height:100%;display:flex;flex-direction:column;gap:6px;align-items:center;
      justify-content:center;color:var(--dim);
      background:repeating-linear-gradient(45deg,#12151a,#12151a 10px,#151920 10px,#151920 20px)}
  .ph b{font-size:26px;color:#5b6677}
  .badge{position:absolute;top:7px;left:7px;background:rgba(8,10,13,.85);
         border:1px solid var(--linha);border-radius:6px;padding:2px 6px;font-size:10.5px;
         letter-spacing:.3px}
  .badge.ok{color:var(--acento);border-color:#245745}
  .score{position:absolute;top:7px;right:38px;background:rgba(8,10,13,.85);
         border:1px solid var(--linha);border-radius:6px;padding:2px 6px;font-size:10.5px;
         color:var(--alerta);font-variant-numeric:tabular-nums}
  .ver{position:absolute;top:7px;right:7px;background:rgba(8,10,13,.85);
       border:1px solid var(--linha);border-radius:6px;padding:2px 7px;font-size:11px}
  .marcas{position:absolute;bottom:7px;left:7px;display:flex;gap:5px}
  .marcas button{margin:0;padding:2px 7px;font-size:11px;background:rgba(8,10,13,.85)}
  .marcas button.a{color:var(--erro);border-color:#5a2b28}
  .marcas button.b{color:var(--rep);border-color:#2d3a52}
  .marcas button.a.on{background:#3a1f1d;border-color:var(--erro)}
  .marcas button.b.on{background:#1c2537;border-color:var(--rep)}
  .info{padding:8px 10px 10px}
  .nome{font-size:12.5px;line-height:1.3;height:33px;overflow:hidden;color:#cfd5df}
  .meta{display:flex;gap:6px;justify-content:space-between;margin-top:6px;font-size:11.5px;
        color:var(--dim)}
  .p{font-size:10.5px;letter-spacing:.4px;padding:1px 5px;border-radius:4px;background:#232833;
     color:#b6bfcd}
  /* recomendados */
  #lista{display:flex;flex-direction:column;gap:8px;max-width:1100px}
  .linha{display:grid;grid-template-columns:74px 1fr auto;gap:12px;align-items:center;
         background:var(--card);border:1px solid var(--linha);border-radius:10px;padding:8px}
  .linha.nao{opacity:.45}
  .linha img,.linha .mini{width:74px;height:74px;object-fit:cover;border-radius:7px;background:#0b0d10;
         display:flex;align-items:center;justify-content:center;color:#5b6677;font-size:20px}
  .linha .t{font-size:13px;color:#dfe4ec;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .linha .s{font-size:11.5px;color:var(--dim);margin-top:3px;display:flex;gap:10px;flex-wrap:wrap}
  .barra{height:5px;border-radius:3px;background:#232833;margin-top:6px;overflow:hidden;max-width:420px}
  .barra i{display:block;height:100%;background:linear-gradient(90deg,#2f6f5b,var(--acento))}
  .dir{display:flex;flex-direction:column;gap:5px;align-items:flex-end}
  .nota{font-size:20px;font-variant-numeric:tabular-nums;color:var(--alerta);font-weight:600}
  footer{position:fixed;bottom:0;left:0;right:0;z-index:30;display:flex;gap:10px;
         align-items:center;padding:10px 16px;background:rgba(14,16,19,.98);
         border-top:1px solid var(--linha);backdrop-filter:blur(8px)}
  footer .aviso{color:var(--dim);font-size:12px}
  #det{position:fixed;inset:0;background:rgba(6,7,9,.85);z-index:40;display:none;
       padding:24px;overflow:auto}
  #det.on{display:block}
  .folha{max-width:1080px;margin:0 auto;background:var(--card);border:1px solid var(--linha);
         border-radius:14px;padding:18px}
  .folha h2{margin:0 0 4px;font-size:16px}
  .folha .sub{color:var(--dim);font-size:12.5px;margin-bottom:12px}
  .mosaico{display:grid;gap:8px;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));
           margin:12px 0 16px}
  .mosaico figure{margin:0;background:#0b0d10;border:1px solid var(--linha);border-radius:9px;
                  overflow:hidden}
  .mosaico img,.mosaico video{width:100%;display:block;background:#000}
  .mosaico figcaption{font-size:11px;color:var(--dim);padding:5px 7px}
  .bloco{background:var(--card2);border:1px solid var(--linha);border-radius:9px;padding:10px 12px;
         margin:8px 0;font-size:13px;white-space:pre-wrap}
  .bloco b{display:block;font-size:11px;letter-spacing:.6px;color:var(--dim);margin-bottom:5px;
           text-transform:uppercase}
  .kv{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px;color:var(--dim);margin:6px 0}
  .kv b{color:var(--txt);font-weight:500}
  a{color:var(--acento)}
  #toast{position:fixed;left:50%;bottom:78px;transform:translateX(-50%);z-index:60;
         background:#101418;border:1px solid var(--linha);border-radius:9px;padding:9px 14px;
         font-size:12.5px;opacity:0;transition:opacity .18s;pointer-events:none;max-width:70vw}
  #toast.on{opacity:1}
</style>
</head>
<body>
<header>
  <div class="topo">
    <h1>bcn_academy <span>· __N__ posts</span></h1>
    <div class="abas">
      <button id="abaGrade" class="on">acervo</button>
      <button id="abaRec">recomendados</button>
      <button id="abaCortes">cortes</button>
    </div>
    <div class="modo"><span class="led" id="led"></span><span id="modoTxt">arquivo (offline)</span></div>
  </div>
  <div class="filtros">
    <input type="search" id="busca" placeholder="buscar na pasta, legenda ou fala transcrita…">
    <select id="ano"><option value="">todos os anos</option></select>
    <select id="tipo">
      <option value="">todos os tipos</option>
      <option value="fcproj">com vídeo → FilmCraft</option>
      <option value="pcraft">só imagem → PhotoCraft</option>
    </select>
    <select id="status">
      <option value="">status: todos</option>
      <option value="pendente">pendentes (sem marcação)</option>
      <option value="nao">não interessantes</option>
      <option value="rep">já repostados</option>
      <option value="semprojeto">sem projeto ainda</option>
    </select>
    <div id="pilares" style="display:flex;gap:6px;flex-wrap:wrap"></div>
  </div>
</header>

<main>
  <div id="grade"></div>
  <div id="lista" style="display:none"></div>
  <div id="cortes" style="display:none"></div>
</main>

<footer>
  <span><b id="nsel">0</b> selecionados <span class="aviso" id="pesoSel"></span></span>
  <span class="aviso" id="dica">clique marca · “ver” abre o preview · NI = não interessa · RP = já repostado</span>
  <span style="flex:1"></span>
  <button id="marcarVisiveis">marcar visíveis</button>
  <button id="limpar">limpar</button>
  <label class="aviso" style="display:flex;gap:6px;align-items:center;cursor:pointer">
    <input type="checkbox" id="embutir"> embutir imagens no .pcraft (pesado)
  </label>
  <button id="exportarEstados">exportar marcações</button>
  <button class="primario" id="gerar" disabled>gerar projeto</button>
</footer>

<div id="det"><div class="folha" id="folha"></div></div>
<div id="toast"></div>

<script>
const DADOS = __DADOS__;
const CORTES = __CORTES__;
const ESTADOS = __ESTADOS__;
const sel = new Set();
let filtrados = [], mostrados = 0, pilarAtivo = '', aba = 'grade';
let SERVIDOR = false;

const S = k => JSON.parse(localStorage.getItem('bcn-est-'+k) || '{}');
let locais = S('v1');

function estadoDe(d){
  return ESTADOS[d.nome] || locais[d.nome] || {};
}
function marcado(d, qual){ return !!estadoDe(d)[qual]; }

// ---------- servidor ----------
async function checarServidor(){
  try{
    const r = await fetch('/api/estado', {cache:'no-store'});
    const j = await r.json();
    if(j && j.servidor){
      SERVIDOR = true;
      Object.assign(ESTADOS, j.estados || {});
      document.getElementById('led').classList.add('on');
      document.getElementById('modoTxt').textContent =
        'servidor local · marcações e projetos gravados no disco';
    }
  }catch(e){ /* offline: segue no modo arquivo */ }
}
async function marcar(d, qual, valor){
  locais[d.nome] = Object.assign({}, estadoDe(d), {[qual]: valor});
  localStorage.setItem('bcn-est-v1', JSON.stringify(locais));
  if(SERVIDOR){
    try{
      const r = await fetch('/api/marcar', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({post:d.nome, [qual]: valor})});
      const j = await r.json();
      if(j.estados) { Object.keys(ESTADOS).forEach(k=>delete ESTADOS[k]);
                      Object.assign(ESTADOS, j.estados); }
    }catch(e){ toast('não consegui gravar no disco — ficou só no navegador'); }
  }
  aplicar();
}
async function gerar(posts){
  if(!posts.length) return;
  const embutir = document.getElementById('embutir').checked;
  if(!SERVIDOR){
    const cmd = 'python3 _reciclagem/gerar_projetos.py ' +
                posts.map(p=>'--post "'+p+'"').join(' ') +
                (embutir ? '' : ' --linked') + ' --aplicar';
    navigator.clipboard?.writeText(cmd);
    toast('sem servidor: comando copiado — ' + cmd.slice(0,60) + '…');
    return;
  }
  toast(`gerando ${posts.length} projeto(s)…`);
  const r = await fetch('/api/gerar', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({posts, linked: !embutir})});
  const j = await r.json();
  (j.gerados||[]).forEach(nome=>{
    const d = DADOS.find(x=>x.nome===nome); if(d) d.projeto = true;
  });
  toast(j.ok ? `${(j.gerados||[]).length} projeto(s) gerados` : 'erro ao gerar: '+(j.saida||'').slice(0,120));
  aplicar();
}
function toast(msg){
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('on');
  clearTimeout(t._h); t._h = setTimeout(()=>t.classList.remove('on'), 4200);
}

// ---------- filtros ----------
const elAno = document.getElementById('ano');
const elPilar = document.getElementById('pilares');
[...new Set(DADOS.map(d=>d.ano))].sort().reverse()
  .forEach(a=>elAno.insertAdjacentHTML('beforeend', `<option>${a}</option>`));
const cont = {};
DADOS.forEach(d=>cont[d.pilar]=(cont[d.pilar]||0)+1);
Object.entries(cont).sort((a,b)=>b[1]-a[1]).forEach(([p,n])=>{
  const b=document.createElement('span');
  b.className='pill'; b.dataset.p=p; b.textContent=`${p} ${n}`;
  b.onclick=()=>{ pilarAtivo = (pilarAtivo===p)?'':p;
    [...elPilar.children].forEach(c=>c.classList.toggle('on', c.dataset.p===pilarAtivo));
    aplicar(); };
  elPilar.appendChild(b);
});

function casar(d,q){
  if(!q) return true;
  const alvo=(d.nome+' '+d.gancho+' '+d.fala).toLowerCase();
  return q.split(/\s+/).every(t=>alvo.includes(t));
}
function passa(d){
  const q=document.getElementById('busca').value.trim().toLowerCase();
  const ano=elAno.value, tipo=document.getElementById('tipo').value;
  const st=document.getElementById('status').value;
  if(ano && d.ano!==ano) return false;
  if(tipo && d.tipo!==tipo) return false;
  if(pilarAtivo && d.pilar!==pilarAtivo) return false;
  if(!casar(d,q)) return false;
  const e=estadoDe(d);
  if(st==='nao' && !e.nao_interessante) return false;
  if(st==='rep' && !e.repostado) return false;
  if(st==='semprojeto' && d.projeto) return false;
  if(st==='pendente' && (e.nao_interessante || e.repostado || d.projeto)) return false;
  return true;
}
function atualizarRodape(){
  document.getElementById('nsel').textContent = sel.size;
  const peso = DADOS.filter(d=>sel.has(d.id)).reduce((s,d)=>s+d.peso,0);
  document.getElementById('pesoSel').textContent = peso ? `· ~${peso.toFixed(0)} MB de projeto` : '';
  const g = document.getElementById('gerar');
  g.disabled = sel.size===0;
  g.textContent = sel.size>1 ? `gerar ${sel.size} projetos` : 'gerar projeto';
}
function aplicar(){
  filtrados = DADOS.filter(passa);
  if(aba==='grade') desenhar();
  else if(aba==='rec') desenharLista();
  else desenharCortes();
  atualizarRodape();
}

// ---------- grade ----------
const grade=document.getElementById('grade'), lista=document.getElementById('lista');
function desenhar(){ grade.innerHTML=''; mostrados=0; encher();
  window.onscroll=()=>{ if(innerHeight+scrollY>document.body.offsetHeight-700) encher(); }; }
function encher(){
  const lote=filtrados.slice(mostrados,mostrados+48);
  lote.forEach(d=>grade.appendChild(cartao(d)));
  mostrados+=lote.length;
}
function cartao(d){
  const el=document.createElement('div');
  const e=estadoDe(d);
  el.className='card'+(sel.has(d.id)?' sel':'')+(e.nao_interessante?' nao':'')+(e.repostado?' rep':'');
  const midia = d.thumb ? `<img loading="lazy" src="${d.thumb}" alt="">`
    : `<div class="ph"><b>▶</b><span>${d.n_video} vídeo(s)</span></div>`;
  el.innerHTML=`
    <div class="thumb">${midia}
      <span class="badge ${d.projeto?'ok':''}">${d.projeto?'PROJETO ✓':(d.tipo==='fcproj'?'REEL':'CARROSSEL')}</span>
      <span class="score">${d.score}</span>
      <button class="ver">ver</button>
      <div class="marcas">
        <button class="a ${e.nao_interessante?'on':''}" title="não interessante">NI</button>
        <button class="b ${e.repostado?'on':''}" title="já repostado">RP</button>
      </div>
    </div>
    <div class="info">
      <div class="nome">${d.nome}</div>
      <div class="meta"><span class="p">${d.pilar}</span>
        <span>${d.n_img} img · ${d.n_video} vid · ${d.curtidas} ♥</span></div>
    </div>`;
  const vid=d.midias.find(m=>/\.(mp4|mov|m4v)$/i.test(m));
  if(vid){
    const th=el.querySelector('.thumb');
    th.onmouseenter=()=>{ if(th.dataset.loaded) return; th.dataset.loaded='1';
      const v=document.createElement('video'); v.src=vid; v.muted=true; v.preload='metadata';
      v.style.cssText='width:100%;height:100%;object-fit:cover';
      const ph=th.querySelector('.ph'); if(ph) ph.replaceWith(v); };
  }
  el.onclick=ev=>{
    if(ev.target.classList.contains('ver')){ abrir(d); return; }
    if(ev.target.classList.contains('a')){ marcar(d,'nao_interessante',!e.nao_interessante); return; }
    if(ev.target.classList.contains('b')){ marcar(d,'repostado',!e.repostado); return; }
    if(sel.has(d.id)){ sel.delete(d.id); el.classList.remove('sel'); }
    else { sel.add(d.id); el.classList.add('sel'); }
    atualizarRodape();
  };
  return el;
}

// ---------- recomendados ----------
function desenharLista(){
  const ordenados=[...filtrados].sort((a,b)=>b.score-a.score);
  lista.innerHTML='';
  if(!ordenados.length){ lista.innerHTML='<p style="color:var(--dim)">nada com esses filtros</p>'; return; }
  ordenados.slice(0,60).forEach((d,i)=>{
    const e=estadoDe(d), p=d.partes;
    const el=document.createElement('div');
    el.className='linha'+(e.nao_interessante?' nao':'');
    const midia = d.thumb ? `<img loading="lazy" src="${d.thumb}" alt="">`
      : `<div class="mini">▶</div>`;
    el.innerHTML=`
      ${midia}
      <div>
        <div class="t">${i+1}. ${d.nome}</div>
        <div class="s"><span>${d.pilar}</span><span>${d.curtidas} ❤ (p${d.percentil})</span>
          <span>${d.idade} dias</span><span>${d.n_img} img · ${d.n_video} vid</span>
          ${d.repetido>1?'<span style="color:var(--alerta)">legenda repetida</span>':''}</div>
        <div class="s"><span>alcance ${p.alcance}</span><span>evergreen ${p.evergreen}</span>
          <span>material ${p.material}</span><span>maturidade ${p.maturidade}</span>
          ${p.penal?`<span style="color:var(--erro)">penal ${p.penal}</span>`:''}</div>
        <div class="barra"><i style="width:${Math.max(2,Math.min(100,d.score))}%"></i></div>
      </div>
      <div class="dir">
        <span class="nota">${d.score}</span>
        <button class="ver">ver</button>
        <button class="gen">gerar</button>
      </div>`;
    el.querySelector('.ver').onclick=ev=>{ ev.stopPropagation(); abrir(d); };
    el.querySelector('.gen').onclick=ev=>{ ev.stopPropagation(); gerar([d.nome]); };
    el.onclick=()=>abrir(d);
    lista.appendChild(el);
  });
}

// ---------- cortes ----------
const elCortes = document.getElementById('cortes');
function desenharCortes(){
  const q = document.getElementById('busca').value.trim().toLowerCase();
  const lista = CORTES.filter(c => (!q || (c.tema+c.fala).toLowerCase().includes(q))
                                  && (!pilarAtivo || c.pilar===pilarAtivo));
  elCortes.innerHTML = '';
  if(!lista.length){ elCortes.innerHTML = '<p style="color:var(--dim)">nenhum corte com esse filtro</p>'; return; }
  const cab = document.createElement('p');
  cab.className='aviso';
  cab.textContent = `${lista.length} cortes · ${(lista.reduce((s,c)=>s+c.seg,0)/60).toFixed(0)} min de material`;
  elCortes.appendChild(cab);
  lista.forEach(c=>{
    const el=document.createElement('div');
    el.className='linha';
    el.innerHTML=`
      <div class="mini">▶</div>
      <div>
        <div class="t">${c.tema} · ${c.seg}s · ${c.mb} MB</div>
        <div class="s"><span>${c.pilar}</span><span>${c.nome_arq}</span>
          ${c.projeto?'<span style="color:var(--acento)">projeto ✓</span>':''}</div>
        <div class="s" style="color:#b9c1cd">${(c.fala||'(sem transcrição)').slice(0,150)}…</div>
      </div>
      <div class="dir"><button class="gen">gerar</button></div>`;
    el.querySelector('.gen').onclick=()=>gerarCorte(c);
    elCortes.appendChild(el);
  });
}
async function gerarCorte(c){
  if(!SERVIDOR){
    navigator.clipboard?.writeText(`python3 _reciclagem/gerar_projetos.py --tipo corte --corte "${c.nome_arq}" --aplicar`);
    toast('sem servidor: comando copiado');
    return;
  }
  toast(`gerando projeto de ${c.tema}…`);
  const r = await fetch('/api/gerar', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({posts:[c.nome_arq], cortes:true})});
  const j = await r.json();
  c.projeto = !!j.ok;
  toast(j.ok ? 'projeto do corte gerado' : 'erro: '+(j.saida||'').slice(0,120));
  desenharCortes();
}

// ---------- detalhe ----------
function abrir(d){
  const e=estadoDe(d);
  const midias=d.midias.map(m=>m.match(/\.(mp4|mov|m4v)$/i)
    ? `<figure><video controls preload="metadata" src="${m}"></video>
       <figcaption>${m.split('/').pop()}</figcaption></figure>`
    : `<figure><img loading="lazy" src="${m}"><figcaption>${m.split('/').pop()}</figcaption></figure>`
  ).join('');
  const p=d.partes;
  document.getElementById('folha').innerHTML=`
    <button class="fechar" style="float:right" onclick="fechar()">fechar ✕</button>
    <h2>${d.nome}</h2>
    <div class="sub">${d.data} · ${d.pilar} (confiança ${d.conf}) · ${d.curtidas} curtidas
      · ${d.n_img} imagens, ${d.n_video} vídeos · ${d.mb} MB</div>
    <div class="kv"><span>score <b>${d.score}</b></span>
      <span>alcance <b>${p.alcance}</b></span><span>evergreen <b>${p.evergreen}</b></span>
      <span>material <b>${p.material}</b></span><span>maturidade <b>${p.maturidade}</b></span>
      ${p.penal?`<span>penal <b style="color:var(--erro)">${p.penal}</b></span>`:''}
      <span>projeto <b>${d.tipo} ${d.seq}</b>${d.tipo==='pcraft'?' · '+d.n_img+' canvas':''} ${d.projeto?'· já existe':'· ~'+d.peso.toFixed(0)+' MB'}</span>
    </div>
    <div class="sub"><a href="${d.url}" target="_blank">${d.url}</a></div>
    <div class="mosaico">${midias}</div>
    <div class="bloco"><b>legenda original</b>${d.gancho || '(vazia)'}</div>
    <div class="bloco"><b>o que é dito no vídeo</b>${d.fala || '(sem transcrição)'}</div>
    <div style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">
      <button class="primario" onclick="gerarUm('${d.nome}')">gerar projeto</button>
      <button onclick="marcarUm('${d.nome}','nao_interessante')">${e.nao_interessante?'desmarcar':'marcar'} não interessante</button>
      <button onclick="marcarUm('${d.nome}','repostado')">${e.repostado?'desmarcar':'marcar'} já repostado</button>
      <button onclick="marcarSel('${d.id}')">selecionar</button>
      <button onclick="fechar()">fechar</button>
    </div>`;
  document.getElementById('det').classList.add('on');
  document.body.style.overflow='hidden';
  window._detAtual=d;
}
function fechar(){ document.getElementById('det').classList.remove('on');
                   document.body.style.overflow=''; }
function marcarUm(nome, qual){
  const d=DADOS.find(x=>x.nome===nome); if(!d) return;
  marcar(d, qual, !estadoDe(d)[qual]);
  setTimeout(()=>abrir(d), 30);
}
function marcarSel(id){ const d=DADOS.find(x=>x.id===id); if(!d) return;
  sel.add(id); fechar(); aplicar(); }
function gerarUm(nome){ gerar([nome]); fechar(); }
window.fechar=fechar; window.marcarUm=marcarUm; window.marcarSel=marcarSel; window.gerarUm=gerarUm;

// ---------- abas e rodapé ----------
document.getElementById('abaGrade').onclick=()=>{ aba='grade';
  document.getElementById('abaGrade').classList.add('on');
  document.getElementById('abaRec').classList.remove('on');
  document.getElementById('abaCortes').classList.remove('on');
  grade.style.display=''; lista.style.display='none';
  elCortes.style.display='none'; aplicar(); };
document.getElementById('abaRec').onclick=()=>{ aba='rec';
  document.getElementById('abaRec').classList.add('on');
  document.getElementById('abaGrade').classList.remove('on');
  document.getElementById('abaCortes').classList.remove('on');
  grade.style.display='none'; lista.style.display='flex';
  elCortes.style.display='none'; aplicar(); };
document.getElementById('abaCortes').onclick=()=>{ aba='cortes';
  document.getElementById('abaCortes').classList.add('on');
  document.getElementById('abaGrade').classList.remove('on');
  document.getElementById('abaRec').classList.remove('on');
  grade.style.display='none'; lista.style.display='none';
  elCortes.style.display='flex'; atualizarRodape(); desenharCortes(); };
document.getElementById('busca').oninput=aplicar;
elAno.onchange=aplicar;
document.getElementById('tipo').onchange=aplicar;
document.getElementById('status').onchange=aplicar;
document.getElementById('marcarVisiveis').onclick=()=>{ filtrados.forEach(d=>sel.add(d.id)); aplicar(); };
document.getElementById('limpar').onclick=()=>{ sel.clear(); aplicar(); };
document.getElementById('gerar').onclick=()=>gerar(DADOS.filter(d=>sel.has(d.id)).map(d=>d.nome));
document.getElementById('exportarEstados').onclick=()=>{
  const blob=new Blob([JSON.stringify(Object.assign({}, ESTADOS, locais), null, 1)],
                      {type:'application/json'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
  a.download='estados-bcn.json'; a.click();
  toast('estados-bcn.json baixado — copie para _reciclagem/estados.json');
};

checarServidor().then(()=>{ aplicar(); });
aplicar();
</script>
</body>
</html>
"""


def montar_cortes(limite_fala: int = 320) -> list[dict]:
    """Cortes de `_Cortes/`: material bruto, um card por vídeo."""
    cortes = []
    for c in bcnlib.coletar_cortes(BASE):
        pasta = os.path.dirname(os.path.join(BASE, c["arquivo"]))
        nome = f"{c['tema'].split('/')[0].strip().replace(' ', '-')}_" \
               f"{os.path.splitext(os.path.basename(c['arquivo']))[0]}"
        cortes.append({
            "arquivo": c["arquivo"],
            "nome_arq": os.path.basename(c["arquivo"]),
            "tema": c["tema"],
            "tema_raiz": c["tema"].split("/")[0].strip(),
            "pilar": c["pilar"],
            "seg": c["segundos"],
            "mb": round(c["bytes"] / 1e6, 1),
            "fala": (c["fala"] or "")[:limite_fala],
            "gancho": c["gancho"],
            "projeto": os.path.exists(os.path.join(pasta, f"{nome}.fcproj")),
            "nome_projeto": nome,
        })
    return cortes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default=SAIDA)
    a = ap.parse_args()
    dados = montar_dados()
    cortes = montar_cortes()
    estados = bcnlib.carregar_estados()
    html = (HTML.replace("__DADOS__", json.dumps(dados, ensure_ascii=False))
                .replace("__CORTES__", json.dumps(cortes, ensure_ascii=False))
                .replace("__ESTADOS__", json.dumps(estados, ensure_ascii=False))
                .replace("__N__", str(len(dados))))
    with open(a.saida, "w", encoding="utf-8") as fh:
        fh.write(html)
    mb = os.path.getsize(a.saida) / 1e6
    com_projeto = sum(1 for d in dados if d["projeto"])
    pelos = {}
    for d in dados:
        pelos[d["tipo"]] = pelos.get(d["tipo"], 0) + 1
    print(f"painel: {a.saida} ({mb:.1f} MB)")
    print(f"{len(dados)} posts · {pelos.get('fcproj',0)} fcproj · {pelos.get('pcraft',0)} pcraft"
          f" · {com_projeto} com projeto · {len(estados)} marcados · {len(cortes)} cortes")


if __name__ == "__main__":
    main()
