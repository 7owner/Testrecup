from __future__ import annotations

import cgi
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import fitz
from PIL import Image, ImageDraw, ImageFilter, ImageOps

CV2_AVAILABLE = None


ROOT = Path(__file__).resolve().parent
SAAS_ROOT = ROOT.parent
WEB_DIR = ROOT / "web"
RUNS_DIR = ROOT / "runs"
UPLOADS_DIR = ROOT / "uploads"
HOST = "127.0.0.1"
PORT = 8891


def ensure_dirs():
  RUNS_DIR.mkdir(parents=True, exist_ok=True)
  UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def safe_file_name(name):
  cleaned = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in name)
  cleaned = cleaned.strip(" .")
  return cleaned or "plan.pdf"


def write_json(handler, payload, status=HTTPStatus.OK):
  data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
  handler.send_response(status)
  handler.send_header("Content-Type", "application/json; charset=utf-8")
  handler.send_header("Content-Length", str(len(data)))
  handler.end_headers()
  handler.wfile.write(data)


def write_error(handler, message, status=HTTPStatus.BAD_REQUEST):
  write_json(handler, {"error": message}, status)


def resolve_upload(pdf_id):
  candidate = (UPLOADS_DIR / pdf_id).resolve()
  if UPLOADS_DIR not in candidate.parents and candidate != UPLOADS_DIR:
    raise ValueError("Chemin PDF invalide.")
  if not candidate.exists() or candidate.suffix.lower() != ".pdf":
    raise ValueError("PDF introuvable.")
  return candidate


def resolve_run_file(raw_path):
  candidate = (ROOT / unquote(raw_path)).resolve()
  if ROOT not in candidate.parents and candidate != ROOT:
    raise ValueError("Chemin fichier invalide.")
  if not candidate.exists():
    raise ValueError("Fichier introuvable.")
  return candidate


def resolve_saas_file(raw_path):
  candidate = (SAAS_ROOT / unquote(raw_path)).resolve()
  if SAAS_ROOT not in candidate.parents and candidate != SAAS_ROOT:
    raise ValueError("Chemin hors projet saas_test_comptage.")
  if not candidate.exists():
    raise ValueError("Fichier introuvable.")
  return candidate


def saas_file_url(path):
  path = Path(path).resolve()
  if SAAS_ROOT not in path.parents and path != SAAS_ROOT:
    raise ValueError("Fichier hors projet saas_test_comptage.")
  rel = path.relative_to(SAAS_ROOT).as_posix()
  return f"/api/saas-file?path={rel}"


def web_file_url_from_root(path):
  path = Path(path).resolve()
  if ROOT not in path.parents and path != ROOT:
    raise ValueError("Fichier hors PDF Tile Lab.")
  rel = path.relative_to(ROOT).as_posix()
  return f"/api/file?path={rel}"


def serveable_crop_bounds(image, pad_ratio=0.45):
  gray = image.convert("L")
  arr = np.asarray(gray) if "np" in globals() else None
  if arr is None:
    import numpy as np
    arr = np.asarray(gray)
  ys, xs = np.where(arr < 245)
  if len(xs) == 0 or len(ys) == 0:
    return (0, 0, image.width, image.height)
  x0, x1 = int(xs.min()), int(xs.max()) + 1
  y0, y1 = int(ys.min()), int(ys.max()) + 1
  pad = int(max(x1 - x0, y1 - y0) * pad_ratio)
  return (
    max(0, x0 - pad),
    max(0, y0 - pad),
    min(image.width, x1 + pad),
    min(image.height, y1 + pad),
  )


def normalize_symbol_image(image, size=96):
  import numpy as np
  image = image.convert("RGB")
  crop = image.crop(serveable_crop_bounds(image, pad_ratio=0.35))
  canvas = Image.new("RGB", (size, size), "white")
  scale = min((size - 10) / max(1, crop.width), (size - 10) / max(1, crop.height))
  resized = crop.resize(
    (max(1, int(crop.width * scale)), max(1, int(crop.height * scale))),
    Image.Resampling.LANCZOS,
  )
  canvas.paste(resized, ((size - resized.width) // 2, (size - resized.height) // 2))
  return canvas


def visual_embedding(image):
  import cv2
  import numpy as np
  norm = normalize_symbol_image(image, size=96)
  arr = np.asarray(norm, dtype=np.uint8)
  gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
  small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
  edges = cv2.Canny(gray, 70, 160)
  edges_small = cv2.resize(edges, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
  hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
  hist_h = cv2.calcHist([hsv], [0], None, [24], [0, 180]).flatten()
  hist_s = cv2.calcHist([hsv], [1], None, [16], [0, 256]).flatten()
  hist_v = cv2.calcHist([hsv], [2], None, [16], [0, 256]).flatten()
  feature = np.concatenate([small.flatten(), edges_small.flatten() * 1.4, hist_h, hist_s, hist_v]).astype(np.float32)
  feature -= feature.mean()
  norm_value = np.linalg.norm(feature)
  return feature / norm_value if norm_value > 0 else feature


def cosine_score(a, b):
  import numpy as np
  return float(np.dot(a, b))


def list_segmentation_checkpoints():
  roots = [
    SAAS_ROOT / "instance_seg",
    SAAS_ROOT / "outputs",
    SAAS_ROOT / "training_runs",
  ]
  found = []
  skipped = {".git", ".pytest_cache", "__pycache__", ".venv", "node_modules"}
  for base in roots:
    if not base.exists():
      continue
    for current, dirs, files in os.walk(base, topdown=True, onerror=lambda _err: None):
      dirs[:] = [name for name in dirs if name not in skipped]
      for name in files:
        if not name.lower().endswith((".pth", ".pt", ".ckpt")):
          continue
        path = Path(current) / name
        try:
          stat = path.stat()
          rel = path.resolve().relative_to(SAAS_ROOT).as_posix()
        except Exception:
          continue
        found.append({
          "path": rel,
          "name": name,
          "size": stat.st_size,
        })
  return sorted(found, key=lambda item: item["path"])


def list_legend_symbols():
  roots = [
    SAAS_ROOT / "legend_templates_example" / "crops",
  ]
  symbols = []
  for root in roots:
    if not root.exists():
      continue
    for path in sorted(root.glob("*.png")):
      try:
        with Image.open(path) as image:
          width, height = image.size
      except Exception:
        continue
      symbols.append({
        "id": path.stem,
        "label": path.stem.replace("_", " ").title(),
        "path": path.resolve().relative_to(SAAS_ROOT).as_posix(),
        "url": saas_file_url(path),
        "width": width,
        "height": height,
      })
  return symbols


def find_coco_datasets():
  candidates = [
    SAAS_ROOT / "Test_No3" / "colab" / "coco_colab",
    SAAS_ROOT / "instance_seg" / "data" / "plans_coco",
  ]
  datasets = []
  for root in candidates:
    if not root.exists():
      continue
    splits = []
    for split in ["train", "val", "test"]:
      annotations_path = root / split / "annotations.json"
      images_dir = root / split / "images"
      if not annotations_path.exists() or not images_dir.exists():
        continue
      try:
        data = json.loads(annotations_path.read_text(encoding="utf-8"))
      except Exception:
        continue
      splits.append({
        "name": split,
        "images": len(data.get("images", [])),
        "annotations": len(data.get("annotations", [])),
        "categories": len(data.get("categories", [])),
      })
    if splits:
      datasets.append({
        "path": root.resolve().relative_to(SAAS_ROOT).as_posix(),
        "name": root.name,
        "splits": splits,
      })
  return datasets


def palette_color(index):
  colors = [
    (239, 68, 68),
    (37, 99, 235),
    (22, 163, 74),
    (217, 119, 6),
    (147, 51, 234),
    (8, 145, 178),
    (190, 18, 60),
    (79, 70, 229),
  ]
  return colors[index % len(colors)]


def render_coco_sample(payload):
  dataset_root = resolve_saas_file(payload.get("dataset_path", ""))
  split = payload.get("split", "train")
  if split not in {"train", "val", "test"}:
    raise ValueError("Split dataset invalide.")
  annotations_path = dataset_root / split / "annotations.json"
  images_dir = dataset_root / split / "images"
  if not annotations_path.exists() or not images_dir.exists():
    raise ValueError("Dataset COCO incomplet.")

  data = json.loads(annotations_path.read_text(encoding="utf-8"))
  images = data.get("images") or []
  if not images:
    raise ValueError("Aucune image dans ce split.")
  index = max(0, min(len(images) - 1, int(payload.get("index", 0))))
  image_info = images[index]
  image_path = images_dir / image_info["file_name"]
  if not image_path.exists():
    raise ValueError(f"Image introuvable: {image_info['file_name']}")

  categories = {item["id"]: item for item in data.get("categories", [])}
  category_order = {item["id"]: idx for idx, item in enumerate(data.get("categories", []))}
  annotations = [item for item in data.get("annotations", []) if item.get("image_id") == image_info.get("id")]

  image = Image.open(image_path).convert("RGBA")
  overlay = image.copy()
  draw = ImageDraw.Draw(overlay, "RGBA")
  counts = {}
  for annotation in annotations:
    category = categories.get(annotation.get("category_id"), {"name": str(annotation.get("category_id"))})
    name = category.get("name", str(annotation.get("category_id")))
    counts[name] = counts.get(name, 0) + 1
    color = palette_color(category_order.get(annotation.get("category_id"), 0))
    fill = (color[0], color[1], color[2], 52)
    outline = (color[0], color[1], color[2], 230)
    for polygon in annotation.get("segmentation") or []:
      points = [(polygon[i], polygon[i + 1]) for i in range(0, len(polygon), 2)]
      if len(points) >= 3:
        draw.polygon(points, fill=fill, outline=outline)
    bbox = annotation.get("bbox") or []
    if len(bbox) == 4:
      x, y, w, h = bbox
      draw.rectangle((x, y, x + w, y + h), outline=outline, width=2)

  blended = Image.alpha_composite(image, overlay).convert("RGB")
  run_id = uuid.uuid4().hex
  rel_dir = Path("runs") / run_id / "coco_verify"
  out_dir = ROOT / rel_dir
  out_dir.mkdir(parents=True, exist_ok=True)
  overlay_name = "sample_overlay.png"
  raw_name = "sample_raw.png"
  blended.save(out_dir / overlay_name)
  image.convert("RGB").save(out_dir / raw_name)
  return {
    "dataset_path": dataset_root.resolve().relative_to(SAAS_ROOT).as_posix(),
    "split": split,
    "index": index,
    "image_count": len(images),
    "image_name": image_info.get("file_name"),
    "annotation_count": len(annotations),
    "counts": counts,
    "raw_url": f"/api/file?path={(rel_dir / raw_name).as_posix()}",
    "overlay_url": f"/api/file?path={(rel_dir / overlay_name).as_posix()}",
  }


def coco_class_summary(payload):
  dataset_root = resolve_saas_file(payload.get("dataset_path", ""))
  if not dataset_root.exists():
    raise ValueError("Dataset introuvable.")
  per_class = {}
  split_totals = {}
  for split in ["train", "val", "test"]:
    annotations_path = dataset_root / split / "annotations.json"
    if not annotations_path.exists():
      continue
    data = json.loads(annotations_path.read_text(encoding="utf-8"))
    categories = {item["id"]: item.get("name", str(item["id"])) for item in data.get("categories", [])}
    split_totals[split] = {
      "images": len(data.get("images", [])),
      "annotations": len(data.get("annotations", [])),
    }
    for category_id, name in categories.items():
      per_class.setdefault(name, {
        "name": name,
        "category_id": category_id,
        "train": 0,
        "val": 0,
        "test": 0,
        "examples": [],
      })
    for annotation in data.get("annotations", []):
      name = categories.get(annotation.get("category_id"), str(annotation.get("category_id")))
      per_class.setdefault(name, {
        "name": name,
        "category_id": annotation.get("category_id"),
        "train": 0,
        "val": 0,
        "test": 0,
        "examples": [],
      })
      per_class[name][split] += 1

  classes = sorted(per_class.values(), key=lambda item: (-(item["train"] + item["val"] + item["test"]), item["name"]))
  return {
    "dataset_path": dataset_root.resolve().relative_to(SAAS_ROOT).as_posix(),
    "split_totals": split_totals,
    "classes": classes,
  }


def coco_class_examples(payload):
  dataset_root = resolve_saas_file(payload.get("dataset_path", ""))
  class_name = str(payload.get("class_name", "")).strip()
  split = payload.get("split", "train")
  limit = max(1, min(24, int(payload.get("limit", 8))))
  if split not in {"train", "val", "test"}:
    raise ValueError("Split invalide.")
  annotations_path = dataset_root / split / "annotations.json"
  images_dir = dataset_root / split / "images"
  if not annotations_path.exists() or not images_dir.exists():
    raise ValueError("Split COCO introuvable.")

  data = json.loads(annotations_path.read_text(encoding="utf-8"))
  categories = {item["id"]: item for item in data.get("categories", [])}
  matching_category_ids = {cid for cid, item in categories.items() if item.get("name") == class_name}
  if not matching_category_ids:
    raise ValueError("Classe introuvable.")
  images_by_id = {item["id"]: item for item in data.get("images", [])}
  annotations = [item for item in data.get("annotations", []) if item.get("category_id") in matching_category_ids]
  annotations = annotations[:limit]

  run_id = uuid.uuid4().hex
  rel_dir = Path("runs") / run_id / "class_examples"
  out_dir = ROOT / rel_dir
  out_dir.mkdir(parents=True, exist_ok=True)
  examples = []
  for index, annotation in enumerate(annotations):
    image_info = images_by_id.get(annotation.get("image_id"))
    if not image_info:
      continue
    image_path = images_dir / image_info["file_name"]
    if not image_path.exists():
      continue
    bbox = annotation.get("bbox") or []
    if len(bbox) != 4:
      continue
    with Image.open(image_path).convert("RGB") as image:
      x, y, w, h = bbox
      pad = max(w, h) * 0.8
      crop_box = (
        max(0, int(x - pad)),
        max(0, int(y - pad)),
        min(image.width, int(x + w + pad)),
        min(image.height, int(y + h + pad)),
      )
      crop = image.crop(crop_box).convert("RGBA")
      draw = ImageDraw.Draw(crop, "RGBA")
      ox, oy = crop_box[0], crop_box[1]
      color = (22, 163, 74, 230)
      for polygon in annotation.get("segmentation") or []:
        points = [(polygon[i] - ox, polygon[i + 1] - oy) for i in range(0, len(polygon), 2)]
        if len(points) >= 3:
          draw.polygon(points, fill=(22, 163, 74, 46), outline=color)
      draw.rectangle((x - ox, y - oy, x + w - ox, y + h - oy), outline=color, width=2)
      name = f"example_{index:02d}.png"
      crop.convert("RGB").save(out_dir / name)
      examples.append({
        "url": f"/api/file?path={(rel_dir / name).as_posix()}",
        "image_name": image_info.get("file_name"),
        "bbox": bbox,
      })
  return {
    "class_name": class_name,
    "split": split,
    "examples": examples,
  }


def symbol_visual_matches(payload):
  legend_path = resolve_saas_file(payload.get("legend_path", ""))
  dataset_root = resolve_saas_file(payload.get("dataset_path", ""))
  split = payload.get("split", "train")
  limit = max(1, min(40, int(payload.get("limit", 12))))
  scan_limit = max(100, min(12000, int(payload.get("scan_limit", 2500))))
  if split not in {"train", "val", "test"}:
    raise ValueError("Split invalide.")

  annotations_path = dataset_root / split / "annotations.json"
  images_dir = dataset_root / split / "images"
  if not annotations_path.exists() or not images_dir.exists():
    raise ValueError("Split COCO introuvable.")

  data = json.loads(annotations_path.read_text(encoding="utf-8"))
  images_by_id = {item["id"]: item for item in data.get("images", [])}
  categories = {item["id"]: item.get("name", str(item["id"])) for item in data.get("categories", [])}

  with Image.open(legend_path).convert("RGB") as legend_image:
    legend_embedding = visual_embedding(legend_image)

  scored = []
  annotations = data.get("annotations", [])[:scan_limit]
  for annotation in annotations:
    image_info = images_by_id.get(annotation.get("image_id"))
    if not image_info:
      continue
    image_path = images_dir / image_info["file_name"]
    bbox = annotation.get("bbox") or []
    if not image_path.exists() or len(bbox) != 4:
      continue
    try:
      with Image.open(image_path).convert("RGB") as image:
        x, y, w, h = bbox
        pad = max(w, h) * 0.8
        crop_box = (
          max(0, int(x - pad)),
          max(0, int(y - pad)),
          min(image.width, int(x + w + pad)),
          min(image.height, int(y + h + pad)),
        )
        crop = image.crop(crop_box)
        score = cosine_score(legend_embedding, visual_embedding(crop))
        scored.append((score, annotation, image_info, crop_box))
    except Exception:
      continue

  scored.sort(key=lambda item: item[0], reverse=True)
  run_id = uuid.uuid4().hex
  rel_dir = Path("runs") / run_id / "visual_matches"
  out_dir = ROOT / rel_dir
  out_dir.mkdir(parents=True, exist_ok=True)

  matches = []
  for index, (score, annotation, image_info, crop_box) in enumerate(scored[:limit]):
    image_path = images_dir / image_info["file_name"]
    with Image.open(image_path).convert("RGB") as image:
      crop = image.crop(crop_box).convert("RGBA")
      draw = ImageDraw.Draw(crop, "RGBA")
      bbox = annotation.get("bbox") or []
      x, y, w, h = bbox
      ox, oy = crop_box[0], crop_box[1]
      for polygon in annotation.get("segmentation") or []:
        points = [(polygon[i] - ox, polygon[i + 1] - oy) for i in range(0, len(polygon), 2)]
        if len(points) >= 3:
          draw.polygon(points, fill=(37, 99, 235, 48), outline=(37, 99, 235, 230))
      draw.rectangle((x - ox, y - oy, x + w - ox, y + h - oy), outline=(22, 163, 74, 240), width=2)
      name = f"match_{index:02d}.png"
      crop.convert("RGB").save(out_dir / name, "PNG")
      matches.append({
        "url": f"/api/file?path={(rel_dir / name).as_posix()}",
        "score": score,
        "class_name": categories.get(annotation.get("category_id"), str(annotation.get("category_id"))),
        "image_name": image_info.get("file_name"),
      })

  return {
    "legend_path": legend_path.resolve().relative_to(SAAS_ROOT).as_posix(),
    "dataset_path": dataset_root.resolve().relative_to(SAAS_ROOT).as_posix(),
    "split": split,
    "scanned": len(annotations),
    "matches": matches,
  }


def pixmap_to_pil(pix):
  mode = "RGBA" if pix.alpha else "RGB"
  return Image.frombytes(mode, (pix.width, pix.height), pix.samples)


def render_clip(page, rect, dpi):
  zoom = dpi / 72.0
  pix = page.get_pixmap(
    matrix=fitz.Matrix(zoom, zoom),
    clip=rect,
    colorspace=fitz.csRGB,
    alpha=False,
  )
  return pixmap_to_pil(pix)


def enhance_image(image, mode):
  if mode == "none":
    return image

  if mode == "opencv":
    try:
      import cv2
      import numpy as np
    except Exception:
      cv2 = None
      np = None

  if mode == "opencv" and cv2 is not None:
    arr = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    arr = cv2.resize(arr, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    lab = cv2.cvtColor(arr, cv2.COLOR_BGR2LAB)
    l_chan, a_chan, b_chan = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_chan = clahe.apply(l_chan)
    lab = cv2.merge((l_chan, a_chan, b_chan))
    arr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    blur = cv2.GaussianBlur(arr, (0, 0), 1.1)
    arr = cv2.addWeighted(arr, 1.55, blur, -0.55, 0)
    arr = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(arr)

  upscaled = image.resize((image.width * 2, image.height * 2), Image.Resampling.BICUBIC)
  upscaled = ImageOps.autocontrast(upscaled, cutoff=1)
  return upscaled.filter(ImageFilter.UnsharpMask(radius=1.1, percent=150, threshold=3))


def opencv_available():
  global CV2_AVAILABLE
  if CV2_AVAILABLE is not None:
    return CV2_AVAILABLE
  try:
    import cv2  # noqa: F401
    CV2_AVAILABLE = True
  except Exception:
    CV2_AVAILABLE = False
  return CV2_AVAILABLE


def save_image(image, path):
  path.parent.mkdir(parents=True, exist_ok=True)
  image.save(path, "PNG", optimize=True)


def rotate_cv_image(cv2_module, image, angle):
  if angle == 0:
    return image
  if angle == 90:
    return cv2_module.rotate(image, cv2_module.ROTATE_90_CLOCKWISE)
  if angle == 180:
    return cv2_module.rotate(image, cv2_module.ROTATE_180)
  if angle == 270:
    return cv2_module.rotate(image, cv2_module.ROTATE_90_COUNTERCLOCKWISE)
  return image


def nms_detections(detections, min_dist):
  detections.sort(key=lambda item: item["score"], reverse=True)
  kept = []
  for det in detections:
    cx = det["x"] + det["w"] / 2
    cy = det["y"] + det["h"] / 2
    duplicate = False
    for prev in kept:
      pcx = prev["x"] + prev["w"] / 2
      pcy = prev["y"] + prev["h"] / 2
      if ((cx - pcx) ** 2 + (cy - pcy) ** 2) ** 0.5 < min_dist:
        duplicate = True
        break
    if not duplicate:
      kept.append(det)
  return kept


def detect_template(payload):
  try:
    import cv2
    import numpy as np
  except Exception as exc:
    raise ValueError(f"OpenCV indisponible: {exc}") from exc

  template_file = resolve_run_file(payload.get("template_path", ""))
  target_file = resolve_run_file(payload.get("target_path", ""))
  bbox = payload.get("bbox") or {}
  threshold = max(0.4, min(0.98, float(payload.get("threshold", 0.72))))
  rotations = payload.get("rotations") or [0]

  x = max(0, int(round(float(bbox.get("x", 0)))))
  y = max(0, int(round(float(bbox.get("y", 0)))))
  w = max(4, int(round(float(bbox.get("w", 0)))))
  h = max(4, int(round(float(bbox.get("h", 0)))))

  target = cv2.imread(str(target_file), cv2.IMREAD_COLOR)
  source = cv2.imread(str(template_file), cv2.IMREAD_COLOR)
  if target is None or source is None:
    raise ValueError("Image source ou cible illisible.")
  if x + w > source.shape[1] or y + h > source.shape[0]:
    raise ValueError("Le gabarit sort de l'image source.")

  template = source[y:y + h, x:x + w]
  target_gray = cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)
  template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
  if template_gray.std() < 3:
    raise ValueError("Gabarit trop uniforme. Selectionne plus de contours du symbole.")

  detections = []
  for angle in rotations:
    try:
      angle = int(angle)
    except Exception:
      continue
    tpl = rotate_cv_image(cv2, template_gray, angle)
    th, tw = tpl.shape[:2]
    if th >= target_gray.shape[0] or tw >= target_gray.shape[1]:
      continue
    result = cv2.matchTemplate(target_gray, tpl, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(result >= threshold)
    for px, py in zip(xs, ys):
      detections.append({
        "x": int(px),
        "y": int(py),
        "w": int(tw),
        "h": int(th),
        "score": float(result[py, px]),
        "angle": angle,
      })

  detections = nms_detections(detections, max(w, h) * 0.55)
  overlay = target.copy()
  for det in detections:
    cv2.rectangle(
      overlay,
      (det["x"], det["y"]),
      (det["x"] + det["w"], det["y"] + det["h"]),
      (0, 190, 80),
      2,
    )
    cv2.putText(
      overlay,
      f'{det["score"]:.2f}',
      (det["x"], max(12, det["y"] - 4)),
      cv2.FONT_HERSHEY_SIMPLEX,
      0.42,
      (0, 120, 50),
      1,
      cv2.LINE_AA,
    )

  run_id = uuid.uuid4().hex
  rel_dir = Path("runs") / run_id
  out_dir = ROOT / rel_dir
  out_dir.mkdir(parents=True, exist_ok=True)
  template_name = "template.png"
  overlay_name = "detections.png"
  cv2.imwrite(str(out_dir / template_name), template)
  cv2.imwrite(str(out_dir / overlay_name), overlay)
  return {
    "count": len(detections),
    "threshold": threshold,
    "detections": detections[:500],
    "template_url": f"/api/file?path={rel_dir.as_posix()}/{template_name}",
    "overlay_url": f"/api/file?path={rel_dir.as_posix()}/{overlay_name}",
  }


def detect_red_symbols(payload):
  try:
    import cv2
    import numpy as np
  except Exception as exc:
    raise ValueError(f"OpenCV indisponible: {exc}") from exc

  target_file = resolve_run_file(payload.get("target_path", ""))
  min_area = max(20, int(payload.get("min_area", 80)))
  max_area = max(min_area + 1, int(payload.get("max_area", 6000)))
  target = cv2.imread(str(target_file), cv2.IMREAD_COLOR)
  if target is None:
    raise ValueError("Image cible illisible.")

  hsv = cv2.cvtColor(target, cv2.COLOR_BGR2HSV)
  mask1 = cv2.inRange(hsv, (0, 45, 70), (12, 255, 255))
  mask2 = cv2.inRange(hsv, (165, 45, 70), (180, 255, 255))
  mask = cv2.bitwise_or(mask1, mask2)
  kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
  mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
  mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

  contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
  candidates = []
  for cnt in contours:
    x, y, w, h = cv2.boundingRect(cnt)
    area = cv2.contourArea(cnt)
    if area < min_area or area > max_area:
      continue
    ratio = w / max(1, h)
    if ratio < 0.45 or ratio > 2.2:
      continue
    fill = area / max(1, w * h)
    if fill < 0.10:
      continue
    # Expand to capture the white circle / cross context around the red fill.
    pad = int(max(w, h) * 0.35)
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(target.shape[1], x + w + pad)
    y1 = min(target.shape[0], y + h + pad)
    candidates.append({
      "x": int(x0),
      "y": int(y0),
      "w": int(x1 - x0),
      "h": int(y1 - y0),
      "score": float(min(1.0, fill + 0.45)),
      "area": float(area),
    })

  candidates = nms_detections(candidates, 24)
  overlay = target.copy()
  for det in candidates:
    cv2.rectangle(
      overlay,
      (det["x"], det["y"]),
      (det["x"] + det["w"], det["y"] + det["h"]),
      (0, 190, 80),
      2,
    )
    cv2.putText(
      overlay,
      f'{det["score"]:.2f}',
      (det["x"], max(12, det["y"] - 4)),
      cv2.FONT_HERSHEY_SIMPLEX,
      0.42,
      (0, 120, 50),
      1,
      cv2.LINE_AA,
    )

  run_id = uuid.uuid4().hex
  rel_dir = Path("runs") / run_id
  out_dir = ROOT / rel_dir
  out_dir.mkdir(parents=True, exist_ok=True)
  overlay_name = "red-symbol-detections.png"
  mask_name = "red-mask.png"
  cv2.imwrite(str(out_dir / overlay_name), overlay)
  cv2.imwrite(str(out_dir / mask_name), mask)
  return {
    "count": len(candidates),
    "detections": candidates[:500],
    "overlay_url": f"/api/file?path={rel_dir.as_posix()}/{overlay_name}",
    "mask_url": f"/api/file?path={rel_dir.as_posix()}/{mask_name}",
  }


def run_instance_segmentation(payload):
  checkpoint_raw = payload.get("checkpoint_path", "")
  if not checkpoint_raw:
    raise ValueError("Aucun checkpoint de segmentation selectionne.")
  checkpoint_path = resolve_saas_file(checkpoint_raw)
  target_file = resolve_run_file(payload.get("target_path", ""))
  score_threshold = max(0.05, min(0.95, float(payload.get("score_threshold", 0.50))))
  mask_threshold = max(0.05, min(0.95, float(payload.get("mask_threshold", 0.50))))
  tile_size = max(256, min(2048, int(payload.get("tile_size", 1024))))
  overlap = max(0, min(tile_size - 1, int(payload.get("overlap", 128))))

  run_id = uuid.uuid4().hex
  output_dir = ROOT / "runs" / run_id / "instance_seg"
  output_dir.mkdir(parents=True, exist_ok=True)
  command = [
    sys.executable,
    "-m",
    "instance_seg.infer_instance",
    "--checkpoint",
    str(checkpoint_path),
    "--input",
    str(target_file),
    "--output-dir",
    str(output_dir),
    "--tile-size",
    str(tile_size),
    "--overlap",
    str(overlap),
    "--score-threshold",
    str(score_threshold),
    "--mask-threshold",
    str(mask_threshold),
    "--device",
    "cpu",
  ]
  completed = subprocess.run(
    command,
    cwd=SAAS_ROOT,
    capture_output=True,
    text=True,
    timeout=180,
  )
  if completed.returncode != 0:
    message = (completed.stderr or completed.stdout or "Inference segmentation echouee.").strip()
    raise ValueError(message[-1600:])

  summary_path = output_dir / "summary.json"
  if not summary_path.exists():
    raise ValueError("Inference terminee sans summary.json.")
  summary = json.loads(summary_path.read_text(encoding="utf-8"))
  pages = summary.get("pages") or []
  page = pages[0] if pages else {}
  preview_path = page.get("preview_path")
  preview_url = None
  if preview_path:
    preview_url = web_file_url_from_root(Path(preview_path))
  return {
    "instance_count": int(page.get("instance_count", 0)),
    "counts": page.get("counts") or {},
    "instances": page.get("instances") or [],
    "preview_url": preview_url,
    "stdout": completed.stdout[-1200:],
  }


def make_grid_overlay_preview(pdf_path, page_index, rows, cols):
  doc = fitz.open(pdf_path)
  try:
    page = doc[page_index]
    preview = render_clip(page, page.rect, 90)
    run_id = uuid.uuid4().hex
    rel_dir = Path("runs") / run_id
    out_dir = ROOT / rel_dir
    preview_path = out_dir / "page-preview.png"
    save_image(preview, preview_path)
    return {
      "run_id": run_id,
      "page_width": page.rect.width,
      "page_height": page.rect.height,
      "preview_url": f"/api/file?path={rel_dir.as_posix()}/page-preview.png",
      "rows": rows,
      "cols": cols,
    }
  finally:
    doc.close()


def normalized_roi(page, payload):
  roi = payload.get("roi") or {}
  x = float(roi.get("x", 0))
  y = float(roi.get("y", 0))
  w = float(roi.get("w", 1))
  h = float(roi.get("h", 1))
  x = max(0.0, min(0.98, x))
  y = max(0.0, min(0.98, y))
  w = max(0.02, min(1.0 - x, w))
  h = max(0.02, min(1.0 - y, h))
  return fitz.Rect(
    page.rect.x0 + x * page.rect.width,
    page.rect.y0 + y * page.rect.height,
    page.rect.x0 + (x + w) * page.rect.width,
    page.rect.y0 + (y + h) * page.rect.height,
  ), {"x": x, "y": y, "w": w, "h": h}


def render_tile_image(page, area, rows, cols, row, col, dpi, enhance_mode, out_dir, rel_dir, margin_ratio=0.0):
  cell_w = area.width / cols
  cell_h = area.height / rows
  mx = cell_w * margin_ratio
  my = cell_h * margin_ratio
  rect = fitz.Rect(
    max(area.x0, area.x0 + col * cell_w - mx),
    max(area.y0, area.y0 + row * cell_h - my),
    min(area.x1, area.x0 + (col + 1) * cell_w + mx),
    min(area.y1, area.y0 + (row + 1) * cell_h + my),
  )
  base = render_clip(page, rect, dpi)
  enhanced = enhance_image(base, enhance_mode)
  tile_name = f"tile-r{row + 1:02d}-c{col + 1:02d}.png"
  enhanced_name = f"tile-r{row + 1:02d}-c{col + 1:02d}-enhanced.png"
  save_image(base, out_dir / tile_name)
  save_image(enhanced, out_dir / enhanced_name)
  return {
    "row": row + 1,
    "col": col + 1,
    "label": f"L{row + 1} C{col + 1}",
    "url": f"/api/file?path={rel_dir.as_posix()}/{tile_name}",
    "enhanced_url": f"/api/file?path={rel_dir.as_posix()}/{enhanced_name}",
    "width": enhanced.width,
    "height": enhanced.height,
  }


def render_single_tile(pdf_path, page_index, rows, cols, dpi, enhance_mode, payload):
  doc = fitz.open(pdf_path)
  try:
    page = doc[page_index]
    area, roi = normalized_roi(page, payload)
    row = max(0, min(rows - 1, int(payload.get("tile_row", 1)) - 1))
    col = max(0, min(cols - 1, int(payload.get("tile_col", 1)) - 1))
    margin_ratio = max(0.0, min(0.5, float(payload.get("tile_margin", 0.0))))
    run_id = uuid.uuid4().hex
    rel_dir = Path("runs") / run_id
    out_dir = ROOT / rel_dir
    tile = render_tile_image(page, area, rows, cols, row, col, dpi, enhance_mode, out_dir, rel_dir, margin_ratio)
    return {
      "run_id": run_id,
      "rows": rows,
      "cols": cols,
      "dpi": dpi,
      "enhance_mode": enhance_mode,
      "roi": roi,
      "tile": tile,
    }
  finally:
    doc.close()


def render_grid(pdf_path, page_index, rows, cols, dpi, enhance_mode, payload):
  doc = fitz.open(pdf_path)
  try:
    page = doc[page_index]
    area, roi = normalized_roi(page, payload)
    run_id = uuid.uuid4().hex
    rel_dir = Path("runs") / run_id
    out_dir = ROOT / rel_dir
    tiles = []
    margin_ratio = max(0.0, min(0.5, float(payload.get("tile_margin", 0.0))))

    for row in range(rows):
      for col in range(cols):
        tiles.append(render_tile_image(page, area, rows, cols, row, col, dpi, enhance_mode, out_dir, rel_dir, margin_ratio))

    return {
      "run_id": run_id,
      "rows": rows,
      "cols": cols,
      "dpi": dpi,
      "enhance_mode": enhance_mode,
      "roi": roi,
      "tiles": tiles,
      "opencv_available": opencv_available(),
    }
  finally:
    doc.close()


class Handler(BaseHTTPRequestHandler):
  def log_message(self, fmt, *args):
    sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

  def do_GET(self):
    parsed = urlparse(self.path)
    if parsed.path == "/":
      self.serve_static(WEB_DIR / "index.html")
      return
    if parsed.path.startswith("/web/"):
      self.serve_static(WEB_DIR / parsed.path.removeprefix("/web/"))
      return
    if parsed.path == "/api/file":
      params = parse_qs(parsed.query)
      try:
        file_path = resolve_run_file(params.get("path", [""])[0])
      except ValueError as exc:
        write_error(self, str(exc), HTTPStatus.NOT_FOUND)
        return
      self.serve_static(file_path)
      return
    if parsed.path == "/api/saas-file":
      params = parse_qs(parsed.query)
      try:
        file_path = resolve_saas_file(params.get("path", [""])[0])
      except ValueError as exc:
        write_error(self, str(exc), HTTPStatus.NOT_FOUND)
        return
      self.serve_static(file_path)
      return
    if parsed.path == "/api/health":
      write_json(self, {"ok": True, "opencv_status": "loaded_on_render"})
      return
    if parsed.path == "/api/seg-checkpoints":
      try:
        checkpoints = list_segmentation_checkpoints()
      except Exception as exc:
        write_json(self, {"checkpoints": [], "warning": str(exc)})
        return
      write_json(self, {"checkpoints": checkpoints})
      return
    if parsed.path == "/api/coco-datasets":
      try:
        datasets = find_coco_datasets()
      except Exception as exc:
        write_json(self, {"datasets": [], "warning": str(exc)})
        return
      write_json(self, {"datasets": datasets})
      return
    if parsed.path == "/api/legend-symbols":
      try:
        symbols = list_legend_symbols()
      except Exception as exc:
        write_json(self, {"symbols": [], "warning": str(exc)})
        return
      write_json(self, {"symbols": symbols})
      return
    write_error(self, "Route inconnue.", HTTPStatus.NOT_FOUND)

  def do_POST(self):
    parsed = urlparse(self.path)
    if parsed.path == "/api/upload":
      self.handle_upload()
      return
    if parsed.path == "/api/preview":
      self.handle_preview()
      return
    if parsed.path == "/api/render-grid":
      self.handle_render_grid()
      return
    if parsed.path == "/api/render-tile":
      self.handle_render_tile()
      return
    if parsed.path == "/api/detect-template":
      self.handle_detect_template()
      return
    if parsed.path == "/api/detect-red-symbols":
      self.handle_detect_red_symbols()
      return
    if parsed.path == "/api/segment-tile":
      self.handle_segment_tile()
      return
    if parsed.path == "/api/coco-sample":
      self.handle_coco_sample()
      return
    if parsed.path == "/api/coco-class-summary":
      self.handle_coco_class_summary()
      return
    if parsed.path == "/api/coco-class-examples":
      self.handle_coco_class_examples()
      return
    if parsed.path == "/api/symbol-matches":
      self.handle_symbol_matches()
      return
    write_error(self, "Route inconnue.", HTTPStatus.NOT_FOUND)

  def read_json(self):
    length = int(self.headers.get("Content-Length", "0"))
    if length <= 0:
      return {}
    return json.loads(self.rfile.read(length).decode("utf-8"))

  def handle_upload(self):
    ctype, pdict = cgi.parse_header(self.headers.get("Content-Type", ""))
    if ctype != "multipart/form-data":
      write_error(self, "Upload multipart attendu.")
      return
    pdict["boundary"] = bytes(pdict["boundary"], "utf-8")
    form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={
      "REQUEST_METHOD": "POST",
      "CONTENT_TYPE": self.headers.get("Content-Type"),
    })
    field = form["file"] if "file" in form else None
    if field is None or not field.filename:
      write_error(self, "Aucun PDF recu.")
      return
    name = safe_file_name(field.filename)
    if not name.lower().endswith(".pdf"):
      write_error(self, "Le fichier doit etre un PDF.")
      return
    pdf_id = f"{uuid.uuid4().hex}-{name}"
    dest = UPLOADS_DIR / pdf_id
    with dest.open("wb") as fh:
      shutil.copyfileobj(field.file, fh)
    try:
      doc = fitz.open(dest)
      page_count = doc.page_count
      doc.close()
    except Exception as exc:
      dest.unlink(missing_ok=True)
      write_error(self, f"PDF illisible: {exc}")
      return
    write_json(self, {"pdf_id": pdf_id, "name": name, "page_count": page_count})

  def handle_preview(self):
    try:
      payload = self.read_json()
      pdf_path = resolve_upload(payload.get("pdf_id", ""))
      page_index = max(0, int(payload.get("page", 1)) - 1)
      rows = max(1, min(20, int(payload.get("rows", 5))))
      cols = max(1, min(20, int(payload.get("cols", 5))))
      result = make_grid_overlay_preview(pdf_path, page_index, rows, cols)
    except Exception as exc:
      write_error(self, str(exc))
      return
    write_json(self, result)

  def handle_render_grid(self):
    try:
      payload = self.read_json()
      pdf_path = resolve_upload(payload.get("pdf_id", ""))
      page_index = max(0, int(payload.get("page", 1)) - 1)
      rows = max(1, min(20, int(payload.get("rows", 5))))
      cols = max(1, min(20, int(payload.get("cols", 5))))
      if rows * cols > 100:
        raise ValueError("Limite de securite: 100 cellules maximum par rendu.")
      dpi = max(120, min(600, int(payload.get("dpi", 300))))
      enhance_mode = payload.get("enhance_mode", "opencv")
      if enhance_mode not in {"none", "pil", "opencv"}:
        raise ValueError("Mode amelioration inconnu.")
      result = render_grid(pdf_path, page_index, rows, cols, dpi, enhance_mode, payload)
    except Exception as exc:
      write_error(self, str(exc))
      return
    write_json(self, result)

  def handle_render_tile(self):
    try:
      payload = self.read_json()
      pdf_path = resolve_upload(payload.get("pdf_id", ""))
      page_index = max(0, int(payload.get("page", 1)) - 1)
      rows = max(1, min(20, int(payload.get("rows", 5))))
      cols = max(1, min(20, int(payload.get("cols", 5))))
      dpi = max(120, min(600, int(payload.get("dpi", 300))))
      enhance_mode = payload.get("enhance_mode", "none")
      if enhance_mode not in {"none", "pil", "opencv"}:
        raise ValueError("Mode amelioration inconnu.")
      result = render_single_tile(pdf_path, page_index, rows, cols, dpi, enhance_mode, payload)
    except Exception as exc:
      write_error(self, str(exc))
      return
    write_json(self, result)

  def handle_detect_template(self):
    try:
      payload = self.read_json()
      result = detect_template(payload)
    except Exception as exc:
      write_error(self, str(exc))
      return
    write_json(self, result)

  def handle_detect_red_symbols(self):
    try:
      payload = self.read_json()
      result = detect_red_symbols(payload)
    except Exception as exc:
      write_error(self, str(exc))
      return
    write_json(self, result)

  def handle_segment_tile(self):
    try:
      payload = self.read_json()
      result = run_instance_segmentation(payload)
    except Exception as exc:
      write_error(self, str(exc))
      return
    write_json(self, result)

  def handle_coco_sample(self):
    try:
      payload = self.read_json()
      result = render_coco_sample(payload)
    except Exception as exc:
      write_error(self, str(exc))
      return
    write_json(self, result)

  def handle_coco_class_summary(self):
    try:
      payload = self.read_json()
      result = coco_class_summary(payload)
    except Exception as exc:
      write_error(self, str(exc))
      return
    write_json(self, result)

  def handle_coco_class_examples(self):
    try:
      payload = self.read_json()
      result = coco_class_examples(payload)
    except Exception as exc:
      write_error(self, str(exc))
      return
    write_json(self, result)

  def handle_symbol_matches(self):
    try:
      payload = self.read_json()
      result = symbol_visual_matches(payload)
    except Exception as exc:
      write_error(self, str(exc))
      return
    write_json(self, result)

  def serve_static(self, path):
    path = Path(path).resolve()
    if not path.exists() or not path.is_file():
      self.send_error(HTTPStatus.NOT_FOUND)
      return
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    data = path.read_bytes()
    self.send_response(HTTPStatus.OK)
    self.send_header("Content-Type", ctype)
    self.send_header("Content-Length", str(len(data)))
    self.end_headers()
    self.wfile.write(data)


def main():
  ensure_dirs()
  server = ThreadingHTTPServer((HOST, PORT), Handler)
  print(f"PDF Tile Lab: http://{HOST}:{PORT}")
  server.serve_forever()


if __name__ == "__main__":
  main()
