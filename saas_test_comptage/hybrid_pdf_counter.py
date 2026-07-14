import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

import cv2
import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def parse_args():
  parser = argparse.ArgumentParser(
    description="Analyse un PDF de plan en priorisant l'information vectorielle."
  )
  parser.add_argument("--pdf", required=True, help="PDF a analyser.")
  parser.add_argument("--output", default="hybrid_counter_output", help="Dossier de sortie.")
  parser.add_argument("--pages", nargs="*", type=int, help="Pages 1-based a analyser. Par defaut: toutes.")
  parser.add_argument("--preview-dpi", type=int, default=110, help="Resolution des apercus.")
  parser.add_argument("--max-groups", type=int, default=80, help="Nombre max de groupes exportes par page. 0 = tous.")
  parser.add_argument("--min-count", type=int, default=3, help="Nombre mini d'occurrences pour retenir un groupe.")
  parser.add_argument("--min-items", type=int, default=12, help="Complexite minimale d'un drawing pour etre un candidat.")
  parser.add_argument("--min-size", type=float, default=6.0, help="Taille mini d'un candidat vectoriel.")
  parser.add_argument("--max-size", type=float, default=140.0, help="Taille max d'un candidat vectoriel.")
  parser.add_argument("--vector-similarity-threshold", type=float, default=0.16, help="Distance visuelle max pour regrouper des symboles similaires.")
  parser.add_argument("--vector-size-tolerance", type=float, default=0.22, help="Tolerance relative de taille pour regrouper des symboles similaires.")
  parser.add_argument("--vector-color-distance-threshold", type=float, default=0.18, help="Distance couleur max entre symboles vectoriels similaires.")
  parser.add_argument("--template-threshold", type=float, default=0.68, help="Seuil de matching pour les symboles de legende.")
  parser.add_argument("--template-min-scale", type=float, default=0.55, help="Echelle minimale du symbole sur le plan.")
  parser.add_argument("--template-max-scale", type=float, default=1.9, help="Echelle maximale du symbole sur le plan.")
  parser.add_argument("--template-scale-step", type=float, default=0.15, help="Pas d'echelle pour le matching multi-scale.")
  parser.add_argument("--template-scale-window", type=float, default=0.3, help="Fenetre autour de l'echelle de reference du plan.")
  parser.add_argument("--template-reference-count", type=int, default=6, help="Nombre de symboles de legende utilises pour estimer l'echelle du plan.")
  parser.add_argument("--template-shape-threshold", type=float, default=0.24, help="Distance maximale de forme entre legende et occurrence detectee.")
  parser.add_argument("--template-color-distance-threshold", type=float, default=105.0, help="Distance couleur maximale entre legende et occurrence.")
  parser.add_argument("--template-scale-consistency", type=float, default=0.1, help="Tolerance d'echelle acceptee autour de la taille dominante d'un symbole.")
  parser.add_argument("--feedback-priors", default="hybrid_feedback/learned_priors.json", help="JSON de priors appris depuis les feedbacks.")
  parser.add_argument("--allow-vector-fallback", action="store_true", help="Autorise le fallback groupes vectoriels quand aucune legende n'est exploitable.")
  return parser.parse_args()


def load_feedback_priors(path):
  priors_path = Path(path)
  if not priors_path.exists():
    return {}
  try:
    payload = json.loads(priors_path.read_text(encoding="utf-8"))
  except Exception:
    return {}
  return payload.get("by_signature", {})


def classify_page(profile):
  if profile["drawings"] >= 5000 and (profile["text_chars"] >= 500 or profile["words"] >= 100):
    return "vector"
  if profile["drawings"] >= 1000 and profile["image_blocks"] <= max(20, profile["text_blocks"] * 2):
    return "mixed"
  return "raster"


def round_color(color):
  if not color:
    return None
  return tuple(round(float(value), 3) for value in color)


def extract_points(value):
  if hasattr(value, "x") and hasattr(value, "y"):
    return [(float(value.x), float(value.y))]
  if hasattr(value, "x0") and hasattr(value, "y0") and hasattr(value, "x1") and hasattr(value, "y1"):
    return [
      (float(value.x0), float(value.y0)),
      (float(value.x1), float(value.y1)),
    ]
  if hasattr(value, "ul") and hasattr(value, "ur") and hasattr(value, "ll") and hasattr(value, "lr"):
    return [
      (float(value.ul.x), float(value.ul.y)),
      (float(value.ur.x), float(value.ur.y)),
      (float(value.ll.x), float(value.ll.y)),
      (float(value.lr.x), float(value.lr.y)),
    ]
  if isinstance(value, (tuple, list)):
    points = []
    for item in value:
      points.extend(extract_points(item))
    return points
  return []


def normalize_points(points, rect):
  width = max(rect.width, 1e-6)
  height = max(rect.height, 1e-6)
  normalized = []
  for x, y in points:
    normalized.append((round((x - rect.x0) / width, 2), round((y - rect.y0) / height, 2)))
  return normalized


def candidate_fingerprint(page, drawing, zoom=3.0, target_size=48):
  rect = fitz.Rect(drawing["rect"])
  margin_x = max(rect.width * 0.15, 2.0)
  margin_y = max(rect.height * 0.15, 2.0)
  clip = fitz.Rect(rect.x0 - margin_x, rect.y0 - margin_y, rect.x1 + margin_x, rect.y1 + margin_y)
  pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
  image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples).convert("L")
  image = image.resize((target_size, target_size), Image.Resampling.BILINEAR)
  threshold = sum(image.getdata()) / max(len(image.getdata()), 1)
  binary = image.point(lambda value: 255 if value > threshold else 0, mode="L")
  digest = hashlib.sha1(binary.tobytes()).hexdigest()
  return digest, binary


def color_distance_tuple(color_a, color_b):
  if not color_a or not color_b:
    return None
  vector_a = np.array(color_a, dtype=np.float32)
  vector_b = np.array(color_b, dtype=np.float32)
  return float(np.sqrt(((vector_a - vector_b) ** 2).sum()))


def size_distance_ratio(size_a, size_b):
  width_a, height_a = size_a
  width_b, height_b = size_b
  width_ratio = abs(width_a - width_b) / max(max(width_a, width_b), 1e-6)
  height_ratio = abs(height_a - height_b) / max(max(height_a, height_b), 1e-6)
  return max(width_ratio, height_ratio)


def extract_vector_candidate(page, drawing):
  fingerprint, binary = candidate_fingerprint(page, drawing)
  rect = drawing["rect"]
  return {
    "fingerprint": fingerprint,
    "binary": np.array(binary, dtype=np.uint8),
    "rect": rect,
    "bbox_size": [round(rect.width, 2), round(rect.height, 2)],
    "stroke_width": round(float(drawing.get("width", 0.0) or 0.0), 2),
    "color": round_color(drawing.get("color")),
    "fill": round_color(drawing.get("fill")),
    "items_len": len(drawing.get("items", [])),
    "box": [
      round(rect.x0, 2),
      round(rect.y0, 2),
      round(rect.x1, 2),
      round(rect.y1, 2),
    ],
  }


def vector_candidates_match(reference, candidate, args):
  size_distance = size_distance_ratio(reference["bbox_size"], candidate["bbox_size"])
  if size_distance > args.vector_size_tolerance:
    return False

  shape_distance = binary_distance_arrays(reference["binary"], candidate["binary"])
  if shape_distance > args.vector_similarity_threshold:
    return False

  color_distance = color_distance_tuple(reference.get("color"), candidate.get("color"))
  if color_distance is not None and color_distance > args.vector_color_distance_threshold:
    return False

  fill_distance = color_distance_tuple(reference.get("fill"), candidate.get("fill"))
  if fill_distance is not None and fill_distance > args.vector_color_distance_threshold:
    return False
  return True


def is_candidate_drawing(drawing, args):
  rect = drawing["rect"]
  width = float(rect.width)
  height = float(rect.height)
  if width < args.min_size or height < args.min_size:
    return False
  if width > args.max_size or height > args.max_size:
    return False
  ratio = max(width / max(height, 1e-6), height / max(width, 1e-6))
  if ratio > 5.0:
    return False
  if len(drawing.get("items", [])) < args.min_items:
    return False
  return True


def profile_page(page):
  drawings = page.get_drawings()
  raw = page.get_text("rawdict")
  text = page.get_text("text")
  words = page.get_text("words")
  technical_scale = extract_technical_scale(page)
  profile = {
    "page_size": [round(page.rect.width, 2), round(page.rect.height, 2)],
    "drawings": len(drawings),
    "image_refs": len(page.get_images(full=True)),
    "text_chars": len(text),
    "text_blocks": sum(1 for block in raw.get("blocks", []) if block.get("type") == 0),
    "image_blocks": sum(1 for block in raw.get("blocks", []) if block.get("type") == 1),
    "words": len(words),
    "technical_scale": technical_scale["label"] if technical_scale else None,
    "technical_scale_denominator": technical_scale["denominator"] if technical_scale else None,
    "technical_scale_source_text": technical_scale["line_text"] if technical_scale else None,
  }
  profile["mode"] = classify_page(profile)
  return drawings, profile


def collect_vector_groups(page, drawings, args):
  exact_groups = defaultdict(list)
  for drawing in drawings:
    if not is_candidate_drawing(drawing, args):
      continue
    candidate = extract_vector_candidate(page, drawing)
    exact_groups[candidate["fingerprint"]].append(candidate)

  merged_groups = []
  for _, items in exact_groups.items():
    items.sort(key=lambda item: (-item["items_len"], -(item["bbox_size"][0] * item["bbox_size"][1])))
    candidate = items[0]
    candidate["members"] = items[:]
    matched_index = None
    for index, existing in enumerate(merged_groups):
      if vector_candidates_match(existing["representative"], candidate, args):
        matched_index = index
        break

    if matched_index is None:
      merged_groups.append(
        {
          "representative": candidate,
          "members": items[:],
        }
      )
    else:
      merged_groups[matched_index]["members"].extend(items)

  kept = []
  for merged in merged_groups:
    members = merged["members"]
    if len(members) < args.min_count:
      continue
    representative = merged["representative"]
    sample_image = Image.fromarray(representative["binary"], mode="L")
    kept.append(
      {
        "signature": representative["fingerprint"],
        "count": len(members),
        "bbox_size": representative["bbox_size"],
        "stroke_width": representative["stroke_width"],
        "color": representative["color"],
        "fill": representative["fill"],
        "items_len": representative["items_len"],
        "sample_image": sample_image,
        "similarity_mode": "visual_cluster",
        "boxes": [member["box"] for member in members],
      }
    )

  kept.sort(key=lambda group: (-group["count"], -group["items_len"], group["bbox_size"][0] * group["bbox_size"][1]))
  if args.max_groups and args.max_groups > 0:
    return kept[:args.max_groups]
  return kept


def ensure_preview_font():
  try:
    return ImageFont.truetype("DejaVuSans.ttf", 16)
  except OSError:
    return ImageFont.load_default()


def group_words_into_lines(words):
  grouped = defaultdict(list)
  for word in words:
    key = (word[5], word[6])
    grouped[key].append(word)

  lines = []
  for (_, _), items in grouped.items():
    items.sort(key=lambda item: item[0])
    x0 = min(item[0] for item in items)
    y0 = min(item[1] for item in items)
    x1 = max(item[2] for item in items)
    y1 = max(item[3] for item in items)
    text = " ".join(item[4] for item in items).strip()
    lines.append({"bbox": [x0, y0, x1, y1], "text": text})
  lines.sort(key=lambda line: (line["bbox"][1], line["bbox"][0]))
  return lines


def normalize_scale_token(token):
  cleaned = token.strip().lower().replace(" ", "")
  cleaned = cleaned.replace("e", "")
  cleaned = cleaned.replace(":", "/")
  if not cleaned.startswith("1/"):
    return None
  denominator = cleaned.split("/", 1)[1]
  if not denominator.isdigit():
    return None
  return f"1/{int(denominator)}"


def extract_technical_scale(page):
  words = page.get_text("words")
  if not words:
    return None

  lines = group_words_into_lines(words)
  pattern = re.compile(r"1\s*[:/]\s*(\d{2,4})(?:e)?", re.IGNORECASE)
  candidates = []
  page_width = float(page.rect.width)
  page_height = float(page.rect.height)

  for line in lines:
    text = line["text"]
    upper_text = text.upper()
    matches = pattern.findall(text)
    if not matches:
      continue

    has_scale_keyword = any(keyword in upper_text for keyword in ["ECHELLE", "Echelle", "ECH", "Ech"])
    for raw_denominator in matches:
      denominator = int(raw_denominator)
      if denominator < 5 or denominator > 1000:
        continue

      score = 0
      if has_scale_keyword:
        score += 10
      x0, y0, x1, y1 = line["bbox"]
      if x0 >= page_width * 0.65:
        score += 2
      if y0 >= page_height * 0.75:
        score += 3
      if y0 >= page_height * 0.5:
        score += 1

      candidates.append(
        {
          "label": f"1/{denominator}",
          "denominator": denominator,
          "score": score,
          "line_text": text.strip(),
          "bbox": [round(value, 2) for value in line["bbox"]],
        }
      )

  if not candidates:
    return None

  candidates.sort(key=lambda item: (-item["score"], item["bbox"][1], item["bbox"][0]))
  best = candidates[0]
  if best["score"] <= 0:
    return None
  return best


def normalize_binary_image(image, target_size=48):
  resized = image.convert("L").resize((target_size, target_size), Image.Resampling.BILINEAR)
  threshold = sum(resized.getdata()) / max(len(resized.getdata()), 1)
  return resized.point(lambda value: 255 if value > threshold else 0, mode="L")


def render_clip(page, rect, zoom=3.0):
  pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect, alpha=False)
  image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
  return image


def crop_binary_content(image, padding=2):
  array = np.array(image)
  ys, xs = np.where(array < 245)
  if len(xs) == 0 or len(ys) == 0:
    return image
  x0 = max(int(xs.min()) - padding, 0)
  y0 = max(int(ys.min()) - padding, 0)
  x1 = min(int(xs.max()) + padding + 1, image.width)
  y1 = min(int(ys.max()) + padding + 1, image.height)
  return image.crop((x0, y0, x1, y1))


def extract_symbol_color(image):
  rgb = np.array(image.convert("RGB"))
  non_white = np.any(rgb < 235, axis=2)
  if not np.any(non_white):
    return None

  pixels = rgb[non_white]
  chroma = pixels.max(axis=1) - pixels.min(axis=1)
  chromatic_pixels = pixels[chroma >= 30]
  if len(chromatic_pixels) < 12:
    return None

  mean = chromatic_pixels.mean(axis=0)
  return [int(round(value)) for value in mean.tolist()]


def extract_legend_entries(page, output_dir, page_number):
  words = page.get_text("words")
  if not words:
    return []

  page_width = float(page.rect.width)
  candidate_words = [word for word in words if word[0] > page_width * 0.65]
  lines = group_words_into_lines(candidate_words)
  anchor_indexes = [
    index for index, line in enumerate(lines)
    if "LEGENDE" in line["text"].upper()
  ]
  if anchor_indexes:
    anchor_index = anchor_indexes[0]
    filtered_lines = []
    anchor_y = lines[anchor_index]["bbox"][1]
    previous_y = anchor_y
    for line in lines[anchor_index:]:
      current_y = line["bbox"][1]
      if current_y - previous_y > 80:
        break
      filtered_lines.append(line)
      previous_y = current_y
    lines = filtered_lines

  entries = []
  output_dir.mkdir(parents=True, exist_ok=True)

  for index, line in enumerate(lines, start=1):
    text = line["text"].strip()
    if len(text) < 4:
      continue
    if not any(character.isalpha() for character in text):
      continue
    if text.upper() in {"LEGENDE", "ECLAIRAGES", "LEGENDE ECLAIRAGES"}:
      continue

    x0, y0, x1, y1 = line["bbox"]
    clip = fitz.Rect(max(x0 - 120, 0), max(y0 - 10, 0), max(x0 - 8, 0), min(y1 + 10, page.rect.height))
    if clip.width < 8 or clip.height < 8:
      continue

    image = render_clip(page, clip)
    binary = crop_binary_content(normalize_binary_image(image))
    if binary.width < 14 or binary.height < 14:
      continue
    if binary.width * binary.height < 260:
      continue

    sample_path = output_dir / f"page_{page_number:03d}_legend_{index:02d}.png"
    binary.save(sample_path)
    entries.append(
      {
        "text": text,
        "bbox": [round(value, 2) for value in line["bbox"]],
        "match_rgb": extract_symbol_color(image),
        "sample_image": str(sample_path),
      }
    )

  return entries


def compute_matching_zoom(page, preferred_zoom=3.0, max_dimension_px=5500):
  page_max_dim = max(float(page.rect.width), float(page.rect.height), 1.0)
  adaptive_zoom = min(preferred_zoom, max_dimension_px / page_max_dim)
  return max(adaptive_zoom, 1.2)


def render_page_binary(page, zoom=None):
  zoom = zoom or compute_matching_zoom(page)
  pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
  rgb_image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
  array = np.array(rgb_image.convert("L"))
  _, binary = cv2.threshold(array, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
  return binary, np.array(rgb_image), zoom


def generate_scales(min_scale, max_scale, step):
  scales = []
  value = min_scale
  while value <= max_scale + 1e-9:
    scales.append(round(value, 4))
    value += step
  return scales


def build_template_array(template_path):
  template = Image.open(template_path).convert("L")
  base_template = 255 - np.array(template)
  ink_pixels = int(np.count_nonzero(base_template > 0))
  return base_template, ink_pixels


def binary_distance_arrays(array_a, array_b):
  image_a = crop_binary_content(Image.fromarray(array_a.astype(np.uint8), mode="L"))
  image_b = crop_binary_content(Image.fromarray(array_b.astype(np.uint8), mode="L"))
  normalized_a = normalize_binary_image(image_a)
  normalized_b = normalize_binary_image(image_b)
  pixels_a = np.array(normalized_a, dtype=np.float32)
  pixels_b = np.array(normalized_b, dtype=np.float32)
  diff = np.abs(pixels_a - pixels_b).mean() / 255.0
  return float(diff)


def build_color_search_image(search_rgb, target_rgb):
  if not target_rgb:
    return None

  rgb = search_rgb.astype(np.float32)
  target = np.array(target_rgb, dtype=np.float32)
  diff = np.sqrt(((rgb - target) ** 2).sum(axis=2))
  chroma = search_rgb.max(axis=2) - search_rgb.min(axis=2)
  mask = (diff <= 95) & (chroma >= 25)
  if int(mask.sum()) < 150:
    return None
  return mask.astype(np.uint8) * 255


def color_distance_rgb(rgb_a, rgb_b):
  if not rgb_a or not rgb_b:
    return None
  vector_a = np.array(rgb_a, dtype=np.float32)
  vector_b = np.array(rgb_b, dtype=np.float32)
  return float(np.sqrt(((vector_a - vector_b) ** 2).sum()))


def scale_window_scales(reference_scale, args):
  if reference_scale is None:
    return generate_scales(args.template_min_scale, args.template_max_scale, args.template_scale_step)

  min_scale = max(args.template_min_scale, reference_scale - args.template_scale_window)
  max_scale = min(args.template_max_scale, reference_scale + args.template_scale_window)
  return generate_scales(min_scale, max_scale, args.template_scale_step)


def estimate_reference_scale(search_region, template_specs, args):
  if not template_specs:
    return None

  coarse_step = max(args.template_scale_step * 2, 0.25)
  coarse_scales = generate_scales(args.template_min_scale, args.template_max_scale, coarse_step)
  if not coarse_scales:
    return None

  scored_scales = []
  for scale in coarse_scales:
    total_score = 0.0
    contributors = 0
    for spec in template_specs:
      base_template = spec["template"]
      width = max(int(round(base_template.shape[1] * scale)), 6)
      height = max(int(round(base_template.shape[0] * scale)), 6)
      if width >= search_region.shape[1] or height >= search_region.shape[0]:
        continue

      template_array = cv2.resize(
        base_template,
        (width, height),
        interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR,
      )
      result = cv2.matchTemplate(search_region, template_array, cv2.TM_CCOEFF_NORMED)
      _, max_value, _, _ = cv2.minMaxLoc(result)
      weighted = max_value * spec["weight"]
      total_score += weighted
      if max_value >= max(args.template_threshold - 0.08, 0.45):
        contributors += 1

    if contributors:
      scored_scales.append((scale, total_score, contributors))

  if not scored_scales:
    return None

  scored_scales.sort(key=lambda item: (-item[2], -item[1], item[0]))
  return scored_scales[0][0]


def box_iou(candidate_a, candidate_b):
  x1 = max(candidate_a["x1"], candidate_b["x1"])
  y1 = max(candidate_a["y1"], candidate_b["y1"])
  x2 = min(candidate_a["x2"], candidate_b["x2"])
  y2 = min(candidate_a["y2"], candidate_b["y2"])
  if x2 <= x1 or y2 <= y1:
    return 0.0

  intersection = (x2 - x1) * (y2 - y1)
  area_a = max(candidate_a["x2"] - candidate_a["x1"], 0) * max(candidate_a["y2"] - candidate_a["y1"], 0)
  area_b = max(candidate_b["x2"] - candidate_b["x1"], 0) * max(candidate_b["y2"] - candidate_b["y1"], 0)
  union = area_a + area_b - intersection
  if union <= 0:
    return 0.0
  return intersection / union


def non_max_suppression_boxes(candidates, min_distance, iou_threshold=0.35):
  ordered = sorted(candidates, key=lambda item: item["score"], reverse=True)
  kept = []
  for candidate in ordered:
    center_x = (candidate["x1"] + candidate["x2"]) / 2
    center_y = (candidate["y1"] + candidate["y2"]) / 2
    too_close = False
    for existing in kept:
      ex = (existing["x1"] + existing["x2"]) / 2
      ey = (existing["y1"] + existing["y2"]) / 2
      if box_iou(candidate, existing) >= iou_threshold:
        too_close = True
        break
      x_threshold = max(min_distance, min(candidate["x2"] - candidate["x1"], existing["x2"] - existing["x1"]) * 0.55)
      y_threshold = max(min_distance, min(candidate["y2"] - candidate["y1"], existing["y2"] - existing["y1"]) * 0.55)
      if abs(center_x - ex) <= x_threshold and abs(center_y - ey) <= y_threshold:
        too_close = True
        break
    if not too_close:
      kept.append(candidate)
  return kept


def dominant_scale_from_candidates(candidates):
  if not candidates:
    return None

  weighted = defaultdict(float)
  for candidate in candidates:
    weighted[round(candidate["scale"], 4)] += float(candidate.get("score", 0.0))

  ordered = sorted(weighted.items(), key=lambda item: (-item[1], item[0]))
  return ordered[0][0]


def page_scale_anchor(groups):
  scales = [
    group.get("dominant_scale") or group.get("matched_scale") or group.get("reference_scale")
    for group in groups
    if group.get("count", 0) > 0
  ]
  scales = [float(scale) for scale in scales if scale is not None]
  if not scales:
    return None
  return round(float(np.median(np.array(scales, dtype=np.float32))), 3)


def resolve_reference_scale(estimated_reference_scale, technical_reference_scale):
  if technical_reference_scale is None:
    return estimated_reference_scale
  if estimated_reference_scale is None:
    return technical_reference_scale
  if abs(estimated_reference_scale - technical_reference_scale) <= 0.18:
    return round(technical_reference_scale * 0.65 + estimated_reference_scale * 0.35, 4)
  return round(technical_reference_scale, 4)


def match_legend_templates(page, legend_entries, args, page_legend_entries=None, technical_reference_scale=None, feedback_priors=None):
  if not legend_entries:
    return []

  page_binary, page_rgb, zoom = render_page_binary(page)
  search_image = 255 - page_binary
  if page_legend_entries:
    legend_x0 = min(entry["bbox"][0] for entry in page_legend_entries)
    search_limit_x = max(int((legend_x0 - 20) * zoom), 1)
  else:
    search_limit_x = search_image.shape[1]
  search_region_default = search_image[:, :search_limit_x]
  search_region_rgb = page_rgb[:, :search_limit_x]
  groups = []
  template_specs = []
  color_cache = {}

  for entry in legend_entries:
    template_path = entry.get("sample_image")
    if not template_path:
      continue
    base_template, ink_pixels = build_template_array(template_path)
    if base_template.shape[0] < 6 or base_template.shape[1] < 6:
      continue
    if ink_pixels < 40:
      continue
    template_specs.append(
      {
        "entry": entry,
        "template": base_template,
        "ink_pixels": ink_pixels,
        "weight": max(np.sqrt(ink_pixels), 1.0),
      }
    )

  if not template_specs:
    return []

  template_specs.sort(key=lambda item: (-item["ink_pixels"], -item["template"].shape[0] * item["template"].shape[1]))
  reference_specs = template_specs[:max(args.template_reference_count, 1)]
  estimated_reference_scale = estimate_reference_scale(search_region_default, reference_specs, args)
  reference_scale = resolve_reference_scale(estimated_reference_scale, technical_reference_scale)

  for spec in template_specs:
    entry = spec["entry"]
    template_path = entry.get("sample_image")
    base_template = spec["template"]
    signature = hashlib.sha1(entry["text"].encode("utf-8")).hexdigest()
    prior = (feedback_priors or {}).get(signature, {})
    if prior.get("ignore"):
      continue

    score_delta = float(prior.get("score_delta", 0.0) or 0.0)
    shape_multiplier = float(prior.get("shape_multiplier", 1.0) or 1.0)
    color_multiplier = float(prior.get("color_multiplier", 1.0) or 1.0)
    scale_multiplier = float(prior.get("scale_multiplier", 1.0) or 1.0)
    prefer_color_only = bool(prior.get("prefer_color_only"))
    allow_mono_fallback = bool(prior.get("allow_mono_fallback"))
    match_rgb = entry.get("match_rgb")
    scales = scale_window_scales(reference_scale, args)

    region_specs = [("mono", search_region_default, min(max(args.template_threshold + score_delta, 0.4), 0.95))]
    if match_rgb:
      color_key = tuple(match_rgb)
      if color_key not in color_cache:
        color_cache[color_key] = build_color_search_image(search_region_rgb, match_rgb)
      color_region = color_cache[color_key]
      if color_region is not None:
        region_specs = [("color", color_region, min(max(args.template_threshold - 0.03 + score_delta, 0.45), 0.92))]
        if allow_mono_fallback or not prefer_color_only:
          region_specs.append(("mono_fallback", search_region_default, min(max(args.template_threshold + 0.02 + score_delta, 0.5), 0.95)))
      elif prefer_color_only:
        continue

    kept = []
    min_distance = max(10, int(min(base_template.shape[0], base_template.shape[1]) * args.template_min_scale * 0.9))
    for region_name, proposal_region, proposal_threshold in region_specs:
      candidates = []
      for scale in scales:
        width = max(int(round(base_template.shape[1] * scale)), 6)
        height = max(int(round(base_template.shape[0] * scale)), 6)
        if width >= proposal_region.shape[1] or height >= proposal_region.shape[0]:
          continue

        if scale == 1.0:
          template_array = base_template
        else:
          template_array = cv2.resize(base_template, (width, height), interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR)

        result = cv2.matchTemplate(proposal_region, template_array, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(result >= proposal_threshold)
        for y, x in zip(ys.tolist(), xs.tolist()):
          candidates.append(
            {
              "x1": x,
              "y1": y,
              "x2": x + width,
              "y2": y + height,
              "score": float(result[y, x]),
              "scale": scale,
              "proposal_region": region_name,
            }
          )

      dominant_scale = dominant_scale_from_candidates(candidates)
      if dominant_scale is not None:
        candidates = [
          candidate
          for candidate in candidates
          if abs(candidate["scale"] - dominant_scale) <= (args.template_scale_consistency * scale_multiplier)
        ]

      kept = non_max_suppression_boxes(candidates, min_distance)
      validated = []
      for candidate in kept:
        crop = search_region_default[candidate["y1"]:candidate["y2"], candidate["x1"]:candidate["x2"]]
        if crop.size == 0:
          continue
        shape_distance = binary_distance_arrays(base_template, crop)
        shape_limit = args.template_shape_threshold * shape_multiplier
        if region_name == "mono_fallback":
          shape_limit *= 0.9
        if shape_distance > shape_limit:
          continue

        color_distance = None
        if match_rgb:
          rgb_crop = search_region_rgb[candidate["y1"]:candidate["y2"], candidate["x1"]:candidate["x2"]]
          candidate_rgb = extract_symbol_color(Image.fromarray(rgb_crop))
          color_distance = color_distance_rgb(match_rgb, candidate_rgb)
          if candidate_rgb is None and region_name in {"mono", "mono_fallback"}:
            continue
          color_limit = args.template_color_distance_threshold * color_multiplier
          if region_name == "mono_fallback":
            color_limit *= 0.8
          if color_distance is not None and color_distance > color_limit:
            continue

        candidate["shape_distance"] = shape_distance
        candidate["color_distance"] = color_distance
        validated.append(candidate)

      kept = validated
      if kept:
        dominant_scale = dominant_scale_from_candidates(kept) or dominant_scale
        if dominant_scale is not None:
          kept = [
            candidate
            for candidate in kept
            if abs(candidate["scale"] - dominant_scale) <= (args.template_scale_consistency * scale_multiplier)
          ]
        break

    if not kept:
      continue

    average_scale = sum(candidate.get("scale", 1.0) for candidate in kept) / len(kept)

    groups.append(
      {
        "signature": signature,
        "count": len(kept),
        "bbox_size": [
          round((base_template.shape[1] * average_scale) / zoom, 2),
          round((base_template.shape[0] * average_scale) / zoom, 2),
        ],
        "stroke_width": 0.0,
        "color": None,
        "fill": None,
        "items_len": 0,
        "sample_image": template_path,
        "label_guess": entry["text"],
        "match_rgb": entry.get("match_rgb"),
        "label_score": round(sum(candidate["score"] for candidate in kept) / len(kept), 4),
        "shape_score": round(sum(candidate["shape_distance"] for candidate in kept) / len(kept), 4),
        "color_score": round(sum(candidate["color_distance"] for candidate in kept if candidate.get("color_distance") is not None) / max(sum(1 for candidate in kept if candidate.get("color_distance") is not None), 1), 2) if any(candidate.get("color_distance") is not None for candidate in kept) else None,
        "proposal_region": kept[0].get("proposal_region"),
        "feedback_rule": prior.get("rule"),
        "dominant_scale": round(dominant_scale, 3) if dominant_scale is not None else None,
        "matched_scale": round(average_scale, 3),
        "estimated_reference_scale": round(estimated_reference_scale, 3) if estimated_reference_scale is not None else None,
        "technical_reference_scale": round(technical_reference_scale, 3) if technical_reference_scale is not None else None,
        "reference_scale": round(reference_scale, 3) if reference_scale is not None else None,
        "boxes": [
          [
            round(candidate["x1"] / zoom, 2),
            round(candidate["y1"] / zoom, 2),
            round(candidate["x2"] / zoom, 2),
            round(candidate["y2"] / zoom, 2),
          ]
          for candidate in kept
        ],
      }
    )

  groups.sort(key=lambda group: (-group["count"], group["label_guess"]))
  if args.max_groups and args.max_groups > 0:
    return groups[:args.max_groups]
  return groups


def image_distance(path_a, path_b):
  image_a = normalize_binary_image(Image.open(path_a))
  image_b = normalize_binary_image(Image.open(path_b))
  pixels_a = list(image_a.getdata())
  pixels_b = list(image_b.getdata())
  diff = sum(abs(a - b) for a, b in zip(pixels_a, pixels_b))
  return diff / (255.0 * len(pixels_a))


def assign_legend_labels(groups, legend_entries, threshold=0.22):
  for group in groups:
    best_text = None
    best_score = None
    sample_path = group.get("sample_image")
    if not sample_path:
      continue

    for entry in legend_entries:
      score = image_distance(sample_path, entry["sample_image"])
      if best_score is None or score < best_score:
        best_score = score
        best_text = entry["text"]

    if best_text is not None and best_score is not None and best_score <= threshold:
      group["label_guess"] = best_text
      group["label_score"] = round(best_score, 4)
    else:
      group["label_guess"] = None
      group["label_score"] = round(best_score, 4) if best_score is not None else None


def make_page_preview(page, groups, output_path, dpi):
  zoom = dpi / 72.0
  pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
  image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
  draw = ImageDraw.Draw(image)
  font = ensure_preview_font()
  palette = [
    "#e74c3c",
    "#2980b9",
    "#27ae60",
    "#f39c12",
    "#8e44ad",
    "#16a085",
    "#d35400",
    "#2c3e50",
  ]

  for index, group in enumerate(groups, start=1):
    color = palette[(index - 1) % len(palette)]
    for box in group["boxes"]:
      x0, y0, x1, y1 = [value * zoom for value in box]
      draw.rectangle((x0, y0, x1, y1), outline=color, width=2)
      label = f"G{index}:{group['count']}"
      left, top, right, bottom = draw.textbbox((x0, y0), label, font=font)
      draw.rectangle((left, top, right + 6, bottom + 4), fill=color)
      draw.text((x0 + 3, y0 + 1), label, fill="white", font=font)

  image.save(output_path)


def analyze_pdf(args):
  pdf_path = Path(args.pdf)
  feedback_priors = load_feedback_priors(args.feedback_priors)
  output_dir = Path(args.output)
  output_dir.mkdir(parents=True, exist_ok=True)
  previews_dir = output_dir / "previews"
  previews_dir.mkdir(parents=True, exist_ok=True)
  groups_dir = output_dir / "groups"
  groups_dir.mkdir(parents=True, exist_ok=True)
  legend_dir = output_dir / "legend"
  legend_dir.mkdir(parents=True, exist_ok=True)

  document = fitz.open(pdf_path)
  page_numbers = args.pages or list(range(1, document.page_count + 1))
  page_profiles = {}
  page_drawings = {}
  page_legends = {}
  best_legend_page = None
  best_legend_entries = []
  technical_scale_samples = defaultdict(list)

  for page_number in page_numbers:
    page = document[page_number - 1]
    drawings, profile = profile_page(page)
    page_profiles[page_number] = profile
    page_drawings[page_number] = drawings
    entries = extract_legend_entries(page, legend_dir, page_number)
    page_legends[page_number] = entries
    if len(entries) > len(best_legend_entries):
      best_legend_entries = entries
      best_legend_page = page_number

  for page_number in page_numbers:
    profile = page_profiles[page_number]
    technical_scale_denominator = profile.get("technical_scale_denominator")
    page_legend_entries = page_legends.get(page_number, [])
    if not technical_scale_denominator or not page_legend_entries:
      continue

    page = document[page_number - 1]
    groups = match_legend_templates(page, page_legend_entries, args, page_legend_entries=page_legend_entries, feedback_priors=feedback_priors)
    anchor = page_scale_anchor(groups)
    if anchor is not None:
      technical_scale_samples[technical_scale_denominator].append(anchor)

  technical_scale_reference_map = {
    denominator: round(float(np.median(np.array(values, dtype=np.float32))), 3)
    for denominator, values in technical_scale_samples.items()
    if values
  }

  report = {
    "pdf": str(pdf_path),
    "page_count": document.page_count,
    "shared_legend_source_page": best_legend_page,
    "technical_scale_reference_map": technical_scale_reference_map,
    "pages": [],
  }

  for page_number in page_numbers:
    page = document[page_number - 1]
    drawings = page_drawings[page_number]
    profile = page_profiles[page_number]
    groups = []
    preview_path = None
    technical_reference_scale = technical_scale_reference_map.get(profile.get("technical_scale_denominator"))

    if profile["mode"] in {"vector", "mixed"}:
      page_legend_entries = page_legends.get(page_number, [])
      active_legend_entries = page_legend_entries or best_legend_entries
      groups = match_legend_templates(
        page,
        active_legend_entries,
        args,
        page_legend_entries=page_legend_entries,
        technical_reference_scale=technical_reference_scale,
        feedback_priors=feedback_priors,
      )

      if groups:
        detection_mode = "legend_match_page" if page_legend_entries else "legend_match_shared"
      elif active_legend_entries:
        detection_mode = "legend_only_no_match"
      elif args.allow_vector_fallback:
        groups = collect_vector_groups(page, drawings, args)
        for group_index, group in enumerate(groups, start=1):
          sample_path = groups_dir / f"page_{page_number:03d}_group_{group_index:02d}.png"
          group["sample_image"].save(sample_path)
          group["sample_image"] = str(sample_path)
        assign_legend_labels(groups, page_legend_entries)
        detection_mode = "vector_repeat"
      else:
        detection_mode = "no_legend"

      preview_path = previews_dir / f"page_{page_number:03d}.png"
      make_page_preview(page, groups, preview_path, args.preview_dpi)
    else:
      page_legend_entries = page_legends.get(page_number, [])
      active_legend_entries = page_legend_entries or best_legend_entries
      groups = match_legend_templates(
        page,
        active_legend_entries,
        args,
        page_legend_entries=page_legend_entries,
        technical_reference_scale=technical_reference_scale,
        feedback_priors=feedback_priors,
      )
      detection_mode = "legend_match_page" if groups and page_legend_entries else "legend_match_shared" if groups else "raster_no_match"
      legend_entries = active_legend_entries
      preview_path = previews_dir / f"page_{page_number:03d}.png"
      make_page_preview(page, groups, preview_path, args.preview_dpi)
      page_legend_source = best_legend_page if (not page_legend_entries and best_legend_entries) else page_number if page_legend_entries else None
      report["pages"].append(
        {
          "page": page_number,
          "profile": profile,
          "vector_groups": groups,
          "legend_entries": legend_entries,
          "legend_source_page": page_legend_source,
          "detection_mode": detection_mode,
          "preview": str(preview_path) if preview_path else None,
        }
      )
      print(f"Page {page_number}: mode={profile['mode']} drawings={profile['drawings']} groups={len(groups)}")
      continue
    legend_entries = active_legend_entries if profile["mode"] in {"vector", "mixed"} else legend_entries
    page_legend_source = best_legend_page if (not page_legend_entries and best_legend_entries) else page_number if page_legend_entries else None

    report["pages"].append(
      {
        "page": page_number,
        "profile": profile,
        "vector_groups": groups,
        "legend_entries": legend_entries,
        "legend_source_page": page_legend_source,
        "detection_mode": detection_mode,
        "preview": str(preview_path) if preview_path else None,
      }
    )
    print(f"Page {page_number}: mode={profile['mode']} drawings={profile['drawings']} groups={len(groups)}")

  report_path = output_dir / "report.json"
  report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
  print(f"Report: {report_path}")


def main():
  args = parse_args()
  analyze_pdf(args)


if __name__ == "__main__":
  main()
