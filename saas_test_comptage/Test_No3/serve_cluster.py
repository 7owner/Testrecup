"""Interface web locale : deposer un PDF -> LEGENDE-DRIVEN.

Chaine 100% deterministe (aucun modele, aucun DWG en production) :
  PDF --extract_page--> clusters vectoriels
      --find_legend_templates (corrige)--> PROTOTYPES de la legende (1 par ligne :
        glyphe + libelle + QTE declaree) + zone legende a exclure du comptage
      --filtre taille symbole (hors legende)--> candidats du plan
      --clustering d'identite (union-find sur _feature_distance)--> groupes de copies
      --appariement groupe -> prototype de legende le plus proche (sous seuil)--> NOM
  -> chaque groupe porte le NOM de sa ligne de legende ; panneau = detecte vs declare.

Lancer avec le Python qui a fitz/numpy/PIL :
  python serve_cluster.py   ->  http://localhost:8771
"""
from __future__ import annotations

import base64
import cgi
import collections
import io
import math
import json
import sys
import tempfile
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "plan_takeoff"))

import fitz
from PIL import Image
import pdf_takeoff as pt
from dwg_pdf_match import _shape_features, _feature_distance, _cluster_points

PORT = 8771
THRESH = 0.06        # distance "meme forme" pour regrouper les copies
MATCH_THRESH = 0.20  # distance max groupe<->prototype de legende pour attribuer un nom
DIAG_MIN, DIAG_MAX = 2.0, 90.0
MIN_GROUP = 2        # taille min d'un groupe pour etre compte
RENDER_W = 2200      # largeur cible de l'image rendue (px)
NONE_KEY = "__none__"
NONE_COLOR = "#9ca3af"

PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#008080", "#f032e6",
           "#9a6324", "#800000", "#808000", "#000075", "#e67e22", "#46b3f0", "#7cb518",
           "#c2185b", "#00897b", "#5e35b1", "#d81b60", "#3949ab", "#00acc1", "#8d6e63",
           "#e53935", "#1e88e5", "#43a047", "#fb8c00", "#8e24aa", "#00838f", "#6d4c41",
           "#c0ca33", "#f4511e", "#3f51b5", "#009688", "#795548", "#607d8b", "#ad1457"]


def _feat_of_cluster(c):
    pts, ops = _cluster_points(c)
    return _shape_features(pts, ops)


def cluster_plan(pdf_path):
    """-> dict pret pour la page (image PIL + legende + groupes nommes)."""
    doc = fitz.open(pdf_path)
    page = doc[0]
    pr = page.rect
    clusters, words = pt.extract_page(page)
    templates, legend_rect = pt.find_legend_templates(clusters, words, page.rect)

    # --- prototypes de legende : 1 par ligne (glyphe primaire + libelle + QTE) ---
    protos = []
    for t in templates:
        feat = _feat_of_cluster(t["cluster"])
        if not feat:
            continue
        vb = [v["bbox"] for v in t.get("variants") or [t["cluster"]]]
        bbox = [min(b[0] for b in vb), min(b[1] for b in vb),
                max(b[2] for b in vb), max(b[3] for b in vb)]
        protos.append({"label": t["label"], "qty": t.get("qty_declared"),
                       "feat": feat, "bbox": bbox})

    # --- candidats du plan (hors legende, taille symbole) ---
    cand = []
    for c in clusters:
        bb = c["bbox"]
        cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
        if legend_rect and legend_rect.contains(fitz.Point(cx, cy)):
            continue
        diag = math.hypot(bb[2] - bb[0], bb[3] - bb[1])
        if diag < DIAG_MIN or diag > DIAG_MAX:
            continue
        feat = _feat_of_cluster(c)
        if not feat:
            continue
        cand.append({"bbox": bb, "feat": feat})

    # --- clustering d'identite (union-find bucketise) ---
    parent = list(range(len(cand)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    buckets = collections.defaultdict(list)
    for idx, c in enumerate(cand):
        key = (frozenset(c["feat"]["ops"].keys()),
               round(math.log(max(c["feat"]["n_points"], 1)) * 2))
        buckets[key].append(idx)
    for members in buckets.values():
        for a in range(len(members)):
            fa = cand[members[a]]["feat"]
            for b in range(a + 1, len(members)):
                if _feature_distance(fa, cand[members[b]]["feat"]) <= THRESH:
                    union(members[a], members[b])

    groups = collections.defaultdict(list)
    for idx in range(len(cand)):
        groups[find(idx)].append(idx)
    ranked = [g for g in sorted(groups.values(), key=len, reverse=True) if len(g) >= MIN_GROUP]
    singletons = sum(1 for g in groups.values() if len(g) == 1)

    # --- appariement groupe -> prototype de legende ---
    def group_repr(g):
        # membre le plus riche en points = representant robuste du groupe
        return max((cand[i]["feat"] for i in g), key=lambda f: f["n_points"])

    label_detected = collections.Counter()
    group_key = {}   # gid -> label ou NONE_KEY
    for gi, g in enumerate(ranked):
        rf = group_repr(g)
        best_lab, best_d = None, MATCH_THRESH
        for p in protos:
            d = _feature_distance(rf, p["feat"])
            if d is not None and d < best_d:
                best_d, best_lab = d, p["label"]
        if best_lab is not None:
            group_key[gi] = best_lab
            label_detected[best_lab] += len(g)
        else:
            group_key[gi] = NONE_KEY

    # --- couleurs : par libelle de legende matche, gris pour non identifie ---
    matched_labels = [p["label"] for p in protos if label_detected.get(p["label"], 0) > 0]
    color_of = {lab: PALETTE[i % len(PALETTE)] for i, lab in enumerate(matched_labels)}
    color_of[NONE_KEY] = NONE_COLOR

    # --- rendu image ---
    zoom = RENDER_W / max(pr.width, 1.0)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    doc.close()

    # boites (coords image) avec leur cle (libelle ou none)
    boxes = []
    for gi, g in enumerate(ranked):
        key = group_key[gi]
        for idx in g:
            bb = cand[idx]["bbox"]
            boxes.append({"box": [round(bb[0] * zoom, 1), round(bb[1] * zoom, 1),
                                  round(bb[2] * zoom, 1), round(bb[3] * zoom, 1)],
                          "key": key})

    # vignettes des prototypes de legende (crop de l'image rendue)
    def thumb(bbox):
        pad = 6
        x0 = max(0, int(bbox[0] * zoom) - pad); y0 = max(0, int(bbox[1] * zoom) - pad)
        x1 = min(img.width, int(bbox[2] * zoom) + pad); y1 = min(img.height, int(bbox[3] * zoom) + pad)
        if x1 <= x0 or y1 <= y0:
            return None
        crop = img.crop((x0, y0, x1, y1))
        crop.thumbnail((70, 70))
        b = io.BytesIO(); crop.save(b, format="PNG")
        return base64.b64encode(b.getvalue()).decode("ascii")

    legend = []
    for p in protos:
        det = label_detected.get(p["label"], 0)
        legend.append({"label": p["label"], "qty": p["qty"], "detected": det,
                       "color": color_of.get(p["label"], NONE_COLOR),
                       "thumb_b64": thumb(p["bbox"])})
    legend.sort(key=lambda r: (-r["detected"], r["label"]))

    none_count = sum(len(g) for gi, g in enumerate(ranked) if group_key[gi] == NONE_KEY)

    lr_px = None
    if legend_rect:
        lr_px = [round(legend_rect.x0 * zoom, 1), round(legend_rect.y0 * zoom, 1),
                 round(legend_rect.x1 * zoom, 1), round(legend_rect.y1 * zoom, 1)]

    return {"image": img, "legend_rect_px": lr_px, "boxes": boxes, "legend": legend,
            "none_count": none_count, "none_color": NONE_COLOR,
            "n_candidates": len(cand), "n_groups": len(ranked),
            "n_protos": len(protos), "n_matched": len(matched_labels),
            "singletons": singletons}


PAGE = """<!doctype html><html lang=fr><head><meta charset=utf-8>
<title>Comptage légende-driven — plan</title>
<style>
  * { box-sizing: border-box; }
  body { margin:0; font:14px/1.4 system-ui,Segoe UI,sans-serif; color:#1a1a1a; background:#f4f4f5; }
  header { padding:12px 18px; background:#111; color:#fff; display:flex; align-items:center; gap:16px; }
  header h1 { font-size:15px; margin:0; font-weight:600; }
  header .sub { font-size:12px; color:#9ca3af; }
  #drop { margin-left:auto; }
  #drop label { background:#2563eb; color:#fff; padding:7px 14px; border-radius:6px; cursor:pointer; font-size:13px; }
  #drop input { display:none; }
  main { display:flex; height:calc(100vh - 49px); }
  #view { flex:1; overflow:hidden; position:relative; background:#e5e7eb; }
  #stage { position:absolute; transform-origin:0 0; }
  #stage img { display:block; }
  #stage svg { position:absolute; top:0; left:0; pointer-events:none; }
  aside { width:330px; background:#fff; border-left:1px solid #e5e7eb; display:flex; flex-direction:column; }
  aside .head { padding:12px 14px; border-bottom:1px solid #eee; }
  aside .head b { font-size:20px; } aside .head .m { color:#6b7280; font-size:12px; }
  .sech { padding:8px 14px; font-size:11px; letter-spacing:.4px; text-transform:uppercase;
          color:#6b7280; background:#f9fafb; border-bottom:1px solid #eee; position:sticky; top:0; }
  #counts { overflow-y:auto; flex:1; }
  .row { display:flex; align-items:center; gap:9px; padding:6px 12px; cursor:pointer; border-bottom:1px solid #f3f4f6; }
  .row:hover { background:#f9fafb; } .row.off { opacity:.34; }
  .row .sw { width:12px; height:12px; border-radius:3px; flex:none; }
  .row img { width:34px; height:26px; object-fit:contain; background:#fff; border:1px solid #eee; border-radius:3px; flex:none; }
  .row .nm { flex:1; font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .row .n { font-variant-numeric:tabular-nums; font-weight:600; font-size:12.5px; }
  .row .q { color:#9ca3af; font-size:11px; margin-left:4px; }
  .row .warn .n { color:#d97706; }
  #msg { position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
         flex-direction:column; gap:12px; color:#6b7280; text-align:center; padding:20px; }
  .spin { width:34px;height:34px;border:3px solid #d1d5db;border-top-color:#2563eb;border-radius:50%;
          animation:s 1s linear infinite; } @keyframes s { to { transform:rotate(360deg);} }
  #zoomhint { position:absolute; bottom:10px; left:12px; font-size:11px; color:#6b7280;
              background:rgba(255,255,255,.8); padding:3px 8px; border-radius:4px; }
</style></head><body>
<header>
  <h1>Comptage légende-driven</h1>
  <span class=sub id=meta></span>
  <span id=drop><label>Déposer un PDF<input type=file id=file accept=.pdf></label></span>
</header>
<main>
  <div id=view>
    <div id=stage></div>
    <div id=msg><div>Dépose un plan PDF — les symboles de la légende deviennent les prototypes,<br>
      chaque groupe du plan est relié à sa ligne de légende.<br>
      <small>100% déterministe. Zone légende exclue du comptage en pointillés gris.</small></div></div>
    <div id=zoomhint>molette = zoom · glisser = déplacer</div>
  </div>
  <aside>
    <div class=head><b id=total>—</b> objets comptés<div class=m id=info></div></div>
    <div id=counts></div>
  </aside>
</main>
<script>
const view=document.getElementById('view'), stage=document.getElementById('stage'),
      msg=document.getElementById('msg'), counts=document.getElementById('counts');
let sc=1, ox=0, oy=0, dragging=false, sx=0, sy=0, hidden=new Set(), data=null, svg=null;
function apply(){ stage.style.transform=`translate(${ox}px,${oy}px) scale(${sc})`; }
view.addEventListener('wheel',e=>{ e.preventDefault(); const r=view.getBoundingClientRect();
  const mx=e.clientX-r.left-ox, my=e.clientY-r.top-oy; const f=e.deltaY<0?1.15:1/1.15;
  sc*=f; ox-=mx*(f-1); oy-=my*(f-1); apply(); },{passive:false});
view.addEventListener('mousedown',e=>{dragging=true;sx=e.clientX-ox;sy=e.clientY-oy;});
addEventListener('mousemove',e=>{ if(dragging){ox=e.clientX-sx;oy=e.clientY-sy;apply();}});
addEventListener('mouseup',()=>dragging=false);

document.getElementById('file').onchange=e=>{ const f=e.target.files[0]; if(f) run(f); };
async function run(f){
  msg.style.display='flex'; msg.innerHTML='<div class=spin></div><div>Analyse…<br><small>'+f.name+'</small></div>';
  stage.innerHTML=''; counts.innerHTML=''; document.getElementById('total').textContent='—';
  const fd=new FormData(); fd.append('pdf',f);
  try{
    const r=await fetch('/infer',{method:'POST',body:fd}); if(!r.ok) throw new Error(await r.text());
    data=await r.json(); render();
  }catch(err){ msg.innerHTML='<div style="color:#b91c1c">Erreur : '+err.message+'</div>'; }
}
function colorForKey(k){ if(k==='__none__') return data.none_color;
  const e=data.legend.find(l=>l.label===k); return e?e.color:'#000'; }
function render(){
  msg.style.display='none'; hidden.clear();
  const img=new Image(); img.src='data:image/png;base64,'+data.image_b64;
  svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('width',data.w); svg.setAttribute('height',data.h);
  if(data.legend_rect_px){ const [x0,y0,x1,y1]=data.legend_rect_px;
    const rc=document.createElementNS('http://www.w3.org/2000/svg','rect');
    rc.setAttribute('x',x0); rc.setAttribute('y',y0); rc.setAttribute('width',x1-x0);
    rc.setAttribute('height',y1-y0); rc.setAttribute('fill','none');
    rc.setAttribute('stroke','#888'); rc.setAttribute('stroke-dasharray','8 6');
    rc.setAttribute('stroke-width',2); svg.appendChild(rc); }
  for(const d of data.boxes){ const [x0,y0,x1,y1]=d.box;
    const rc=document.createElementNS('http://www.w3.org/2000/svg','rect');
    rc.setAttribute('x',x0); rc.setAttribute('y',y0); rc.setAttribute('width',x1-x0);
    rc.setAttribute('height',y1-y0); rc.setAttribute('fill','none');
    rc.setAttribute('stroke',colorForKey(d.key)); rc.setAttribute('stroke-width',2.5);
    rc.dataset.key=d.key; svg.appendChild(rc); }
  stage.innerHTML=''; stage.appendChild(img); stage.appendChild(svg);
  const r=view.getBoundingClientRect();
  sc=Math.min(r.width/data.w, r.height/data.h)*0.98;
  ox=(r.width-data.w*sc)/2; oy=(r.height-data.h*sc)/2; apply();
  let counted=data.legend.reduce((a,l)=>a+l.detected,0);
  document.getElementById('total').textContent=counted;
  document.getElementById('info').textContent=
    data.n_matched+'/'+data.n_protos+' types de légende identifiés · '+data.n_groups+' groupes · '
    +data.none_count+' non identifiés · '+data.seconds+' s';
  document.getElementById('meta').textContent=data.name
    +(data.legend_rect_px?' · légende détectée ('+data.n_protos+' symboles)':' · pas de légende');
  counts.innerHTML='';
  const h1=document.createElement('div'); h1.className='sech'; h1.textContent='Légende → détecté / déclaré';
  counts.appendChild(h1);
  function addRow(key,thumb,label,det,qty,color,warn){
    const row=document.createElement('div'); row.className='row'+(warn?' warn':'');
    const q = (qty!==null&&qty!==undefined) ? `<span class=q>/ ${qty}</span>` : '';
    const sw = thumb ? `<img src="data:image/png;base64,${thumb}">`
                     : `<span class=sw style="background:${color}"></span>`;
    row.innerHTML=`${sw}<span class=nm title="${label}">${label}</span>`
      +`<span class=n style="color:${warn?'#d97706':'inherit'}">${det}</span>${q}`;
    row.onclick=()=>{ if(hidden.has(key)){hidden.delete(key);row.classList.remove('off');}
      else{hidden.add(key);row.classList.add('off');}
      svg.querySelectorAll(`rect[data-key="${CSS.escape(key)}"]`).forEach(r=>r.style.display=hidden.has(key)?'none':'');
    };
    counts.appendChild(row);
  }
  for(const l of data.legend){
    const warn = (l.qty!==null&&l.qty!==undefined&&l.detected!==l.qty);
    addRow(l.label,l.thumb_b64,l.label,l.detected,l.qty,l.color,warn);
  }
  if(data.none_count>0){
    const h2=document.createElement('div'); h2.className='sech'; h2.textContent='Non reliés à la légende';
    counts.appendChild(h2);
    addRow('__none__',null,'Formes sans correspondance',data.none_count,null,data.none_color,false);
  }
}
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/infer":
            self.send_error(404)
            return
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers,
                                environ={"REQUEST_METHOD": "POST",
                                         "CONTENT_TYPE": self.headers["Content-Type"]})
        item = form["pdf"]
        name = Path(item.filename or "plan.pdf").name
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            tf.write(item.file.read())
            pdf_path = tf.name
        try:
            t0 = time.time()
            res = cluster_plan(pdf_path)
            secs = round(time.time() - t0)
            buf = io.BytesIO()
            res["image"].save(buf, format="PNG")
            payload = {
                "name": name,
                "w": res["image"].width, "h": res["image"].height,
                "image_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
                "legend_rect_px": res["legend_rect_px"],
                "boxes": res["boxes"], "legend": res["legend"],
                "none_count": res["none_count"], "none_color": res["none_color"],
                "n_candidates": res["n_candidates"], "n_groups": res["n_groups"],
                "n_protos": res["n_protos"], "n_matched": res["n_matched"],
                "singletons": res["singletons"], "seconds": secs,
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            import traceback
            traceback.print_exc()
            msg = f"{type(e).__name__}: {e}".encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
        finally:
            Path(pdf_path).unlink(missing_ok=True)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Comptage legende-driven -> {url}")
    print("  (Ctrl+C pour arreter)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\narret.")


if __name__ == "__main__":
    main()
