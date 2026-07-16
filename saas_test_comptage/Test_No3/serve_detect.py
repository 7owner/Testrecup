"""Interface web locale : deposer un PDF -> voir les detections du modele sur le plan entier.

Lancer avec le Python qui a torch/torchvision/fitz (PAS le venv du projet) :
  ~/AppData/Local/Programs/Python/Python312/python.exe serve_detect.py
  -> http://localhost:8770

Le serveur rend le plan, lance infer_plan.infer(), renvoie l'image + les detections ;
la page superpose les boites (zoom/pan) et un panneau de comptes par classe.
"""
from __future__ import annotations

import base64
import cgi
import io
import json
import tempfile
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image

import infer_plan

HERE = Path(__file__).resolve().parent
D4 = HERE / "resultat_fine_tunning" / "new_resultats4"
MODEL_TS = D4 / "model.ts"
META = D4 / "model_meta (1).json"
THRESHOLDS = HERE / "thresholds.json"
PORT = 8770

# palette stable par classe (couleurs distinctes, lisibles sur fond blanc de plan)
PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#008080", "#f032e6",
           "#9a6324", "#800000", "#808000", "#000075", "#e6763b", "#46f0f0", "#bcf60c",
           "#fabebe", "#aa6e28", "#fffac8", "#aaffc3", "#ffd8b1", "#a9a9a9", "#d2691e",
           "#ff1493", "#00ced1", "#556b2f", "#8b0000", "#483d8b", "#b8860b", "#2f4f4f",
           "#dc143c", "#00bfff", "#daa520", "#9932cc", "#8fbc8f", "#cd5c5c", "#4682b4",
           "#d2b48c", "#6a5acd", "#20b2aa"]


def color_of(names):
    return {n: PALETTE[i % len(PALETTE)] for i, n in enumerate(sorted(names))}


PAGE = """<!doctype html><html lang=fr><head><meta charset=utf-8>
<title>Comptage — détection sur plan</title>
<style>
  * { box-sizing: border-box; }
  body { margin:0; font:14px/1.4 system-ui,Segoe UI,sans-serif; color:#1a1a1a; background:#f4f4f5; }
  header { padding:12px 18px; background:#111; color:#fff; display:flex; align-items:center; gap:16px; }
  header h1 { font-size:15px; margin:0; font-weight:600; letter-spacing:.3px; }
  header .sub { font-size:12px; color:#9ca3af; }
  #drop { margin-left:auto; }
  #drop label { background:#2563eb; color:#fff; padding:7px 14px; border-radius:6px; cursor:pointer; font-size:13px; }
  #drop input { display:none; }
  main { display:flex; height:calc(100vh - 49px); }
  #view { flex:1; overflow:hidden; position:relative; background:#e5e7eb; }
  #stage { position:absolute; transform-origin:0 0; }
  #stage img { display:block; }
  #stage svg { position:absolute; top:0; left:0; pointer-events:none; }
  aside { width:290px; background:#fff; border-left:1px solid #e5e7eb; display:flex; flex-direction:column; }
  aside .head { padding:12px 14px; border-bottom:1px solid #eee; }
  aside .head b { font-size:20px; } aside .head .m { color:#6b7280; font-size:12px; }
  #counts { overflow-y:auto; flex:1; }
  .row { display:flex; align-items:center; gap:9px; padding:6px 14px; cursor:pointer; border-bottom:1px solid #f3f4f6; }
  .row:hover { background:#f9fafb; } .row.off { opacity:.34; }
  .row .sw { width:13px; height:13px; border-radius:3px; flex:none; }
  .row .nm { flex:1; font-size:12.5px; } .row .n { font-variant-numeric:tabular-nums; font-weight:600; }
  #msg { position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
         flex-direction:column; gap:12px; color:#6b7280; text-align:center; padding:20px; }
  .spin { width:34px;height:34px;border:3px solid #d1d5db;border-top-color:#2563eb;border-radius:50%;
          animation:s 1s linear infinite; } @keyframes s { to { transform:rotate(360deg);} }
  #zoomhint { position:absolute; bottom:10px; left:12px; font-size:11px; color:#6b7280;
              background:rgba(255,255,255,.8); padding:3px 8px; border-radius:4px; }
</style></head><body>
<header>
  <h1>Comptage sur plan</h1>
  <span class=sub id=meta></span>
  <span id=drop><label>Déposer un PDF<input type=file id=file accept=.pdf></label></span>
</header>
<main>
  <div id=view>
    <div id=stage></div>
    <div id=msg><div>Dépose un plan PDF pour lancer la détection.<br>
      <small>Le modèle tourne en local sur CPU (~2 min selon la taille du plan).</small></div></div>
    <div id=zoomhint>molette = zoom · glisser = déplacer</div>
  </div>
  <aside>
    <div class=head><b id=total>—</b> objets détectés<div class=m id=info></div></div>
    <div id=counts></div>
  </aside>
</main>
<script>
const view=document.getElementById('view'), stage=document.getElementById('stage'),
      msg=document.getElementById('msg'), counts=document.getElementById('counts');
let sc=1, ox=0, oy=0, dragging=false, sx=0, sy=0, hidden=new Set(), data=null;

function apply(){ stage.style.transform=`translate(${ox}px,${oy}px) scale(${sc})`; }
view.addEventListener('wheel',e=>{ e.preventDefault(); const r=view.getBoundingClientRect();
  const mx=e.clientX-r.left-ox, my=e.clientY-r.top-oy; const f=e.deltaY<0?1.15:1/1.15;
  sc*=f; ox-=mx*(f-1); oy-=my*(f-1); apply(); },{passive:false});
view.addEventListener('mousedown',e=>{dragging=true;sx=e.clientX-ox;sy=e.clientY-oy;});
addEventListener('mousemove',e=>{ if(dragging){ox=e.clientX-sx;oy=e.clientY-sy;apply();}});
addEventListener('mouseup',()=>dragging=false);

document.getElementById('file').onchange=async e=>{
  const f=e.target.files[0]; if(!f) return;
  msg.style.display='flex'; msg.innerHTML='<div class=spin></div><div>Détection en cours…<br>'
    +'<small>'+f.name+'</small></div>'; stage.innerHTML=''; counts.innerHTML='';
  document.getElementById('total').textContent='—'; document.getElementById('info').textContent='';
  const fd=new FormData(); fd.append('pdf',f);
  try{
    const r=await fetch('/infer',{method:'POST',body:fd}); if(!r.ok) throw new Error(await r.text());
    data=await r.json(); render();
  }catch(err){ msg.innerHTML='<div style="color:#b91c1c">Erreur : '+err.message+'</div>'; }
};

function render(){
  msg.style.display='none'; hidden.clear();
  const img=new Image(); img.src='data:image/png;base64,'+data.image_b64;
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('width',data.w); svg.setAttribute('height',data.h);
  for(const d of data.detections){
    const [x0,y0,x1,y1]=d.box;
    const rc=document.createElementNS('http://www.w3.org/2000/svg','rect');
    rc.setAttribute('x',x0); rc.setAttribute('y',y0);
    rc.setAttribute('width',x1-x0); rc.setAttribute('height',y1-y0);
    rc.setAttribute('fill','none'); rc.setAttribute('stroke',data.colors[d.name]);
    rc.setAttribute('stroke-width',2); rc.dataset.cls=d.name;
    rc.innerHTML='<title>'+d.name+' '+d.score+'</title>'; svg.appendChild(rc);
  }
  stage.innerHTML=''; stage.appendChild(img); stage.appendChild(svg);
  // ajuste pour voir le plan entier
  const r=view.getBoundingClientRect();
  sc=Math.min(r.width/data.w, r.height/data.h)*0.98;
  ox=(r.width-data.w*sc)/2; oy=(r.height-data.h*sc)/2; apply();
  // panneau
  document.getElementById('total').textContent=data.detections.length;
  document.getElementById('info').textContent=data.n_tiles+' tuiles · '+data.seconds+' s';
  document.getElementById('meta').textContent=data.name;
  const entries=Object.entries(data.counts).sort((a,b)=>b[1]-a[1]);
  counts.innerHTML='';
  for(const [nm,n] of entries){
    const row=document.createElement('div'); row.className='row'; row.dataset.cls=nm;
    row.innerHTML=`<span class=sw style="background:${data.colors[nm]}"></span>`
      +`<span class=nm>${nm}</span><span class=n>${n}</span>`;
    row.onclick=()=>{ if(hidden.has(nm)){hidden.delete(nm);row.classList.remove('off');}
      else{hidden.add(nm);row.classList.add('off');}
      svg.querySelectorAll(`rect[data-cls="${nm}"]`).forEach(r=>r.style.display=hidden.has(nm)?'none':'');
    };
    counts.appendChild(row);
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
            self.send_error(404); return
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
            res = infer_plan.infer(pdf_path, MODEL_TS, META, THRESHOLDS)
            secs = round(time.time() - t0)
            arr = res["image"]
            buf = io.BytesIO()
            Image.fromarray(arr).save(buf, format="PNG")
            names = infer_plan.load_meta(META)
            payload = {
                "name": name,
                "w": arr.shape[1], "h": arr.shape[0],
                "image_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
                "detections": res["detections"],
                "counts": res["counts"],
                "colors": color_of(names),
                "n_tiles": res["n_tiles"], "seconds": secs,
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
    for p in (MODEL_TS, META):
        if not p.exists():
            print(f"!! manquant : {p}")
            print("   place model.ts + model_meta.json (export TorchScript du run) dans")
            print(f"   {D4}")
            return
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Comptage sur plan -> {url}")
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
