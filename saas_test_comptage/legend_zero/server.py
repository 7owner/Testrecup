import json
import mimetypes
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from .pdf_utils import resolve_repo_pdf_path
from .kmeans_matcher import match_legend_object_kmeans
from .plan_matcher import match_legend_object
from .pipeline import export_index, list_project_pdfs, run_legend_extraction
from .settings import HOST, PORT, REPO_ROOT, UPLOADS_DIR, WEB_DIR
from .vector_inspector import inspect_pdf_vectors


MATCH_JOBS = {}
MATCH_JOBS_LOCK = threading.Lock()


def _resolve_repo_file(raw_path):
  candidate = (REPO_ROOT / raw_path).resolve()
  if REPO_ROOT not in candidate.parents and candidate != REPO_ROOT:
    raise ValueError("Chemin hors depot.")
  return candidate


def web_file_url(relative_path):
  return f"/api/file?path={quote(relative_path.replace(chr(92), '/'))}"


def enrich_result(result):
  payload = dict(result)
  payload["preview_url"] = web_file_url(result["preview_path"])
  for item in payload["objects"]:
    item["crop_url"] = web_file_url(item["crop_path"])
    item["binary_crop_url"] = web_file_url(item["binary_crop_path"])
  for page in payload["page_summaries"]:
    page["preview_url"] = web_file_url(page["preview_path"])
  return payload


def enrich_match_result(result):
  payload = dict(result)
  for page in payload["pages"]:
    page["preview_url"] = web_file_url(page["preview_path"])
    if page.get("counted_items_path"):
      page["counted_items_url"] = web_file_url(page["counted_items_path"])
  return payload


def enrich_vector_result(result):
  payload = dict(result)
  for page in payload["pages"]:
    page["preview_url"] = web_file_url(page["preview_path"])
  return payload


def create_match_job(pdf_path, page_spec, obj_payload, mode="direct"):
  if mode not in {"direct", "kmeans_strict"}:
    raise ValueError("Mode de recherche inconnu.")
  job_id = uuid.uuid4().hex
  with MATCH_JOBS_LOCK:
    MATCH_JOBS[job_id] = {
      "job_id": job_id,
      "status": "queued",
      "message": "Job en attente.",
      "created_at": time.time(),
      "updated_at": time.time(),
      "result": None,
      "error": None,
      "label": obj_payload.get("label"),
      "mode": mode,
      "pdf_path": pdf_path,
    }

  worker = threading.Thread(
    target=run_match_job,
    args=(job_id, pdf_path, page_spec, obj_payload, mode),
    daemon=True,
  )
  worker.start()
  return job_id


def run_match_job(job_id, pdf_path, page_spec, obj_payload, mode):
  with MATCH_JOBS_LOCK:
    job = MATCH_JOBS.get(job_id)
    if not job:
      return
    job["status"] = "running"
    job["message"] = "Recherche KMeans stricte en cours." if mode == "kmeans_strict" else "Recherche en cours."
    job["updated_at"] = time.time()

  try:
    if mode == "kmeans_strict":
      result = match_legend_object_kmeans(pdf_path, obj_payload, page_spec=page_spec)
    else:
      result = match_legend_object(pdf_path, obj_payload, page_spec=page_spec)
    enriched = enrich_match_result(result)
    with MATCH_JOBS_LOCK:
      job = MATCH_JOBS.get(job_id)
      if not job:
        return
      job["status"] = "done"
      job["message"] = "Recherche terminee."
      job["result"] = enriched
      job["updated_at"] = time.time()
  except Exception as exc:
    with MATCH_JOBS_LOCK:
      job = MATCH_JOBS.get(job_id)
      if not job:
        return
      job["status"] = "error"
      job["message"] = str(exc)
      job["error"] = str(exc)
      job["updated_at"] = time.time()


def get_match_job(job_id):
  with MATCH_JOBS_LOCK:
    job = MATCH_JOBS.get(job_id)
    if not job:
      return None
    return dict(job)


class LegendZeroHandler(SimpleHTTPRequestHandler):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, directory=str(WEB_DIR), **kwargs)

  def do_GET(self):
    parsed = urlparse(self.path)
    if parsed.path == "/api/pdfs":
      return self.send_json({"pdfs": list_project_pdfs(), "runs": export_index()})
    if parsed.path == "/api/job-status":
      return self.handle_job_status(parsed.query)
    if parsed.path == "/favicon.ico":
      self.send_response(HTTPStatus.NO_CONTENT)
      self.end_headers()
      return
    if parsed.path == "/api/file":
      return self.handle_file(parsed.query)
    return super().do_GET()

  def do_POST(self):
    parsed = urlparse(self.path)
    if parsed.path == "/api/upload":
      return self.handle_upload(parsed.query)
    if parsed.path == "/api/extract":
      return self.handle_extract()
    if parsed.path == "/api/match-object":
      return self.handle_match_object()
    if parsed.path == "/api/vector-inspect":
      return self.handle_vector_inspect()
    self.send_error(HTTPStatus.NOT_FOUND, "unknown endpoint")

  def send_json(self, payload, status=HTTPStatus.OK):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    self.send_response(status)
    self.send_header("Content-Type", "application/json; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)

  def handle_extract(self):
    content_length = int(self.headers.get("Content-Length", "0"))
    raw_body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
    payload = json.loads(raw_body)
    pdf_path = payload.get("pdf_path")
    pages = payload.get("pages") or None
    try:
      resolve_repo_pdf_path(pdf_path)
      result = run_legend_extraction(pdf_path, pages)
    except Exception as exc:
      print(f"[LegendZero] extract error pdf={pdf_path!r} pages={pages!r}: {exc}", file=sys.stderr, flush=True)
      return self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
    return self.send_json({"result": enrich_result(result)})

  def handle_upload(self, query):
    params = parse_qs(query)
    raw_name = params.get("name", [None])[0]
    if not raw_name:
      print("[LegendZero] upload error: missing filename", file=sys.stderr, flush=True)
      return self.send_json({"error": "Nom de fichier manquant."}, status=HTTPStatus.BAD_REQUEST)

    filename = Path(unquote(raw_name)).name
    if not filename.lower().endswith(".pdf"):
      print(f"[LegendZero] upload error: invalid extension for {filename!r}", file=sys.stderr, flush=True)
      return self.send_json({"error": "Seuls les PDF sont acceptes."}, status=HTTPStatus.BAD_REQUEST)

    content_length = int(self.headers.get("Content-Length", "0"))
    if content_length <= 0:
      print(f"[LegendZero] upload error: empty file for {filename!r}", file=sys.stderr, flush=True)
      return self.send_json({"error": "Fichier vide."}, status=HTTPStatus.BAD_REQUEST)

    body = self.rfile.read(content_length)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOADS_DIR / filename
    target.write_bytes(body)
    return self.send_json(
      {
        "uploaded": {
          "name": filename,
          "relative_path": target.relative_to(REPO_ROOT).as_posix(),
          "folder": target.parent.relative_to(REPO_ROOT).as_posix(),
          "source": "upload",
        }
      }
    )

  def handle_match_object(self):
    content_length = int(self.headers.get("Content-Length", "0"))
    raw_body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
    payload = json.loads(raw_body)
    try:
      pdf_path = payload.get("pdf_path")
      obj_payload = payload.get("object") or {}
      mode = payload.get("mode") or "direct"
      job_id = create_match_job(pdf_path, payload.get("pages") or None, obj_payload, mode=mode)
    except Exception as exc:
      print(
        f"[LegendZero] match error pdf={payload.get('pdf_path')!r} object={payload.get('object', {}).get('id')!r}: {exc}",
        file=sys.stderr,
        flush=True,
      )
      return self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
    return self.send_json({"job_id": job_id, "status": "queued"})

  def handle_vector_inspect(self):
    content_length = int(self.headers.get("Content-Length", "0"))
    raw_body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
    payload = json.loads(raw_body)
    pdf_path = payload.get("pdf_path")
    pages = payload.get("pages") or None
    try:
      resolve_repo_pdf_path(pdf_path)
      result = inspect_pdf_vectors(pdf_path, pages)
    except Exception as exc:
      print(f"[LegendZero] vector inspect error pdf={pdf_path!r} pages={pages!r}: {exc}", file=sys.stderr, flush=True)
      return self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
    return self.send_json({"result": enrich_vector_result(result)})

  def handle_job_status(self, query):
    params = parse_qs(query)
    job_id = params.get("id", [None])[0]
    if not job_id:
      return self.send_json({"error": "Job manquant."}, status=HTTPStatus.BAD_REQUEST)
    job = get_match_job(job_id)
    if not job:
      return self.send_json({"error": "Job introuvable."}, status=HTTPStatus.NOT_FOUND)

    payload = {
      "job_id": job["job_id"],
      "status": job["status"],
      "message": job["message"],
      "label": job.get("label"),
      "mode": job.get("mode"),
      "pdf_path": job.get("pdf_path"),
      "created_at": job["created_at"],
      "updated_at": job["updated_at"],
    }
    if job["status"] == "done":
      payload["result"] = job["result"]
    if job["status"] == "error":
      payload["error"] = job["error"]
    return self.send_json(payload)

  def handle_file(self, query):
    params = parse_qs(query)
    raw_path = params.get("path", [None])[0]
    try:
      file_path = _resolve_repo_file(unquote(raw_path))
    except Exception as exc:
      return self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
    if not file_path.exists() or not file_path.is_file():
      return self.send_json({"error": "Fichier introuvable."}, status=HTTPStatus.NOT_FOUND)

    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    body = file_path.read_bytes()
    self.send_response(HTTPStatus.OK)
    self.send_header("Content-Type", content_type)
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)


def run_server():
  server = ThreadingHTTPServer((HOST, PORT), LegendZeroHandler)
  print(f"Legend Zero server: http://{HOST}:{PORT}")
  server.serve_forever()


__all__ = ["run_server"]
