"""Interface web locale pour importer un PDF et compter les objets de la legende.

Zero dependance en plus (http.server de la stdlib + pymupdf deja present).
Lancer : python serve.py  ->  http://localhost:8765
"""
from __future__ import annotations

import base64
import html
import io
import socketserver
import sys
import tempfile
import webbrowser
from email.parser import BytesParser
from email.policy import default as email_default
from http.server import BaseHTTPRequestHandler
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from pdf_takeoff import count_pdf, overlay_svg_pdf  # noqa: E402
from takeoff import count_dwg_file  # noqa: E402

PORT = 8765

PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4",
           "#f032e6", "#bfef45", "#469990", "#9a6324", "#800000", "#808000"]


def color_for(label: str) -> str:
    return PALETTE[hash(label) % len(PALETTE)]


PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Comptage plans - import PDF</title>
<style>
  :root{--blue:#21479b;--ink:#182033;--muted:#5c667a;--line:#d9e2f1;--ok:#1f8a3c;--red:#b42318}
  *{box-sizing:border-box}
  body{font-family:"Segoe UI",Arial,sans-serif;margin:0;background:#f4f6fa;color:var(--ink)}
  header{background:var(--blue);color:#fff;padding:18px 28px}
  header h1{margin:0;font-size:20px}
  header p{margin:4px 0 0;font-size:13px;opacity:.85}
  main{max-width:1200px;margin:24px auto;padding:0 20px}
  .drop{border:2px dashed var(--blue);border-radius:12px;background:#fff;padding:40px;text-align:center;
        transition:.15s;cursor:pointer}
  .drop.hover{background:#eef2fd;border-color:#153172}
  .drop h2{margin:0 0 8px;color:var(--blue);font-size:18px}
  .drop p{margin:4px 0;color:var(--muted);font-size:14px}
  .btn{display:inline-block;margin-top:12px;background:var(--blue);color:#fff;border:none;border-radius:8px;
       padding:10px 22px;font-size:15px;font-weight:600;cursor:pointer}
  .btn:hover{background:#153172}
  #status{margin-top:16px;font-size:14px;color:var(--muted);min-height:20px}
  .spin{display:inline-block;width:16px;height:16px;border:3px solid #cdd6e8;border-top-color:var(--blue);
        border-radius:50%;animation:spin .8s linear infinite;vertical-align:middle;margin-right:8px}
  @keyframes spin{to{transform:rotate(360deg)}}
  #results{margin-top:28px}
  .plan{background:#fff;border:1px solid var(--line);border-radius:10px;margin-bottom:24px;overflow:hidden}
  .plan h3{margin:0;padding:14px 18px;background:#eef2fa;color:#17366f;font-size:16px}
  .plan .body{padding:16px 18px}
  .badge{display:inline-block;background:var(--blue);color:#fff;border-radius:8px;padding:2px 10px;font-size:13px;font-weight:600}
  table{border-collapse:collapse;width:100%;margin-top:12px}
  th,td{border:1px solid var(--line);padding:6px 10px;font-size:13px;text-align:left}
  th{background:#f4f7fc}
  td.n{text-align:right;font-weight:700}
  .dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle}
  .thumb img{max-width:56px;max-height:40px;vertical-align:middle}
  .warn{color:#a15c00;background:#fff6e6;border:1px solid #ffd98a;border-radius:6px;padding:8px 12px;margin-top:12px;font-size:13px}
  .err{color:var(--red);font-weight:700}
  details{margin-top:14px}
  summary{cursor:pointer;color:var(--blue);font-weight:600;font-size:14px}
  .ovwrap{margin-top:10px;border:1px solid var(--line);border-radius:8px;overflow:auto;max-height:640px;background:#fbfcfe}
  .ovwrap svg{display:block;max-width:100%;height:auto}
  .dl{display:inline-block;margin-top:12px;font-size:13px;color:var(--blue)}
</style></head>
<body>
<header>
  <h1>Comptage des objets de legende</h1>
  <p>Depose un plan <b>PDF</b> (estimation par forme) ou un <b>DWG</b> (comptage exact) : les symboles de la legende sont comptes automatiquement.</p>
</header>
<main>
  <form id="f">
    <label class="drop" id="drop" for="file">
      <h2>Glisse un ou plusieurs plans ici</h2>
      <p>PDF (estimation) ou DWG (exact) &mdash; ou</p>
      <span class="btn">Choisir des fichiers</span>
      <p style="margin-top:14px" id="fname"></p>
      <input type="file" id="file" name="file" accept=".pdf,.dwg" multiple hidden>
    </label>
    <div id="status"></div>
  </form>
  <div id="results"></div>
</main>
<script>
const drop=document.getElementById('drop'), input=document.getElementById('file'),
      status=document.getElementById('status'), results=document.getElementById('results'),
      fname=document.getElementById('fname');
['dragenter','dragover'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add('hover');}));
['dragleave','drop'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove('hover');}));
drop.addEventListener('drop',ev=>{ if(ev.dataTransfer.files.length){ input.files=ev.dataTransfer.files; send(); }});
input.addEventListener('change',send);
function send(){
  if(!input.files.length) return;
  const names=[...input.files].map(f=>f.name).join(', ');
  fname.textContent=names;
  status.innerHTML='<span class="spin"></span>Analyse en cours ('+input.files.length+' fichier'+(input.files.length>1?'s':'')+')...';
  results.innerHTML='';
  const fd=new FormData();
  for(const f of input.files) fd.append('file',f);
  fetch('/count',{method:'POST',body:fd})
    .then(r=>r.text()).then(html=>{ status.innerHTML=''; results.innerHTML=html; })
    .catch(e=>{ status.innerHTML='<span class="err">Erreur : '+e+'</span>'; });
}
</script>
</body></html>"""


CONF_BADGE = {
    "exact": ('<span style="background:#1f8a3c;color:#fff;border-radius:6px;padding:1px 7px;font-size:11px">exact</span>', ""),
    "match": ('<span style="background:#1f8a3c;color:#fff;border-radius:6px;padding:1px 7px;font-size:11px">= QTE</span>', ""),
    "diff":  ('<span style="background:#d97706;color:#fff;border-radius:6px;padding:1px 7px;font-size:11px">a verifier</span>', ""),
    "estim": ('<span style="background:#6b7280;color:#fff;border-radius:6px;padding:1px 7px;font-size:11px">estim.</span>', ""),
}


def render_result(name: str, res: dict, src_path: Path) -> str:
    source = res.get("source", "PDF (estimation)")
    is_dwg = source.startswith("DWG")
    if not res.get("rows"):
        w = "; ".join(res.get("warnings") or []) or "aucune legende exploitable"
        return (f'<div class="plan"><h3>{html.escape(name)}</h3>'
                f'<div class="body"><p class="err">Non compte : {html.escape(w)}</p></div></div>')
    rows = res["rows"]
    total = sum(r["count"] for r in rows)
    has_decl = any(r.get("qty_declared") is not None for r in rows)
    src_color = "#1f8a3c" if is_dwg else "#21479b"
    parts = [f'<div class="plan"><h3>{html.escape(name)}</h3><div class="body">',
             f'<span class="badge">{total} objets comptes</span> '
             f'<span class="badge" style="background:{src_color}">source : {html.escape(source)}</span>']
    if res.get("warnings"):
        parts.append(f'<div class="warn">{html.escape("; ".join(res["warnings"]))}</div>')
    decl_th = "<th>QTE legende</th>" if has_decl else ""
    parts.append(f'<table><tr><th></th><th>Symbole</th><th>Calque/zone</th><th>Qte</th>'
                 f'<th>Confiance</th>{decl_th}</tr>')
    thumbs = res.get("thumbs") or {}
    thumbs_svg = res.get("thumbs_svg") or {}
    for r in rows:
        if r["label"] in thumbs_svg:
            thumb = thumbs_svg[r["label"]]
        elif r["label"] in thumbs:
            thumb = f'<img src="data:image/png;base64,{thumbs[r["label"]]}">'
        else:
            thumb = ""
        dot = f'<span class="dot" style="background:{color_for(r["label"])}"></span>'
        conf = r.get("conf", "exact" if is_dwg else "estim")
        conf_td = CONF_BADGE.get(conf, ("", ""))[0]
        decl_td = ""
        if has_decl:
            q = r.get("qty_declared")
            decl_td = "<td></td>" if q is None else f'<td class="n">{q}</td>'
        loc = r.get("layer", "")
        if r.get("zone"):
            loc = (loc + " / " + r["zone"]).strip(" /")
        parts.append(
            f'<tr><td class="thumb">{thumb}</td>'
            f'<td>{dot}{html.escape(r["display"])}</td>'
            f'<td>{html.escape(loc)}</td>'
            f'<td class="n">{r["count"]}</td>'
            f'<td>{conf_td}</td>{decl_td}</tr>')
    parts.append("</table>")

    # CSV telechargeable (data URI)
    csv_lines = ["symbole;calque;zone;quantite;confiance;qte_declaree"]
    for r in rows:
        csv_lines.append(f'{r["display"]};{r.get("layer","")};{r.get("zone","")};{r["count"]};'
                         f'{r.get("conf","")};{r.get("qty_declared","")}')
    csv_b64 = base64.b64encode(("﻿" + "\n".join(csv_lines)).encode("utf-8")).decode("ascii")
    parts.append(f'<a class="dl" download="{html.escape(name)}.csv" '
                 f'href="data:text/csv;base64,{csv_b64}">Telecharger le CSV</a>')

    # overlay
    if res.get("overlay_svg"):  # DWG
        parts.append(f'<details><summary>Voir l\'overlay du plan</summary>'
                     f'<div class="ovwrap">{res["overlay_svg"]}</div></details>')
    for ov in res.get("overlays") or []:  # PDF
        try:
            svg = overlay_svg_pdf(src_path, ov)
        except Exception:
            continue
        label = f'Overlay (page {ov["page"] + 1})' if len(res["overlays"]) > 1 else "Voir l'overlay du plan"
        parts.append(f'<details><summary>{label}</summary><div class="ovwrap">{svg}</div></details>')
    parts.append("</div></div>")
    return "".join(parts)


def parse_files(headers, body: bytes):
    ctype = headers.get("Content-Type", "")
    raw = b"Content-Type: " + ctype.encode("latin-1") + b"\r\n\r\n" + body
    msg = BytesParser(policy=email_default).parsebytes(raw)
    files = []
    for part in msg.iter_parts():
        if part.get_filename():
            payload = part.get_payload(decode=True)
            if payload:
                files.append((part.get_filename(), payload))
    return files


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body: bytes, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"))
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/count":
            self._send(404, b"not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            files = parse_files(self.headers, body)
        except Exception as e:
            self._send(200, f'<p class="err">Lecture impossible : {html.escape(str(e))}</p>'.encode("utf-8"))
            return
        if not files:
            self._send(200, b'<p class="err">Aucun fichier recu.</p>')
            return
        out = []
        for fname, data in files:
            ext = ".dwg" if fname.lower().endswith(".dwg") else ".pdf"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
                tf.write(data)
                tmp = Path(tf.name)
            try:
                if ext == ".dwg":
                    res = count_dwg_file(tmp)
                    out.append(render_result(fname, res, tmp))
                else:
                    res = count_pdf(tmp)
                    res.setdefault("source", "PDF (estimation)")
                    out.append(render_result(fname, res, tmp))
            except Exception as e:
                import traceback as tb
                tb.print_exc()
                out.append(f'<div class="plan"><h3>{html.escape(fname)}</h3><div class="body">'
                           f'<p class="err">Erreur : {html.escape(str(e))}</p></div></div>')
            finally:
                try:
                    tmp.unlink()
                except OSError:
                    pass
        self._send(200, "".join(out).encode("utf-8"))

    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    port = PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    url = f"http://localhost:{port}/"
    print(f"Interface de comptage : {url}")
    print("Ferme cette fenetre pour arreter le serveur.")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    with Server(("127.0.0.1", port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
