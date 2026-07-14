import fitz
import numpy as np
from PIL import Image, ImageDraw

from .pdf_utils import group_words_into_lines, normalize_text, render_clip, render_page, slugify
from .settings import IGNORED_LABEL_KEYWORDS, LEGEND_ANCHOR_WORDS


def should_ignore_label(text):
  normalized = normalize_text(text).upper()
  if normalized in {"", "LEGENDE", "LEGENDE ECLAIRAGES", "ECLAIRAGES"}:
    return True
  return any(keyword in normalized for keyword in IGNORED_LABEL_KEYWORDS)


def trim_image_to_content(image, padding=4):
  gray = np.asarray(image.convert("L"))
  ys, xs = np.where(gray < 245)
  if len(xs) == 0 or len(ys) == 0:
    return image
  x0 = max(int(xs.min()) - padding, 0)
  y0 = max(int(ys.min()) - padding, 0)
  x1 = min(int(xs.max()) + padding + 1, image.width)
  y1 = min(int(ys.max()) + padding + 1, image.height)
  return image.crop((x0, y0, x1, y1))


def binarize_symbol_image(image):
  rgb = np.asarray(image.convert("RGB"))
  gray = np.asarray(image.convert("L"))
  chroma = rgb.max(axis=2) - rgb.min(axis=2)
  foreground = (gray < 238) | (chroma >= 18)

  if not np.any(foreground):
    binary = np.full(gray.shape, 255, dtype=np.uint8)
    return Image.fromarray(binary, mode="L")

  binary = np.where(foreground, 0, 255).astype(np.uint8)
  return Image.fromarray(binary, mode="L")


def remove_cell_lines_from_binary(binary_image):
  array = np.asarray(binary_image.convert("L"))
  ink = array < 128
  if not np.any(ink):
    return binary_image

  cleaned = ink.copy()
  height, width = cleaned.shape

  row_ratio = cleaned.mean(axis=1)
  col_ratio = cleaned.mean(axis=0)
  line_rows = np.where(row_ratio >= 0.80)[0]
  line_cols = np.where(col_ratio >= 0.80)[0]

  # A filled symbol can naturally have many dense rows/columns. In that case,
  # do not erase them as if they were table borders.
  if len(line_rows) > height * 0.18:
    line_rows = []
  if len(line_cols) > width * 0.18:
    line_cols = []

  for row in line_rows:
    cleaned[max(row - 1, 0):min(row + 2, height), :] = False
  for col in line_cols:
    cleaned[:, max(col - 1, 0):min(col + 2, width)] = False

  ys, xs = np.where(cleaned)
  if len(xs) == 0 or len(ys) == 0:
    cleaned = ink
    ys, xs = np.where(cleaned)

  x0 = max(int(xs.min()) - 3, 0)
  y0 = max(int(ys.min()) - 3, 0)
  x1 = min(int(xs.max()) + 4, width)
  y1 = min(int(ys.max()) + 4, height)
  output = np.where(cleaned[y0:y1, x0:x1], 0, 255).astype(np.uint8)
  return Image.fromarray(output, mode="L")


def extract_dominant_color(image):
  rgb = np.asarray(image.convert("RGB"))
  non_white = np.any(rgb < 235, axis=2)
  if not np.any(non_white):
    return None
  pixels = rgb[non_white]
  chroma = pixels.max(axis=1) - pixels.min(axis=1)
  chromatic_pixels = pixels[chroma >= 24]
  if len(chromatic_pixels) == 0:
    chromatic_pixels = pixels
  mean = chromatic_pixels.mean(axis=0)
  return [int(round(value)) for value in mean.tolist()]


def symbol_metrics(image):
  gray = np.asarray(image.convert("L"))
  ink = gray < 245
  rows = np.any(ink, axis=1)
  cols = np.any(ink, axis=0)
  return {
    "ink_ratio": float(np.mean(ink)),
    "row_fill": float(np.count_nonzero(rows) / max(image.height, 1)),
    "col_fill": float(np.count_nonzero(cols) / max(image.width, 1)),
    "aspect_ratio": float(image.width / max(image.height, 1)),
  }


def is_valid_symbol(image):
  metrics = symbol_metrics(image)
  if image.width < 12 or image.height < 12:
    return False
  if image.width * image.height < 220:
    return False
  if metrics["ink_ratio"] < 0.01 or metrics["ink_ratio"] > 0.60:
    return False
  if metrics["aspect_ratio"] < 0.18 or metrics["aspect_ratio"] > 5.0:
    return False
  if metrics["row_fill"] > 0.96 and metrics["col_fill"] > 0.96:
    return False
  return True


def symbol_score(image):
  metrics = symbol_metrics(image)
  score = 0.0
  score += max(0.0, 0.18 - abs(metrics["ink_ratio"] - 0.12))
  score += max(0.0, 0.90 - abs(metrics["aspect_ratio"] - 1.0))
  score += max(0.0, 0.60 - abs(metrics["row_fill"] - 0.45))
  score += max(0.0, 0.60 - abs(metrics["col_fill"] - 0.35))
  return score


def _anchor_indices(lines):
  indices = []
  for index, line in enumerate(lines):
    normalized = normalize_text(line["text"]).upper()
    if any(anchor in normalized for anchor in LEGEND_ANCHOR_WORDS):
      indices.append(index)
  return indices


def _line_inside_anchor_band(line, anchor_bbox, page_width):
  x0, _, x1, _ = line["bbox"]
  anchor_x0, _, anchor_x1, _ = anchor_bbox
  margin = max(page_width * 0.18, 160)
  band_x0 = max(anchor_x0 - margin, 0)
  band_x1 = min(anchor_x1 + margin, page_width)
  return x1 >= band_x0 and x0 <= band_x1


def _collect_lines_below_anchor(lines, anchor_index, page_rect):
  anchor_line = lines[anchor_index]
  anchor_bbox = anchor_line["bbox"]
  page_width = float(page_rect.width)
  page_height = float(page_rect.height)
  max_y = min(anchor_bbox[3] + page_height * 0.78, page_height)
  selected = []
  previous_y = anchor_bbox[3]

  for line in lines[anchor_index + 1:]:
    _, y0, _, y1 = line["bbox"]
    if y0 <= anchor_bbox[3]:
      continue
    if y1 > max_y:
      break
    if not _line_inside_anchor_band(line, anchor_bbox, page_width):
      continue
    if selected and y0 - previous_y > 120:
      break
    selected.append(line)
    previous_y = y0
  return selected


def _candidate_lines(page):
  words = page.get_text("words")
  if not words:
    return None, []
  lines = group_words_into_lines(words)
  best_lines = []
  best_anchor = None
  for anchor_index in _anchor_indices(lines):
    selected = _collect_lines_below_anchor(lines, anchor_index, page.rect)
    selected = _filter_aligned_lines(selected)
    if len(selected) > len(best_lines):
      best_lines = selected
      best_anchor = lines[anchor_index]
  return best_anchor, best_lines


def _candidate_lines_from_words(words, page_rect):
  if not words:
    return None, []
  lines = group_words_into_lines(words)
  best_lines = []
  best_anchor = None
  for anchor_index in _anchor_indices(lines):
    selected = _collect_lines_below_anchor(lines, anchor_index, page_rect)
    selected = _filter_aligned_lines(selected)
    if len(selected) > len(best_lines):
      best_lines = selected
      best_anchor = lines[anchor_index]
  return best_anchor, best_lines


def _filter_aligned_lines(lines):
  if len(lines) < 4:
    return lines
  starts = sorted(line["bbox"][0] for line in lines)
  median_start = starts[len(starts) // 2]
  tolerance = max(40.0, (max(starts) - min(starts)) * 0.22)
  filtered = [line for line in lines if abs(line["bbox"][0] - median_start) <= tolerance]
  return filtered if len(filtered) >= max(3, len(lines) // 2) else lines


def _build_legend_region(anchor_line, lines, page_rect):
  if not anchor_line:
    return None
  relevant = [anchor_line] + list(lines)
  x0 = min(line["bbox"][0] for line in relevant)
  y0 = min(line["bbox"][1] for line in relevant)
  x1 = max(line["bbox"][2] for line in relevant)
  y1 = max(line["bbox"][3] for line in relevant)
  width_margin = max((x1 - x0) * 0.22, 36)
  height_margin = max((y1 - y0) * 0.04, 12)
  return fitz.Rect(
    max(x0 - width_margin, 0),
    max(y0 - height_margin, 0),
    min(x1 + width_margin, page_rect.width),
    min(y1 + height_margin, page_rect.height),
  )


def _detect_vertical_separator(page, anchor_line=None):
  page_width = float(page.rect.width)
  page_height = float(page.rect.height)
  min_span = max(page_height * 0.18, 260.0)
  candidates = []

  for drawing in page.get_drawings():
    for item in drawing.get("items", []):
      if item[0] != "l":
        continue
      p1, p2 = item[1], item[2]
      dx = abs(p2.x - p1.x)
      dy = abs(p2.y - p1.y)
      if dx > 1.5 or dy < min_span:
        continue
      x = (p1.x + p2.x) / 2.0
      if x < page_width * 0.25 or x > page_width * 0.97:
        continue
      y0 = min(p1.y, p2.y)
      y1 = max(p1.y, p2.y)
      candidates.append({"x": x, "y0": y0, "y1": y1, "span": y1 - y0})

  if not candidates:
    return None

  grouped = []
  for candidate in sorted(candidates, key=lambda item: item["x"]):
    if not grouped or abs(candidate["x"] - grouped[-1]["x"]) > 3.0:
      grouped.append(dict(candidate))
      continue
    current = grouped[-1]
    current["x"] = (current["x"] + candidate["x"]) / 2.0
    current["y0"] = min(current["y0"], candidate["y0"])
    current["y1"] = max(current["y1"], candidate["y1"])
    current["span"] = current["y1"] - current["y0"]

  if anchor_line is not None:
    anchor_x0 = anchor_line["bbox"][0]
    focused = [
      candidate
      for candidate in grouped
      if candidate["x"] < anchor_x0 and candidate["x"] > anchor_x0 - page_width * 0.22
    ]
    if focused:
      focused.sort(key=lambda item: (abs(anchor_x0 - item["x"]), -item["span"]))
      return focused[0]

  grouped.sort(key=lambda item: (-item["span"], item["x"]))
  return grouped[0]


def _infer_text_column(lines):
  if not lines:
    return None
  starts = sorted(line["bbox"][0] for line in lines)
  ends = sorted(line["bbox"][2] for line in lines)
  left = starts[len(starts) // 2]
  right = ends[len(ends) // 2]
  width = max(right - left, 40.0)
  return {"x0": left, "x1": right, "width": width}


def _dedupe_sorted(values, tolerance=1.5):
  grouped = []
  for value in sorted(values):
    if not grouped or abs(value - grouped[-1][-1]) > tolerance:
      grouped.append([value])
    else:
      grouped[-1].append(value)
  return [sum(group) / len(group) for group in grouped]


def _extract_table_horizontals(page, legend_region):
  if legend_region is None:
    return None

  rows = []
  for drawing in page.get_drawings():
    for item in drawing.get("items", []):
      if item[0] != "l":
        continue
      p1, p2 = item[1], item[2]
      dx = abs(p2.x - p1.x)
      dy = abs(p2.y - p1.y)
      if dx < max(legend_region.width * 0.55, 120) or dy > 1.5:
        continue
      minx, maxx = sorted((p1.x, p2.x))
      y = (p1.y + p2.y) / 2.0
      if maxx < legend_region.x0 or minx > legend_region.x1:
        continue
      if y < legend_region.y0 or y > legend_region.y1:
        continue
      rows.append((minx, maxx, y))

  if len(rows) < 4:
    return None

  ys = _dedupe_sorted([row[2] for row in rows], tolerance=1.8)
  if len(ys) < 4:
    return None

  minxs = sorted(row[0] for row in rows)
  maxxs = sorted(row[1] for row in rows)
  return {
    "ys": ys,
    "x0": minxs[len(minxs) // 2],
    "x1": maxxs[len(maxxs) // 2],
  }


def _build_row_specs(lines, page_rect, table_grid=None):
  ordered = sorted(lines, key=lambda line: (line["bbox"][1], line["bbox"][0]))
  if not ordered:
    return []

  if table_grid and len(table_grid.get("ys", [])) >= 2:
    coarse_specs = []
    ys = table_grid["ys"]
    for line in ordered:
      center = (line["bbox"][1] + line["bbox"][3]) / 2.0
      upper = max((y for y in ys if y <= center), default=max(line["bbox"][1] - 8.0, 0))
      lower = min((y for y in ys if y >= center), default=min(line["bbox"][3] + 8.0, page_rect.height))
      if lower - upper < 8:
        upper = max(line["bbox"][1] - 8.0, 0)
        lower = min(line["bbox"][3] + 8.0, page_rect.height)
      coarse_specs.append(
        {
          "line": line,
          "row_top": max(upper, 0),
          "row_bottom": min(lower, page_rect.height),
        }
      )

    grouped = {}
    for spec in coarse_specs:
      key = (round(spec["row_top"], 2), round(spec["row_bottom"], 2))
      grouped.setdefault(key, []).append(spec["line"])

    refined_specs = []
    for key, group_lines in grouped.items():
      row_top, row_bottom = key
      group_lines.sort(key=lambda line: (line["bbox"][1] + line["bbox"][3]) / 2.0)
      if len(group_lines) == 1:
        refined_specs.append({"line": group_lines[0], "row_top": row_top, "row_bottom": row_bottom})
        continue

      centers = [(line["bbox"][1] + line["bbox"][3]) / 2.0 for line in group_lines]
      boundaries = [row_top]
      for index in range(len(centers) - 1):
        boundaries.append((centers[index] + centers[index + 1]) / 2.0)
      boundaries.append(row_bottom)

      for index, line in enumerate(group_lines):
        refined_specs.append(
          {
            "line": line,
            "row_top": max(boundaries[index], 0),
            "row_bottom": min(boundaries[index + 1], page_rect.height),
          }
        )
    refined_specs.sort(key=lambda spec: (spec["row_top"], spec["line"]["bbox"][0]))
    return refined_specs

  centers = [(line["bbox"][1] + line["bbox"][3]) / 2.0 for line in ordered]
  specs = []
  for index, line in enumerate(ordered):
    x0, y0, x1, y1 = line["bbox"]
    line_height = max(y1 - y0, 12.0)
    top = centers[index - 1] if index > 0 else max(y0 - line_height * 0.8, 0)
    bottom = centers[index + 1] if index + 1 < len(ordered) else min(y1 + line_height * 0.8, page_rect.height)
    specs.append(
      {
        "line": line,
        "row_top": max(top, 0),
        "row_bottom": min(bottom, page_rect.height),
      }
    )
  return specs


def _side_column_bounds(side, text_column, legend_region, table_grid=None):
  if not text_column or legend_region is None:
    return None
  grid_x0 = table_grid["x0"] if table_grid else legend_region.x0
  grid_x1 = table_grid["x1"] if table_grid else legend_region.x1
  gap = min(max(text_column["width"] * 0.08, 6.0), 24.0)
  if side == "left":
    x0 = grid_x0 + 2.0
    x1 = text_column["x0"] - gap
  else:
    x0 = text_column["x1"] + gap
    x1 = grid_x1 - 2.0
  if x1 - x0 < 10:
    return None
  return (x0, x1)


def _extract_candidate_in_row(page, row_spec, side, text_column, legend_region, table_grid=None):
  bounds = _side_column_bounds(side, text_column, legend_region, table_grid=table_grid)
  if bounds is None:
    return None
  x0, x1 = bounds
  row_height = max(row_spec["row_bottom"] - row_spec["row_top"], 8.0)
  vertical_padding = min(max(row_height * 0.22, 4.0), 10.0)
  clip = fitz.Rect(
    x0,
    max(row_spec["row_top"] - vertical_padding, 0),
    x1,
    min(row_spec["row_bottom"] + vertical_padding, page.rect.height),
  )
  if clip.width < 8 or clip.height < 8:
    return None
  image = trim_image_to_content(render_clip(page, clip))
  if not is_valid_symbol(image):
    return None
  return {
    "side": side,
    "clip": clip,
    "image": image,
    "score": symbol_score(image),
  }


def _choose_preferred_side(page, row_specs, text_column, legend_region, table_grid=None):
  side_stats = {"left": {"count": 0, "score": 0.0}, "right": {"count": 0, "score": 0.0}}
  for row_spec in row_specs[:12]:
    for side in ("left", "right"):
      candidate = _extract_candidate_in_row(page, row_spec, side, text_column, legend_region, table_grid=table_grid)
      if candidate:
        side_stats[side]["count"] += 1
        side_stats[side]["score"] += candidate["score"]

  left_count = side_stats["left"]["count"]
  right_count = side_stats["right"]["count"]
  if left_count >= right_count + 2 and left_count >= 3:
    return "left"
  if right_count >= left_count + 2 and right_count >= 3:
    return "right"
  if left_count and not right_count:
    return "left"
  if right_count and not left_count:
    return "right"
  return "left" if side_stats["left"]["score"] >= side_stats["right"]["score"] else "right"


def extract_page_legend(page, page_number, output_dir):
  output_dir.mkdir(parents=True, exist_ok=True)
  anchor_line, lines = _candidate_lines(page)
  separator = _detect_vertical_separator(page, anchor_line=anchor_line)
  if separator and lines:
    filtered_lines = [line for line in lines if line["bbox"][0] >= separator["x"]]
    if filtered_lines:
      lines = filtered_lines
  legend_region = _build_legend_region(anchor_line, lines, page.rect)
  if legend_region is not None and separator is not None:
    legend_region = fitz.Rect(
      max(separator["x"] + 2.0, 0),
      legend_region.y0,
      legend_region.x1,
      legend_region.y1,
    )
  text_column = _infer_text_column(lines)
  table_grid = _extract_table_horizontals(page, legend_region)
  row_specs = _build_row_specs(lines, page.rect, table_grid=table_grid)
  preferred_side = _choose_preferred_side(page, row_specs, text_column, legend_region, table_grid=table_grid)
  entries = []

  for index, row_spec in enumerate(row_specs, start=1):
    line = row_spec["line"]
    text = line["text"].strip()
    if len(text) < 3 or not any(character.isalpha() for character in text):
      continue
    if should_ignore_label(text):
      continue

    symbol_payload = _extract_candidate_in_row(page, row_spec, preferred_side, text_column, legend_region, table_grid=table_grid)
    if symbol_payload is None:
      continue

    clip = symbol_payload["clip"]
    symbol_image = symbol_payload["image"]
    binary_image = remove_cell_lines_from_binary(binarize_symbol_image(symbol_image))
    entry_id = f"legend_{index:03d}"
    crop_name = f"{entry_id}_{slugify(text)[:40]}.png"
    binary_name = f"{entry_id}_{slugify(text)[:40]}_binary.png"
    crop_path = output_dir / crop_name
    binary_path = output_dir / binary_name
    symbol_image.save(crop_path)
    binary_image.save(binary_path)
    entries.append(
      {
        "id": entry_id,
        "label": text,
        "page": page_number,
        "line_bbox": [round(value, 2) for value in line["bbox"]],
        "symbol_bbox": [round(clip.x0, 2), round(clip.y0, 2), round(clip.x1, 2), round(clip.y1, 2)],
        "symbol_size": {"width": int(symbol_image.width), "height": int(symbol_image.height)},
        "dominant_color": extract_dominant_color(symbol_image),
        "symbol_side": symbol_payload["side"],
        "symbol_score": round(symbol_payload["score"], 4),
        "crop_path": crop_path,
        "binary_crop_path": binary_path,
        "binary_foreground_ratio": round(symbol_metrics(binary_image)["ink_ratio"], 4),
      }
    )

  preview_path = output_dir / f"page_{page_number:03d}_legend_preview.png"
  save_legend_preview(page, anchor_line, lines, entries, legend_region, separator, preview_path)
  return {
    "entries": entries,
    "preview_path": preview_path,
    "anchor_line": anchor_line,
    "legend_region": legend_region,
    "preferred_side": preferred_side,
    "separator_x": round(separator["x"], 2) if separator else None,
  }


def save_legend_preview(page, anchor_line, lines, entries, legend_region, separator, output_path):
  image = render_page(page, zoom=2.0)
  draw = ImageDraw.Draw(image)
  scale = 2.0
  if legend_region:
    draw.rectangle(
      (legend_region.x0 * scale, legend_region.y0 * scale, legend_region.x1 * scale, legend_region.y1 * scale),
      outline="#f59e0b",
      width=3,
    )
  if anchor_line:
    x0, y0, x1, y1 = anchor_line["bbox"]
    draw.rectangle((x0 * scale, y0 * scale, x1 * scale, y1 * scale), outline="#16a34a", width=3)
  if separator:
    x = separator["x"] * scale
    draw.line((x, separator["y0"] * scale, x, separator["y1"] * scale), fill="#a855f7", width=4)
  for line in lines:
    x0, y0, x1, y1 = line["bbox"]
    draw.rectangle((x0 * scale, y0 * scale, x1 * scale, y1 * scale), outline="#1d4ed8", width=2)
  for entry in entries:
    x0, y0, x1, y1 = entry["symbol_bbox"]
    draw.rectangle((x0 * scale, y0 * scale, x1 * scale, y1 * scale), outline="#dc2626", width=3)
  image.save(output_path)


def choose_best_legend_page(document, page_numbers, output_dir):
  best = None
  page_summaries = []
  quick_candidates = []

  for page_number in page_numbers:
    page = document[page_number - 1]
    words = page.get_text("words")
    anchor_line, lines = _candidate_lines_from_words(words, page.rect)
    quick_candidates.append(
      {
        "page": page_number,
        "quick_count": len(lines),
        "anchor_text": anchor_line["text"] if anchor_line else None,
      }
    )

  candidate_pages = [item for item in quick_candidates if item["quick_count"] > 0]
  candidate_pages.sort(key=lambda item: (-item["quick_count"], item["page"]))
  pages_to_process = [item["page"] for item in candidate_pages[:2]] if candidate_pages else list(page_numbers[:1])

  for page_number in pages_to_process:
    page_output_dir = output_dir / f"page_{page_number:03d}"
    payload = extract_page_legend(document[page_number - 1], page_number, page_output_dir)
    summary = {
      "page": page_number,
      "entry_count": len(payload["entries"]),
      "preview_path": payload["preview_path"],
      "anchor_text": payload["anchor_line"]["text"] if payload["anchor_line"] else None,
      "preferred_side": payload.get("preferred_side"),
      "separator_x": payload.get("separator_x"),
      "entries": payload["entries"],
    }
    page_summaries.append(summary)
    if best is None or summary["entry_count"] > best["entry_count"]:
      best = summary

  if best is None and quick_candidates:
    best = {
      "page": quick_candidates[0]["page"],
      "entry_count": 0,
      "preview_path": None,
      "anchor_text": quick_candidates[0].get("anchor_text"),
      "preferred_side": None,
      "separator_x": None,
      "entries": [],
    }
  return best, page_summaries
