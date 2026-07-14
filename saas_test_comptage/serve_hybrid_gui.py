import hashlib
import json
import mimetypes
import os
import posixpath
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from unsupervised_kmeans_lab.run_unsupervised_kmeans import (
  DEFAULT_RUNS_DIR,
  list_pdf_runs,
  load_pdf_run,
  run_pdf_kmeans,
)


ROOT = Path(__file__).resolve().parent
HYBRID_RUNS = ROOT / "hybrid_runs"
HYBRID_FEEDBACK = ROOT / "hybrid_feedback"
UNSUPERVISED_RUNS = DEFAULT_RUNS_DIR
HOST = "127.0.0.1"
PORT = 8765


def resolve_repo_path(raw_path):
  if not raw_path:
    raise ValueError("missing path")
  candidate = (ROOT / raw_path).resolve()
  if ROOT not in candidate.parents and candidate != ROOT:
    raise ValueError("path outside repository")
  return candidate


def web_file_url(relative_path):
  normalized = relative_path.replace("\\", "/")
  return f"/api/file?path={quote(normalized)}"


def feedback_path_for_report(report_path):
  resolved = resolve_repo_path(report_path)
  relative_parent = resolved.relative_to(ROOT).parent
  return HYBRID_FEEDBACK / relative_parent / "feedback.json"


def kmeans_result_path_for_request(raw_path):
  resolved = resolve_repo_path(raw_path)
  return resolved


def summarize_report(report_path):
  data = json.loads(report_path.read_text(encoding="utf-8"))
  relative = report_path.relative_to(ROOT).as_posix()
  pages = data.get("pages", [])
  total_groups = sum(len(page.get("vector_groups", [])) for page in pages)
  total_objects = sum(group.get("count", 0) for page in pages for group in page.get("vector_groups", []))
  mode_counts = {}
  for page in pages:
    mode = page.get("profile", {}).get("mode", "unknown")
    mode_counts[mode] = mode_counts.get(mode, 0) + 1
  return {
    "title": report_path.parent.name,
    "report_path": relative,
    "pdf": data.get("pdf"),
    "page_count": len(pages),
    "total_groups": total_groups,
    "total_objects": total_objects,
    "mode_counts": mode_counts,
  }


def list_reports():
  if not HYBRID_RUNS.exists():
    return []
  reports = []
  for report_path in sorted(HYBRID_RUNS.rglob("report.json")):
    try:
      reports.append(summarize_report(report_path))
    except Exception:
      continue
  reports.sort(key=lambda item: (-item["total_objects"], item["title"].lower()))
  return reports


def list_pdfs():
  ignored_roots = {"hybrid_runs", "unsupervised_kmeans_lab", "prepared_data", "training_runs", "datasets", "__pycache__"}
  pdfs = []
  for pdf_path in ROOT.rglob("*.pdf"):
    relative = pdf_path.relative_to(ROOT)
    if any(part in ignored_roots for part in relative.parts):
      continue
    pdfs.append(
      {
        "title": pdf_path.stem,
        "pdf_path": relative.as_posix(),
        "pdf_name": pdf_path.name,
        "folder": relative.parent.as_posix(),
      }
    )
  pdfs.sort(key=lambda item: (item["folder"].lower(), item["pdf_name"].lower()))
  return pdfs


def enrich_report(data):
  pages = data.get("pages", [])
  aggregated = {}
  legend_catalog = {}

  for page in pages:
    preview = page.get("preview")
    if preview:
      page["preview_url"] = web_file_url(preview)
    for entry in page.get("legend_entries", []):
      if entry.get("sample_image"):
        entry["sample_image_url"] = web_file_url(entry["sample_image"])
      signature = hashlib.sha1(entry.get("text", "").encode("utf-8")).hexdigest()
      legend_catalog[signature] = {
        "signature": signature,
        "sample_image_url": entry.get("sample_image_url"),
        "bbox_size": None,
        "items_len": 0,
        "stroke_width": 0.0,
        "color": None,
        "fill": None,
        "match_rgb": entry.get("match_rgb"),
        "label_guess": entry.get("text"),
        "label_score": None,
        "shape_score": None,
        "color_score": None,
        "proposal_region": None,
        "total_count": 0,
        "page_occurrences": 0,
        "pages": [],
      }
    page_total = 0
    for group in page.get("vector_groups", []):
      sample_image = group.get("sample_image")
      if sample_image:
        group["sample_image_url"] = web_file_url(sample_image)
      page_total += int(group.get("count", 0))

      signature = group["signature"]
      aggregate = aggregated.setdefault(
        signature,
        {
          "signature": signature,
          "sample_image_url": group.get("sample_image_url"),
          "bbox_size": group.get("bbox_size"),
          "items_len": group.get("items_len"),
          "stroke_width": group.get("stroke_width"),
          "color": group.get("color"),
          "fill": group.get("fill"),
          "match_rgb": group.get("match_rgb"),
          "label_guess": group.get("label_guess"),
          "label_score": group.get("label_score"),
          "shape_score": group.get("shape_score"),
          "color_score": group.get("color_score"),
          "proposal_region": group.get("proposal_region"),
          "dominant_scale": group.get("dominant_scale"),
          "similarity_mode": group.get("similarity_mode"),
          "total_count": 0,
          "page_occurrences": 0,
          "pages": [],
        },
      )
      aggregate["total_count"] += int(group.get("count", 0))
      aggregate["page_occurrences"] += 1
      aggregate["pages"].append({"page": page.get("page"), "count": int(group.get("count", 0))})
    page["total_detected_objects"] = page_total

  aggregated_groups = sorted(
    [aggregated.get(signature, item) for signature, item in legend_catalog.items()] + [
      item for signature, item in aggregated.items() if signature not in legend_catalog
    ],
    key=lambda item: (-item["total_count"], -item["page_occurrences"], item["signature"]),
  )

  return {
    "pdf": data.get("pdf"),
    "page_count": data.get("page_count"),
    "pages": pages,
    "aggregated_groups": aggregated_groups,
    "totals": {
      "pages": len(pages),
      "groups": sum(len(page.get("vector_groups", [])) for page in pages),
      "objects": sum(page.get("total_detected_objects", 0) for page in pages),
    },
  }


class HybridGuiHandler(SimpleHTTPRequestHandler):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, directory=str(ROOT), **kwargs)

  def do_GET(self):
    parsed = urlparse(self.path)
    if parsed.path == "/api/reports":
      return self.handle_reports()
    if parsed.path == "/api/pdfs":
      return self.handle_pdfs()
    if parsed.path == "/api/report":
      return self.handle_report(parsed.query)
    if parsed.path == "/api/feedback":
      return self.handle_feedback(parsed.query)
    if parsed.path == "/api/unsupervised/runs":
      return self.handle_unsupervised_runs(parsed.query)
    if parsed.path == "/api/unsupervised/run":
      return self.handle_unsupervised_run(parsed.query)
    if parsed.path == "/api/file":
      return self.handle_file(parsed.query)
    return super().do_GET()

  def do_POST(self):
    parsed = urlparse(self.path)
    if parsed.path == "/api/feedback/save":
      return self.handle_feedback_save()
    if parsed.path == "/api/unsupervised/run":
      return self.handle_unsupervised_run_post()
    self.send_error(HTTPStatus.NOT_FOUND, "unknown endpoint")

  def translate_path(self, path):
    path = path.split("?", 1)[0].split("#", 1)[0]
    path = posixpath.normpath(unquote(path))
    parts = [part for part in path.split("/") if part and part != ".."]
    resolved = ROOT
    for part in parts:
      resolved = resolved / part
    return str(resolved)

  def send_json(self, payload, status=HTTPStatus.OK):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    self.send_response(status)
    self.send_header("Content-Type", "application/json; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)

  def handle_reports(self):
    return self.send_json({"reports": list_reports()})

  def handle_pdfs(self):
    return self.send_json({"pdfs": list_pdfs()})

  def handle_report(self, query):
    params = parse_qs(query)
    report_path = params.get("path", [None])[0]
    try:
      resolved = resolve_repo_path(report_path)
    except ValueError as exc:
      return self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    if not resolved.exists():
      return self.send_json({"error": "report not found"}, status=HTTPStatus.NOT_FOUND)

    data = json.loads(resolved.read_text(encoding="utf-8"))
    return self.send_json(enrich_report(data))

  def handle_feedback(self, query):
    params = parse_qs(query)
    report_path = params.get("path", [None])[0]
    try:
      resolved = resolve_repo_path(report_path)
      feedback_path = feedback_path_for_report(report_path)
    except ValueError as exc:
      return self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    if not resolved.exists():
      return self.send_json({"error": "report not found"}, status=HTTPStatus.NOT_FOUND)

    if feedback_path.exists():
      payload = json.loads(feedback_path.read_text(encoding="utf-8"))
    else:
      payload = {
        "report_path": resolved.relative_to(ROOT).as_posix(),
        "saved_at": None,
        "legend_feedback": {},
        "group_feedback": {},
      }
    return self.send_json(payload)

  def handle_feedback_save(self):
    try:
      content_length = int(self.headers.get("Content-Length", "0"))
    except ValueError:
      content_length = 0
    if content_length <= 0:
      return self.send_json({"error": "missing body"}, status=HTTPStatus.BAD_REQUEST)

    raw_body = self.rfile.read(content_length)
    try:
      payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
      return self.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)

    report_path = payload.get("report_path")
    if not report_path:
      return self.send_json({"error": "missing report_path"}, status=HTTPStatus.BAD_REQUEST)

    try:
      resolve_repo_path(report_path)
      feedback_path = feedback_path_for_report(report_path)
    except ValueError as exc:
      return self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    payload["saved_at"] = datetime.now().isoformat(timespec="seconds")
    feedback_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return self.send_json(
      {
        "ok": True,
        "saved_at": payload["saved_at"],
        "feedback_path": feedback_path.relative_to(ROOT).as_posix(),
      }
    )

  def handle_unsupervised_runs(self, query):
    params = parse_qs(query)
    pdf_path = params.get("pdf_path", [None])[0]
    runs = list_pdf_runs(UNSUPERVISED_RUNS, pdf_path=pdf_path)
    return self.send_json({"runs": runs})

  def handle_unsupervised_run(self, query):
    params = parse_qs(query)
    result_path = params.get("path", [None])[0]
    if not result_path:
      return self.send_json({"error": "missing path"}, status=HTTPStatus.BAD_REQUEST)

    try:
      resolved = kmeans_result_path_for_request(result_path)
    except ValueError as exc:
      return self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    if not resolved.exists():
      return self.send_json({"error": "run not found"}, status=HTTPStatus.NOT_FOUND)

    data = load_pdf_run(resolved)
    if data.get("summary_csv"):
      data["summary_csv_url"] = web_file_url(data["summary_csv"])
    for legend in data.get("legend_items", []):
      if legend.get("sample_image"):
        legend["sample_image_url"] = web_file_url(legend["sample_image"])
      if legend.get("contact_sheet"):
        legend["contact_sheet_url"] = web_file_url(legend["contact_sheet"])
      if legend.get("matches_export"):
        legend["matches_export_url"] = web_file_url(legend["matches_export"])
      for sample in legend.get("matches", []):
        if sample.get("image_path"):
          sample["image_url"] = web_file_url(sample["image_path"])
    return self.send_json(data)

  def handle_unsupervised_run_post(self):
    try:
      content_length = int(self.headers.get("Content-Length", "0"))
    except ValueError:
      content_length = 0
    if content_length <= 0:
      return self.send_json({"error": "missing body"}, status=HTTPStatus.BAD_REQUEST)

    raw_body = self.rfile.read(content_length)
    try:
      payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
      return self.send_json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)

    pdf_path = payload.get("pdf_path")
    if not pdf_path:
      return self.send_json({"error": "missing pdf_path"}, status=HTTPStatus.BAD_REQUEST)

    try:
      resolve_repo_path(pdf_path)
      result_path = run_pdf_kmeans(
        pdf_path,
        output_root=UNSUPERVISED_RUNS,
        max_components_per_page=int(payload.get("max_components_per_page", 180)),
        sample_size=int(payload.get("sample_size", 32)),
        pages=payload.get("pages"),
        match_threshold=float(payload.get("match_threshold", 0.44)),
      )
    except Exception as exc:
      return self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    return self.send_json(
      {
        "ok": True,
        "result_path": result_path.relative_to(ROOT).as_posix(),
      }
    )

  def handle_file(self, query):
    params = parse_qs(query)
    file_path = params.get("path", [None])[0]
    try:
      resolved = resolve_repo_path(file_path)
    except ValueError:
      self.send_error(HTTPStatus.BAD_REQUEST, "invalid path")
      return

    if not resolved.exists() or not resolved.is_file():
      self.send_error(HTTPStatus.NOT_FOUND, "file not found")
      return

    ctype = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
    stat = resolved.stat()
    self.send_response(HTTPStatus.OK)
    self.send_header("Content-Type", ctype)
    self.send_header("Content-Length", str(stat.st_size))
    self.end_headers()
    with resolved.open("rb") as stream:
      self.copyfile(stream, self.wfile)


def main():
  server = ThreadingHTTPServer((HOST, PORT), HybridGuiHandler)
  print(f"Hybrid GUI server on http://{HOST}:{PORT}/hybrid_viewer/")
  try:
    server.serve_forever()
  except KeyboardInterrupt:
    pass
  finally:
    server.server_close()


if __name__ == "__main__":
  main()
