import json
import mimetypes
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from .common import load_json, save_json
from legend_zero.pdf_utils import list_project_pdfs, resolve_repo_pdf_path
from legend_zero.pipeline import run_legend_extraction
from legend_zero.plan_matcher import match_legend_object
from legend_zero.kmeans_matcher import match_legend_object_kmeans


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
WEB_DIR = PACKAGE_DIR / "web"
HOST = "127.0.0.1"
PORT = 8872


def web_file_url(relative_path):
  return f"/api/file?path={quote(relative_path.replace(chr(92), '/'))}"


def resolve_repo_file(raw_path):
  candidate = (REPO_ROOT / raw_path).resolve()
  if REPO_ROOT not in candidate.parents and candidate != REPO_ROOT:
    raise ValueError("Chemin hors depot.")
  return candidate


def safe_load_json(path):
  path = Path(path)
  if not path.exists():
    return None
  try:
    return load_json(path)
  except Exception:
    return None


def gather_dataset_stats():
  root = REPO_ROOT / "instance_seg" / "data" / "plans_coco"
  categories_template = safe_load_json(root.parent / "categories_template.json") or {}
  splits = []
  for split_name in ["train", "val", "test"]:
    split_root = root / split_name
    annotations_path = split_root / "annotations.json"
    data = safe_load_json(annotations_path) or {"images": [], "annotations": [], "categories": []}
    images = data.get("images", [])
    annotations = data.get("annotations", [])
    annotated_image_ids = {item.get("image_id") for item in annotations}
    splits.append(
      {
        "name": split_name,
        "images": len(images),
        "annotations": len(annotations),
        "annotated_images": len(annotated_image_ids),
        "categories": len(data.get("categories", [])),
        "annotations_path": str(annotations_path.relative_to(REPO_ROOT).as_posix()) if annotations_path.exists() else None,
      }
    )
  return {
    "root": str(root.relative_to(REPO_ROOT).as_posix()),
    "categories_template_count": len(categories_template.get("categories", [])),
    "splits": splits,
  }


def gather_runtime_stats():
  runtime = {
    "python": None,
    "torch": None,
    "torchvision": None,
    "maskrcnn_ready": False,
  }
  try:
    import torch
    runtime["torch"] = torch.__version__
    runtime["python"] = str(Path(torch.__file__).resolve())
  except Exception:
    return runtime

  try:
    import torchvision
    runtime["torchvision"] = torchvision.__version__
  except Exception:
    return runtime

  try:
    from .modeling import build_maskrcnn_model
    model = build_maskrcnn_model(num_classes=2, pretrained_backbone=False)
    runtime["maskrcnn_ready"] = model is not None
  except Exception:
    runtime["maskrcnn_ready"] = False
  return runtime


def gather_training_runs():
  runs_root = REPO_ROOT / "training_runs"
  items = []
  if not runs_root.exists():
    return items
  for run_dir in sorted([path for path in runs_root.iterdir() if path.is_dir()]):
    summary = safe_load_json(run_dir / "summary.json") or {}
    run_info = safe_load_json(run_dir / "run_info.json") or {}
    item = {
      "name": run_dir.name,
      "type": "legacy_classification",
      "run_dir": str(run_dir.relative_to(REPO_ROOT).as_posix()),
      "best_val_loss": summary.get("best_val_loss"),
      "best_val_accuracy": summary.get("best_val_accuracy"),
      "num_classes": run_info.get("num_classes"),
      "train_samples": run_info.get("train_samples"),
      "val_samples": run_info.get("val_samples"),
      "curve_urls": {},
    }
    for image_name in ["loss_curve.png", "accuracy_curve.png", "precision_curve.png", "recall_curve.png", "f1_curve.png"]:
      image_path = run_dir / image_name
      if image_path.exists():
        item["curve_urls"][image_name] = web_file_url(image_path.relative_to(REPO_ROOT).as_posix())
    items.append(item)
  return items


def gather_instance_outputs():
  outputs_root = REPO_ROOT / "outputs" / "instance_seg"
  items = []
  if not outputs_root.exists():
    return items
  for summary_path in sorted(outputs_root.rglob("summary.json")):
    summary = safe_load_json(summary_path) or {}
    pages = summary.get("pages", [])
    items.append(
      {
        "name": summary_path.parent.name,
        "summary_path": str(summary_path.relative_to(REPO_ROOT).as_posix()),
        "page_count": len(pages),
        "instance_count": sum(int(page.get("instance_count", 0)) for page in pages),
        "pages": [
          {
            "name": page.get("name"),
            "page": page.get("page"),
            "instance_count": page.get("instance_count", 0),
            "counts": page.get("counts", {}),
            "preview_url": web_file_url(Path(page.get("preview_path", "")).relative_to(REPO_ROOT).as_posix()) if page.get("preview_path") else None,
          }
          for page in pages
        ],
      }
    )
  return items


def gather_improvements():
  payload = safe_load_json(REPO_ROOT / "instance_seg" / "reports" / "improvements.json") or {}
  return payload.get("items", [])


def _coco_annotations_path(split):
  if split not in {"train", "val", "test"}:
    raise ValueError("Split invalide.")
  return REPO_ROOT / "instance_seg" / "data" / "plans_coco" / split / "annotations.json"


def gather_annotation_state(split):
  annotations_path = _coco_annotations_path(split)
  data = safe_load_json(annotations_path) or {"images": [], "annotations": [], "categories": []}
  annotations_by_image = {}
  for annotation in data.get("annotations", []):
    annotations_by_image.setdefault(annotation.get("image_id"), []).append(annotation)

  images = []
  for image in sorted(data.get("images", []), key=lambda item: item.get("id", 0)):
    image_annotations = annotations_by_image.get(image.get("id"), [])
    relative_image_path = Path("instance_seg") / "data" / "plans_coco" / split / "images" / image["file_name"]
    images.append(
      {
        "id": image["id"],
        "file_name": image["file_name"],
        "width": image["width"],
        "height": image["height"],
        "page": image.get("page"),
        "tile_box": image.get("tile_box"),
        "image_url": web_file_url(relative_image_path.as_posix()),
        "annotation_count": len(image_annotations),
        "annotations": image_annotations,
      }
    )

  annotated_images = sum(1 for image in images if image["annotation_count"] > 0)
  return {
    "split": split,
    "annotations_path": str(annotations_path.relative_to(REPO_ROOT).as_posix()) if annotations_path.exists() else None,
    "images": images,
    "categories": data.get("categories", []),
    "image_count": len(images),
    "annotated_images": annotated_images,
    "annotation_count": len(data.get("annotations", [])),
  }


def _polygon_bbox(segmentation):
  xs = []
  ys = []
  for polygon in segmentation:
    xs.extend(polygon[0::2])
    ys.extend(polygon[1::2])
  if not xs or not ys:
    return [0.0, 0.0, 0.0, 0.0]
  x0 = float(min(xs))
  y0 = float(min(ys))
  x1 = float(max(xs))
  y1 = float(max(ys))
  return [x0, y0, x1 - x0, y1 - y0]


def _polygon_area(segmentation):
  total = 0.0
  for polygon in segmentation:
    if len(polygon) < 6:
      continue
    points = [(float(polygon[index]), float(polygon[index + 1])) for index in range(0, len(polygon), 2)]
    area = 0.0
    for index, (x1, y1) in enumerate(points):
      x2, y2 = points[(index + 1) % len(points)]
      area += (x1 * y2) - (x2 * y1)
    total += abs(area) * 0.5
  return total


def save_image_annotations(split, image_id, annotations_payload):
  annotations_path = _coco_annotations_path(split)
  data = safe_load_json(annotations_path) or {"images": [], "annotations": [], "categories": []}
  image_ids = {image.get("id") for image in data.get("images", [])}
  if image_id not in image_ids:
    raise ValueError("Image introuvable dans le dataset COCO.")

  remaining = [annotation for annotation in data.get("annotations", []) if annotation.get("image_id") != image_id]
  next_id = (max([annotation.get("id", 0) for annotation in remaining], default=0) + 1)

  normalized = []
  for item in annotations_payload:
    category_id = int(item.get("category_id"))
    segmentation = item.get("segmentation") or []
    segmentation = [
      [float(value) for value in polygon]
      for polygon in segmentation
      if isinstance(polygon, list) and len(polygon) >= 6 and len(polygon) % 2 == 0
    ]
    if not segmentation:
      continue
    bbox = _polygon_bbox(segmentation)
    area = _polygon_area(segmentation)
    if bbox[2] <= 0 or bbox[3] <= 0 or area <= 0:
      continue
    normalized.append(
      {
        "id": next_id,
        "image_id": image_id,
        "category_id": category_id,
        "segmentation": segmentation,
        "bbox": bbox,
        "area": area,
        "iscrowd": 0,
      }
    )
    next_id += 1

  data["annotations"] = remaining + normalized
  save_json(annotations_path, data)
  return gather_annotation_state(split)


def enrich_legend_result(result):
  payload = dict(result)
  payload["preview_url"] = web_file_url(result["preview_path"])
  for item in payload.get("objects", []):
    item["crop_url"] = web_file_url(item["crop_path"])
    item["binary_crop_url"] = web_file_url(item["binary_crop_path"])
  for page in payload.get("page_summaries", []):
    page["preview_url"] = web_file_url(page["preview_path"])
  return payload


def enrich_match_result(result):
  payload = dict(result)
  for page in payload.get("pages", []):
    if page.get("preview_path"):
      page["preview_url"] = web_file_url(page["preview_path"])
    if page.get("counted_items_path"):
      page["counted_items_url"] = web_file_url(page["counted_items_path"])
  return payload


def compare_runs(run_a_name, run_b_name):
  runs = {item["name"]: item for item in gather_training_runs()}
  run_a = runs.get(run_a_name)
  run_b = runs.get(run_b_name)
  if not run_a or not run_b:
    return None

  def diff(field):
    a = run_a.get(field)
    b = run_b.get(field)
    if a is None or b is None:
      return None
    return b - a

  return {
    "from": run_a_name,
    "to": run_b_name,
    "delta_best_val_loss": diff("best_val_loss"),
    "delta_best_val_accuracy": diff("best_val_accuracy"),
    "delta_train_samples": diff("train_samples"),
    "delta_val_samples": diff("val_samples"),
  }


class DashboardHandler(SimpleHTTPRequestHandler):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, directory=str(WEB_DIR), **kwargs)

  def do_GET(self):
    parsed = urlparse(self.path)
    if parsed.path == "/api/state":
      return self.send_json(
        {
          "dataset": gather_dataset_stats(),
          "runtime": gather_runtime_stats(),
          "training_runs": gather_training_runs(),
          "instance_outputs": gather_instance_outputs(),
          "improvements": gather_improvements(),
        }
      )
    if parsed.path == "/api/pdfs":
      return self.send_json({"pdfs": list_project_pdfs()})
    if parsed.path == "/api/annotation-state":
      params = parse_qs(parsed.query)
      split = params.get("split", ["train"])[0]
      try:
        return self.send_json(gather_annotation_state(split))
      except Exception as exc:
        return self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
    if parsed.path == "/api/compare":
      params = parse_qs(parsed.query)
      payload = compare_runs(params.get("a", [None])[0], params.get("b", [None])[0])
      if payload is None:
        return self.send_json({"error": "Runs introuvables."}, status=HTTPStatus.BAD_REQUEST)
      return self.send_json(payload)
    if parsed.path == "/api/file":
      return self.handle_file(parsed.query)
    if parsed.path == "/favicon.ico":
      self.send_response(HTTPStatus.NO_CONTENT)
      self.end_headers()
      return
    return super().do_GET()

  def do_POST(self):
    parsed = urlparse(self.path)
    if parsed.path == "/api/extract-legend":
      return self.handle_extract_legend()
    if parsed.path == "/api/match-object":
      return self.handle_match_object()
    if parsed.path == "/api/annotation-save":
      return self.handle_annotation_save()
    self.send_error(HTTPStatus.NOT_FOUND, "unknown endpoint")

  def send_json(self, payload, status=HTTPStatus.OK):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    self.send_response(status)
    self.send_header("Content-Type", "application/json; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)

  def handle_file(self, query):
    params = parse_qs(query)
    raw_path = params.get("path", [None])[0]
    try:
      file_path = resolve_repo_file(unquote(raw_path))
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

  def read_json_body(self):
    content_length = int(self.headers.get("Content-Length", "0"))
    raw_body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
    return json.loads(raw_body)

  def handle_extract_legend(self):
    payload = self.read_json_body()
    pdf_path = payload.get("pdf_path")
    pages = payload.get("pages") or "1"
    try:
      resolve_repo_pdf_path(pdf_path)
      result = run_legend_extraction(pdf_path, pages)
      return self.send_json({"result": enrich_legend_result(result)})
    except Exception as exc:
      return self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

  def handle_match_object(self):
    payload = self.read_json_body()
    pdf_path = payload.get("pdf_path")
    pages = payload.get("pages") or None
    obj_payload = payload.get("object") or {}
    mode = payload.get("mode") or "direct"
    try:
      resolve_repo_pdf_path(pdf_path)
      if mode == "kmeans_strict":
        result = match_legend_object_kmeans(pdf_path, obj_payload, page_spec=pages)
      else:
        result = match_legend_object(pdf_path, obj_payload, page_spec=pages)
      return self.send_json({"result": enrich_match_result(result)})
    except Exception as exc:
      return self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

  def handle_annotation_save(self):
    payload = self.read_json_body()
    split = payload.get("split") or "train"
    image_id = int(payload.get("image_id"))
    annotations = payload.get("annotations") or []
    try:
      state = save_image_annotations(split, image_id, annotations)
      return self.send_json(state)
    except Exception as exc:
      return self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)


def run_server():
  server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
  print(f"Instance Seg Dashboard: http://{HOST}:{PORT}")
  server.serve_forever()


if __name__ == "__main__":
  run_server()
