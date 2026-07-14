import json
from collections import Counter, defaultdict

import fitz
from PIL import ImageDraw

from .legend_detector import _detect_vertical_separator
from .pdf_utils import parse_page_spec, render_page, resolve_repo_pdf_path
from .settings import REPO_ROOT


def _round_color(color):
  if color is None:
    return None
  values = [int(round(max(0.0, min(1.0, value)) * 255)) for value in color[:3]]
  return values


def _color_key(color):
  if color is None:
    return "none"
  return ",".join(str(value) for value in color)


def _item_bbox(item):
  kind = item[0]
  if kind == "l":
    p1, p2 = item[1], item[2]
    return fitz.Rect(min(p1.x, p2.x), min(p1.y, p2.y), max(p1.x, p2.x), max(p1.y, p2.y))
  if kind == "re":
    return fitz.Rect(item[1])
  points = []
  for value in item[1:]:
    if hasattr(value, "x") and hasattr(value, "y"):
      points.append(value)
  if not points:
    return None
  return fitz.Rect(
    min(point.x for point in points),
    min(point.y for point in points),
    max(point.x for point in points),
    max(point.y for point in points),
  )


def _item_kind(item):
  return {
    "l": "line",
    "re": "rect",
    "c": "curve",
    "qu": "quad",
  }.get(item[0], item[0])


def _inspect_page(page, page_number, output_dir):
  separator = _detect_vertical_separator(page)
  search_clip = fitz.Rect(0, 0, max(separator["x"] - 4.0, 1.0), page.rect.height) if separator else page.rect
  kind_counts = Counter()
  color_counts = Counter()
  stroke_widths = Counter()
  primitive_count = 0
  kept_bboxes = []
  colors_by_kind = defaultdict(Counter)

  for drawing in page.get_drawings():
    stroke_color = _round_color(drawing.get("color"))
    fill_color = _round_color(drawing.get("fill"))
    width = round(float(drawing.get("width") or 0.0), 2)
    color_key = _color_key(stroke_color or fill_color)

    for item in drawing.get("items", []):
      bbox = _item_bbox(item)
      if bbox is None or bbox.is_empty:
        continue
      if not bbox.intersects(search_clip):
        continue
      kind = _item_kind(item)
      primitive_count += 1
      kind_counts[kind] += 1
      color_counts[color_key] += 1
      colors_by_kind[kind][color_key] += 1
      stroke_widths[str(width)] += 1
      if len(kept_bboxes) < 300:
        kept_bboxes.append((bbox, color_key, kind))

  preview_path = output_dir / f"page_{page_number:03d}_vector_preview.png"
  preview = render_page(page, zoom=1.4)
  draw = ImageDraw.Draw(preview)
  scale = 1.4
  for bbox, color_key, kind in kept_bboxes:
    outline = "#2563eb"
    if color_key.startswith("255,0,0") or color_key.startswith("255,"):
      outline = "#dc2626"
    elif color_key.endswith(",255") or ",255" in color_key:
      outline = "#1d4ed8"
    elif color_key.startswith("0,255") or color_key.startswith("0,"):
      outline = "#16a34a"
    draw.rectangle((bbox.x0 * scale, bbox.y0 * scale, bbox.x1 * scale, bbox.y1 * scale), outline=outline, width=2)
    if bbox.width > 10 and bbox.height > 10:
      draw.text((bbox.x0 * scale, bbox.y0 * scale), kind, fill=outline)
  preview.save(preview_path)

  return {
    "page": page_number,
    "primitive_count": primitive_count,
    "separator_x": round(separator["x"], 2) if separator else None,
    "search_clip": [round(search_clip.x0, 2), round(search_clip.y0, 2), round(search_clip.x1, 2), round(search_clip.y1, 2)],
    "kind_counts": dict(kind_counts.most_common()),
    "color_counts": dict(color_counts.most_common(12)),
    "stroke_widths": dict(stroke_widths.most_common(12)),
    "colors_by_kind": {kind: dict(counter.most_common(8)) for kind, counter in colors_by_kind.items()},
    "preview_path": preview_path.relative_to(REPO_ROOT).as_posix(),
  }


def inspect_pdf_vectors(pdf_relative_path, page_spec=None):
  pdf_path = resolve_repo_pdf_path(pdf_relative_path)
  output_dir = REPO_ROOT / "legend_zero" / "runs" / "_vector_inspections" / pdf_path.stem
  output_dir.mkdir(parents=True, exist_ok=True)

  pages = []
  with fitz.open(pdf_path) as document:
    page_numbers = parse_page_spec(page_spec, document.page_count) if page_spec else [1]
    for page_number in page_numbers[:3]:
      pages.append(_inspect_page(document[page_number - 1], page_number, output_dir))

  result = {
    "pdf_path": pdf_relative_path,
    "page_count": len(pages),
    "pages": pages,
  }
  result_path = output_dir / "vector_inspection.json"
  result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
  return result
