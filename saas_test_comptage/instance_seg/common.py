import json
import re
import unicodedata
from pathlib import Path

import cv2
import fitz
import numpy as np
from PIL import Image, ImageDraw


def ensure_dir(path):
  path = Path(path)
  path.mkdir(parents=True, exist_ok=True)
  return path


def load_json(path):
  return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, payload):
  path = Path(path)
  ensure_dir(path.parent)
  path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_text(value):
  ascii_value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
  return re.sub(r"\s+", " ", ascii_value).strip()


def slugify(value):
  cleaned = normalize_text(value).lower()
  cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
  return cleaned or "item"


def parse_page_spec(spec, page_count):
  if not spec:
    return list(range(1, page_count + 1))
  pages = set()
  for chunk in str(spec).split(","):
    part = chunk.strip()
    if not part:
      continue
    if "-" in part:
      start_raw, end_raw = part.split("-", 1)
      start = max(int(start_raw), 1)
      end = min(int(end_raw), page_count)
      if start > end:
        start, end = end, start
      pages.update(range(start, end + 1))
    else:
      page_number = int(part)
      if 1 <= page_number <= page_count:
        pages.add(page_number)
  if not pages:
    raise ValueError("Specification de pages invalide.")
  return sorted(pages)


def render_pdf_page(pdf_path, page_number, zoom=2.5, clip_rect=None):
  with fitz.open(pdf_path) as document:
    page = document[page_number - 1]
    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip_rect, alpha=False)
  return Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)


def tile_image(image, tile_size=1024, overlap=128):
  width, height = image.size
  stride = max(tile_size - overlap, 1)
  tiles = []

  y_positions = list(range(0, max(height - tile_size, 0) + 1, stride))
  if not y_positions or y_positions[-1] != max(height - tile_size, 0):
    y_positions.append(max(height - tile_size, 0))

  x_positions = list(range(0, max(width - tile_size, 0) + 1, stride))
  if not x_positions or x_positions[-1] != max(width - tile_size, 0):
    x_positions.append(max(width - tile_size, 0))

  seen = set()
  for y0 in y_positions:
    for x0 in x_positions:
      key = (x0, y0)
      if key in seen:
        continue
      seen.add(key)
      x1 = min(x0 + tile_size, width)
      y1 = min(y0 + tile_size, height)
      tiles.append(
        {
          "x0": int(x0),
          "y0": int(y0),
          "x1": int(x1),
          "y1": int(y1),
          "image": image.crop((x0, y0, x1, y1)),
        }
      )
  return tiles


def non_white_ratio(image, threshold=245):
  gray = np.asarray(image.convert("L"))
  return float(np.mean(gray < threshold))


def polygons_to_mask(width, height, segmentation):
  mask = Image.new("L", (width, height), 0)
  draw = ImageDraw.Draw(mask)
  for polygon in segmentation or []:
    if len(polygon) < 6:
      continue
    points = [(polygon[index], polygon[index + 1]) for index in range(0, len(polygon), 2)]
    draw.polygon(points, fill=1, outline=1)
  return np.asarray(mask, dtype=np.uint8)


def mask_to_polygons(mask, offset_x=0, offset_y=0, min_area=12):
  binary = (mask > 0).astype(np.uint8)
  contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
  polygons = []
  for contour in contours:
    area = cv2.contourArea(contour)
    if area < min_area:
      continue
    flattened = contour.reshape(-1, 2)
    if len(flattened) < 3:
      continue
    polygon = []
    for x, y in flattened:
      polygon.extend([float(x + offset_x), float(y + offset_y)])
    if len(polygon) >= 6:
      polygons.append(polygon)
  return polygons


def box_iou(box_a, box_b):
  ax0, ay0, ax1, ay1 = box_a
  bx0, by0, bx1, by1 = box_b
  inter_x0 = max(ax0, bx0)
  inter_y0 = max(ay0, by0)
  inter_x1 = min(ax1, bx1)
  inter_y1 = min(ay1, by1)
  inter_w = max(inter_x1 - inter_x0, 0.0)
  inter_h = max(inter_y1 - inter_y0, 0.0)
  inter_area = inter_w * inter_h
  if inter_area <= 0:
    return 0.0
  area_a = max(ax1 - ax0, 0.0) * max(ay1 - ay0, 0.0)
  area_b = max(bx1 - bx0, 0.0) * max(by1 - by0, 0.0)
  union = area_a + area_b - inter_area
  return inter_area / union if union > 0 else 0.0


def nms_records(records, iou_threshold=0.5):
  kept = []
  for record in sorted(records, key=lambda item: item.get("score", 0.0), reverse=True):
    should_keep = True
    for existing in kept:
      if record.get("category_id") == existing.get("category_id") and box_iou(record["bbox_xyxy"], existing["bbox_xyxy"]) >= iou_threshold:
        should_keep = False
        break
    if should_keep:
      kept.append(record)
  return kept
