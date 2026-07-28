"""Livrable : deposer un PDF -> voir les GROUPES de symboles reconnus par apparence.

Aucun label, aucun DWG : reconnaissance pure par la forme du symbole (raster HD +
clustering par representant). Chaque groupe = un type de symbole ; la page montre sa
VIGNETTE de reference, son COMPTE, et surligne ses instances sur le plan. Tu vois
directement les correspondances (ce symbole apparait N fois, la).

Lancer :  python serve_groups.py   ->  http://localhost:8772
"""
from __future__ import annotations

import base64, cgi, io, json, tempfile, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image
import cluster_raster as cr

PORT = 8772
PREVIEW_W = 2200
MIN_GROUP = 2
PALETTE = ["#e6194b","#3cb44b","#4363d8","#f58231","#911eb4","#008080","#f032e6","#9a6324",
           "#800000","#808000","#000075","#e67e22","#16a085","#c0392b","#2980b9","#27ae60",
           "#8e44ad","#d35400","#2c3e50","#c2185b","#00838f","#5e35b1","#f57f17","#4e342e",
           "#ad1457","#0277bd","#558b2f","#ef6c00","#6a1b9a","#00695c","#bf360c","#1565c0"]


def analyze(pdf_path):
    comps, rgb, zoom_hd, lr, protos = cr.detect_components(pdf_path, dpi=200)
    groups = cr.cluster(comps)

    hd = Image.fromarray(rgb)
    scale = PREVIEW_W / hd.width
    preview = hd.resize((PREVIEW_W, int(hd.height * scale)))
    buf = io.BytesIO(); preview.save(buf, format="PNG", optimize=True)
    prev_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    def crop_thumb(b, src=hd, pad=5):
        x0 = max(0, int(b[0]*zoom_hd)-pad); y0 = max(0, int(b[1]*zoom_hd)-pad)
        x1 = min(src.width, int(b[2]*zoom_hd)+pad); y1 = min(src.height, int(b[3]*zoom_hd)+pad)
        if x1 <= x0 or y1 <= y0:
            return None
        c = src.crop((x0, y0, x1, y1)); c.thumbnail((64, 64))
        bb = io.BytesIO(); c.save(bb, format="PNG")
        return base64.b64encode(bb.getvalue()).decode("ascii")

    # ne conserver que les groupes qui correspondent a un symbole de la LEGENDE
    # (forme + taille absolue) ; on rattache la vignette du symbole de legende matche.
    kept = []
    have_legend = bool(protos)
    for g in groups:
        rep = max(g, key=lambda i: comps[i]["npix"])
        if have_legend:
            mi, iou = cr.best_legend_match(comps[rep], protos)
            if mi < 0:   # forme+couleur+taille ne correspondent a aucun symbole de legende
                continue
        else:
            # pas de legende : garde-fou anti-texte par alignement (lignes de caracteres)
            mi, iou = -1, 0.0
            if cr.group_is_text(g, comps):
                continue
        if len(g) < MIN_GROUP:
            continue
        kept.append((g, rep, mi, iou))
    kept.sort(key=lambda t: -len(t[0]))

    out_groups = []
    for gi, (g, rep, mi, iou) in enumerate(kept):
        color = PALETTE[gi % len(PALETTE)]
        boxes = []
        for i in g:
            b = comps[i]["bbox_pt"]
            boxes.append([round(b[0]*zoom_hd*scale, 1), round(b[1]*zoom_hd*scale, 1),
                          round(b[2]*zoom_hd*scale, 1), round(b[3]*zoom_hd*scale, 1)])
        leg_thumb = crop_thumb(protos[mi]["bbox_pt"]) if mi >= 0 else None
        out_groups.append({"id": gi, "count": len(g), "color": color,
                           "thumb": crop_thumb(comps[rep]["bbox_pt"]),
                           "legend_thumb": leg_thumb, "iou": round(iou, 2),
                           "boxes": boxes})

    return {"w": preview.width, "h": preview.height, "image_b64": prev_b64,
            "groups": out_groups, "n_comps": len(comps), "has_legend": have_legend,
            "n_protos": len(protos), "n_groups": len(out_groups),
            "total": sum(len(g[0]) for g in kept)}


PAGE = """<!doctype html><html lang=fr><head><meta charset=utf-8>
<title>Symboles reconnus — plan</title>
<style>
 *{box-sizing:border-box}
 body{margin:0;font:14px/1.4 system-ui,Segoe UI,sans-serif;color:#1a1a1a;background:#f4f4f5}
 header{padding:12px 18px;background:#111;color:#fff;display:flex;align-items:center;gap:16px}
 header h1{font-size:15px;margin:0;font-weight:600}
 header .sub{font-size:12px;color:#9ca3af}
 #drop{margin-left:auto} #drop label{background:#2563eb;color:#fff;padding:7px 14px;border-radius:6px;cursor:pointer;font-size:13px}
 #drop input{display:none}
 main{display:flex;height:calc(100vh - 49px)}
 #view{flex:1;overflow:hidden;position:relative;background:#e5e7eb}
 #stage{position:absolute;transform-origin:0 0} #stage img{display:block}
 #stage svg{position:absolute;top:0;left:0;pointer-events:none}
 aside{width:300px;background:#fff;border-left:1px solid #e5e7eb;display:flex;flex-direction:column}
 aside .head{padding:12px 14px;border-bottom:1px solid #eee} aside .head b{font-size:20px} aside .head .m{color:#6b7280;font-size:12px}
 #groups{overflow-y:auto;flex:1}
 .row{display:flex;align-items:center;gap:10px;padding:6px 12px;cursor:pointer;border-bottom:1px solid #f3f4f6}
 .row:hover{background:#f9fafb} .row.off{opacity:.32}
 .row .sw{width:6px;height:34px;border-radius:2px;flex:none}
 .row img{width:40px;height:34px;object-fit:contain;background:#fff;border:1px solid #eee;border-radius:4px;flex:none}
 .row .eq{color:#9ca3af;font-size:13px;flex:none}
 .row .nm{flex:1;font-size:12px;color:#6b7280} .row .n{font-variant-numeric:tabular-nums;font-weight:700;font-size:15px}
 #msg{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:12px;color:#6b7280;text-align:center;padding:20px}
 .spin{width:34px;height:34px;border:3px solid #d1d5db;border-top-color:#2563eb;border-radius:50%;animation:s 1s linear infinite}@keyframes s{to{transform:rotate(360deg)}}
 #zh{position:absolute;bottom:10px;left:12px;font-size:11px;color:#6b7280;background:rgba(255,255,255,.8);padding:3px 8px;border-radius:4px}
</style></head><body>
<header><h1>Symboles reconnus par apparence</h1><span class=sub id=meta></span>
 <span id=drop><label>Déposer un PDF<input type=file id=file accept=.pdf></label></span></header>
<main>
 <div id=view><div id=stage></div>
  <div id=msg><div>Dépose un plan PDF — les symboles identiques sont regroupés par leur forme.<br>
   <small>Aucun label, aucun DWG. Clique un groupe pour l'isoler.</small></div></div>
  <div id=zh>molette = zoom · glisser = déplacer</div></div>
 <aside><div class=head><b id=total>—</b> symboles · <span id=ng>—</span> types<div class=m id=info></div></div>
  <div id=groups></div></aside>
</main>
<script>
const view=document.getElementById('view'),stage=document.getElementById('stage'),msg=document.getElementById('msg'),groupsEl=document.getElementById('groups');
let sc=1,ox=0,oy=0,drag=false,sx=0,sy=0,hidden=new Set(),data=null,svg=null;
function apply(){stage.style.transform=`translate(${ox}px,${oy}px) scale(${sc})`}
view.addEventListener('wheel',e=>{e.preventDefault();const r=view.getBoundingClientRect();const mx=e.clientX-r.left-ox,my=e.clientY-r.top-oy;const f=e.deltaY<0?1.15:1/1.15;sc*=f;ox-=mx*(f-1);oy-=my*(f-1);apply()},{passive:false});
view.addEventListener('mousedown',e=>{drag=true;sx=e.clientX-ox;sy=e.clientY-oy});
addEventListener('mousemove',e=>{if(drag){ox=e.clientX-sx;oy=e.clientY-sy;apply()}});
addEventListener('mouseup',()=>drag=false);
document.getElementById('file').onchange=e=>{const f=e.target.files[0];if(f)run(f)};
// glisser-deposer : accepter un PDF lache n'importe ou sur la page
['dragenter','dragover'].forEach(ev=>document.addEventListener(ev,e=>{e.preventDefault();e.dataTransfer.dropEffect='copy';view.style.outline='3px dashed #2563eb'}));
['dragleave','drop'].forEach(ev=>document.addEventListener(ev,e=>{e.preventDefault();if(ev==='drop'||e.relatedTarget===null)view.style.outline=''}));
document.addEventListener('drop',e=>{e.preventDefault();const f=e.dataTransfer.files[0];if(f&&/\.pdf$/i.test(f.name))run(f);else if(f)msg.innerHTML='<div style="color:#b91c1c">Ce n\\'est pas un PDF : '+f.name+'</div>'});
async function run(f){msg.style.display='flex';msg.innerHTML='<div class=spin></div><div>Analyse…<br><small>'+f.name+'</small></div>';
 stage.innerHTML='';groupsEl.innerHTML='';document.getElementById('total').textContent='—';
 const fd=new FormData();fd.append('pdf',f);
 try{const r=await fetch('/infer',{method:'POST',body:fd});if(!r.ok)throw new Error(await r.text());data=await r.json();render()}
 catch(err){msg.innerHTML='<div style="color:#b91c1c">Erreur : '+err.message+'</div>'}}
function render(){msg.style.display='none';hidden.clear();
 const img=new Image();img.src='data:image/png;base64,'+data.image_b64;
 svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('width',data.w);svg.setAttribute('height',data.h);
 for(const g of data.groups)for(const b of g.boxes){const rc=document.createElementNS('http://www.w3.org/2000/svg','rect');
  rc.setAttribute('x',b[0]);rc.setAttribute('y',b[1]);rc.setAttribute('width',b[2]-b[0]);rc.setAttribute('height',b[3]-b[1]);
  rc.setAttribute('fill','none');rc.setAttribute('stroke',g.color);rc.setAttribute('stroke-width',2.5);rc.dataset.g=g.id;svg.appendChild(rc)}
 stage.innerHTML='';stage.appendChild(img);stage.appendChild(svg);
 const r=view.getBoundingClientRect();sc=Math.min(r.width/data.w,r.height/data.h)*0.98;ox=(r.width-data.w*sc)/2;oy=(r.height-data.h*sc)/2;apply();
 document.getElementById('total').textContent=data.total;document.getElementById('ng').textContent=data.n_groups;
 document.getElementById('info').textContent=(data.has_legend?('légende: '+data.n_protos+' symboles réf · '):'pas de légende détectée · ')+data.n_comps+' composantes · '+data.seconds+' s';
 document.getElementById('meta').textContent=data.name;
 groupsEl.innerHTML='';
 for(const g of data.groups){const row=document.createElement('div');row.className='row';
  const im=g.thumb?`<img src="data:image/png;base64,${g.thumb}">`:`<span class=sw style="background:${g.color}"></span>`;
  const leg=g.legend_thumb?`<span class=eq>≈</span><img title="symbole de la légende" src="data:image/png;base64,${g.legend_thumb}">`:'';
  const nm=g.legend_thumb?`légende · IoU ${g.iou}`:`groupe ${g.id+1}`;
  row.innerHTML=`<span class=sw style="background:${g.color}"></span>${im}${leg}<span class=nm>${nm}</span><span class=n>${g.count}</span>`;
  row.onclick=()=>{if(hidden.has(g.id)){hidden.delete(g.id);row.classList.remove('off')}else{hidden.add(g.id);row.classList.add('off')}
   svg.querySelectorAll(`rect[data-g="${g.id}"]`).forEach(r=>r.style.display=hidden.has(g.id)?'none':'')};
  groupsEl.appendChild(row)}}
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        else:
            self.send_error(404)
    def do_POST(self):
        if self.path != "/infer":
            self.send_error(404); return
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers,
                                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers["Content-Type"]})
        item = form["pdf"]; name = Path(item.filename or "plan.pdf").name
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            tf.write(item.file.read()); pdf_path = tf.name
        try:
            t0 = time.time(); res = analyze(pdf_path); res["name"] = name; res["seconds"] = round(time.time()-t0)
            body = json.dumps(res).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        except Exception as e:
            import traceback; traceback.print_exc()
            m = f"{type(e).__name__}: {e}".encode("utf-8")
            self.send_response(500); self.send_header("Content-Length", str(len(m))); self.end_headers(); self.wfile.write(m)
        finally:
            Path(pdf_path).unlink(missing_ok=True)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://localhost:{PORT}"; print(f"Symboles reconnus -> {url}")
    try: webbrowser.open(url)
    except Exception: pass
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\narret.")


if __name__ == "__main__":
    main()
