import json
from pathlib import Path

import cv2
import fitz
import numpy as np
from PIL import Image, ImageDraw

from .legend_detector import _detect_vertical_separator, binarize_symbol_image, remove_cell_lines_from_binary
from .pdf_utils import parse_page_spec, render_page, resolve_repo_pdf_path
from .settings import REPO_ROOT


PAGE_RENDER_ZOOM = 1.75
MATCH_SCORE_THRESHOLD = 0.16
MIN_ADAPTIVE_MATCH_SCORE = 0.22
ADAPTIVE_SCORE_MARGIN = 0.045
ADAPTIVE_SCORE_RATIO = 0.86
BINARY_SEQUENCE_SIZE = 64
CONTACT_SHEET_COLUMNS = 8
CONTACT_SHEET_CELL_WIDTH = 150
CONTACT_SHEET_CELL_HEIGHT = 150

KERNEL_4_SMALL = np.array(
  [
    [0, 1, 0],
    [1, 1, 1],
    [0, 1, 0],
  ],
  dtype=np.uint8,
)
KERNEL_4_MEDIUM = cv2.getStructuringElement(cv2.MORPH_CROSS, (5, 5))
KERNEL_4_LARGE = cv2.getStructuringElement(cv2.MORPH_CROSS, (7, 7))


def _resolve_repo_file(raw_path):
  candidate = (REPO_ROOT / raw_path).resolve()
  if REPO_ROOT not in candidate.parents and candidate != REPO_ROOT:
    raise ValueError("Chemin hors depot.")
  if not candidate.exists():
    raise FileNotFoundError(f"Fichier introuvable: {raw_path}")
  return candidate


def _load_binary_template(binary_crop_path):
  template_image = Image.open(binary_crop_path).convert("L")
  template_image = remove_cell_lines_from_binary(template_image)
  template_array = np.array(template_image, dtype=np.uint8)
  return 255 - template_array


def _trim_mask(mask, padding=2):
  ys, xs = np.where(mask > 0)
  if len(xs) == 0 or len(ys) == 0:
    return mask
  x0 = max(int(xs.min()) - padding, 0)
  y0 = max(int(ys.min()) - padding, 0)
  x1 = min(int(xs.max()) + padding + 1, mask.shape[1])
  y1 = min(int(ys.max()) + padding + 1, mask.shape[0])
  return mask[y0:y1, x0:x1]


def _normalize_mask(mask, size=48):
  mask = _trim_mask((mask > 0).astype(np.uint8) * 255, padding=1)
  height, width = mask.shape[:2]
  if height <= 0 or width <= 0:
    return np.zeros((size, size), dtype=np.uint8)

  scale = min((size - 6) / max(width, 1), (size - 6) / max(height, 1))
  new_width = max(int(round(width * scale)), 1)
  new_height = max(int(round(height * scale)), 1)
  resized = cv2.resize(mask, (new_width, new_height), interpolation=cv2.INTER_NEAREST)
  output = np.zeros((size, size), dtype=np.uint8)
  x0 = (size - new_width) // 2
  y0 = (size - new_height) // 2
  output[y0:y0 + new_height, x0:x0 + new_width] = resized
  return output


def _clean_binary_mask(mask):
  mask = (mask > 0).astype(np.uint8) * 255
  if np.count_nonzero(mask) == 0:
    return mask
  cleaned = cv2.morphologyEx(mask, cv2.MORPH_OPEN, KERNEL_4_SMALL)
  cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, KERNEL_4_SMALL)
  if np.count_nonzero(cleaned) == 0:
    return mask
  return cleaned


def _shift_mask(mask, dx, dy):
  shifted = np.zeros_like(mask)
  height, width = mask.shape[:2]
  src_x0 = max(-dx, 0)
  src_y0 = max(-dy, 0)
  src_x1 = min(width - dx, width)
  src_y1 = min(height - dy, height)
  dst_x0 = max(dx, 0)
  dst_y0 = max(dy, 0)
  dst_x1 = dst_x0 + max(src_x1 - src_x0, 0)
  dst_y1 = dst_y0 + max(src_y1 - src_y0, 0)
  if src_x1 <= src_x0 or src_y1 <= src_y0:
    return shifted
  shifted[dst_y0:dst_y1, dst_x0:dst_x1] = mask[src_y0:src_y1, src_x0:src_x1]
  return shifted


def _binary_sequence_mask(mask, size=BINARY_SEQUENCE_SIZE):
  normalized = _normalize_mask(mask, size=size)
  return _clean_binary_mask(normalized) > 0


def _binary_sequence_similarity(component_array, template_array):
  component = _binary_sequence_mask(component_array)
  template = _binary_sequence_mask(template_array)
  if not np.any(component) or not np.any(template):
    return {"score": 0.0, "iou": 0.0, "dice": 0.0, "hamming": 0.0}

  best = {"score": 0.0, "iou": 0.0, "dice": 0.0, "hamming": 0.0}
  for dy in (-2, 0, 2):
    for dx in (-2, 0, 2):
      shifted = _shift_mask(component, dx, dy)
      intersection = np.logical_and(shifted, template).sum()
      union = np.logical_or(shifted, template).sum()
      component_count = shifted.sum()
      template_count = template.sum()
      iou = float(intersection / union) if union > 0 else 0.0
      dice = float((2.0 * intersection) / max(component_count + template_count, 1))
      hamming = float(np.mean(shifted == template))
      # Hamming is kept for diagnostics only: sparse symbols share a lot of background,
      # so Hamming can look high even when the foreground shape is wrong.
      score = (dice * 0.70) + (iou * 0.30)
      if score > best["score"]:
        best = {"score": score, "iou": iou, "dice": dice, "hamming": hamming}
  return best


def _zoning_signature(mask, grid_size=8):
  binary = _binary_sequence_mask(mask, size=BINARY_SEQUENCE_SIZE).astype(np.float32)
  cell_size = BINARY_SEQUENCE_SIZE // grid_size
  zones = binary.reshape(grid_size, cell_size, grid_size, cell_size).mean(axis=(1, 3)).flatten()
  total = float(zones.sum())
  if total > 1e-9:
    distribution = zones / total
  else:
    distribution = zones
  return zones, distribution


def _zoning_similarity(component_array, template_array):
  component_zones, component_distribution = _zoning_signature(component_array)
  template_zones, template_distribution = _zoning_signature(template_array)
  if template_zones.sum() <= 0 or component_zones.sum() <= 0:
    return 0.0
  distribution_distance = float(np.sum(np.abs(component_distribution - template_distribution)))
  distribution_score = max(0.0, 1.0 - (distribution_distance / 2.0))
  template_density = float(template_zones.mean())
  component_density = float(component_zones.mean())
  density_score = max(0.0, 1.0 - min(abs(component_density - template_density) / max(template_density, 0.04), 1.0))
  return float((distribution_score * 0.75) + (density_score * 0.25))


def _minimum_binary_score(profile, template_shape):
  shape_class = template_shape["shape_class"]
  if shape_class in {"circle", "square", "rectangle", "diamond", "triangle"}:
    return 0.24
  if shape_class == "line":
    return 0.16
  if profile["family"] == "sparse":
    return 0.18
  if profile["family"] == "linear":
    return 0.16
  return 0.20


def _adaptive_binary_threshold(candidate_pool, profile, template_shape):
  if not candidate_pool:
    return _minimum_binary_score(profile, template_shape)
  best_binary = max(item.get("binary_score", 0.0) for item in candidate_pool)
  floor = _minimum_binary_score(profile, template_shape)
  return max(floor, best_binary * 0.86, best_binary - 0.055)


def _minimum_zoning_score(profile, template_shape):
  if template_shape["shape_class"] == "complex":
    return 0.58
  if profile["family"] in {"sparse", "linear"}:
    return 0.46
  return 0.52


def _adaptive_zoning_threshold(candidate_pool, profile, template_shape):
  if not candidate_pool:
    return _minimum_zoning_score(profile, template_shape)
  best_zoning = max(item.get("zoning_score", 0.0) for item in candidate_pool)
  floor = _minimum_zoning_score(profile, template_shape)
  return max(floor, best_zoning * 0.86, best_zoning - 0.08)



def _projection_score(a, b, axis):
  pa = (a > 0).sum(axis=axis).astype(np.float32)
  pb = (b > 0).sum(axis=axis).astype(np.float32)
  if pa.max() <= 0 or pb.max() <= 0:
    return 0.0
  pa /= pa.max()
  pb /= pb.max()
  return float(1.0 - np.mean(np.abs(pa - pb)))


def _smooth_1d(values, window=7):
  if len(values) < window:
    return values
  kernel = np.ones(window, dtype=np.float64) / window
  padded = np.r_[values[-window:], values, values[:window]]
  smoothed = np.convolve(padded, kernel, mode="same")
  return smoothed[window:-window]


def _largest_contour(mask):
  contours, _ = cv2.findContours((mask > 0).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
  if not contours:
    return None
  return max(contours, key=cv2.contourArea)


def _aggregate_contour(mask):
  contours, _ = cv2.findContours((mask > 0).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
  if not contours:
    return None
  if len(contours) == 1:
    return contours[0]
  points = np.vstack(contours)
  if len(points) < 3:
    return max(contours, key=cv2.contourArea)
  return cv2.convexHull(points)


def _radial_signature(mask, samples=128):
  normalized = _normalize_mask(mask, size=96)
  contour = _aggregate_contour(normalized)
  if contour is None or len(contour) < 12:
    return None

  points = contour[:, 0, :].astype(np.float64)
  moments = cv2.moments(contour)
  if abs(moments["m00"]) > 1e-9:
    cx = moments["m10"] / moments["m00"]
    cy = moments["m01"] / moments["m00"]
  else:
    cx = float(np.mean(points[:, 0]))
    cy = float(np.mean(points[:, 1]))

  signature = np.sqrt((points[:, 0] - cx) ** 2 + (points[:, 1] - cy) ** 2)
  if len(signature) < 4 or float(np.std(signature)) < 1e-9:
    return None

  signature = np.roll(signature, -int(np.argmin(signature)))
  signature = _smooth_1d(signature, window=7)
  x_old = np.linspace(0.0, 1.0, num=len(signature), endpoint=False)
  x_new = np.linspace(0.0, 1.0, num=samples, endpoint=False)
  signature = np.interp(x_new, x_old, signature)
  signature = (signature - np.mean(signature)) / (np.std(signature) + 1e-9)
  return signature


def _radial_signature_score(component_array, template_array):
  component_signature = _radial_signature(component_array)
  template_signature = _radial_signature(template_array)
  if component_signature is None or template_signature is None:
    return 0.0
  direct = np.linalg.norm(component_signature - template_signature) / np.sqrt(len(template_signature))
  reversed_distance = np.linalg.norm(component_signature[::-1] - template_signature) / np.sqrt(len(template_signature))
  distance = min(float(direct), float(reversed_distance))
  return float(1.0 / (1.0 + distance))


def _match_shapes_score(component_array, template_array):
  component = _normalize_mask(component_array, size=96)
  template = _normalize_mask(template_array, size=96)
  component_contour = _aggregate_contour(component)
  template_contour = _aggregate_contour(template)
  if component_contour is None or template_contour is None:
    return 0.0
  if len(component_contour) < 3 or len(template_contour) < 3:
    return 0.0
  distance = cv2.matchShapes(template_contour, component_contour, cv2.CONTOURS_MATCH_I1, 0.0)
  if not np.isfinite(distance):
    return 0.0
  return float(1.0 / (1.0 + max(distance, 0.0)))


def _shape_features(mask):
  normalized = _normalize_mask(mask, size=96)
  contour = _aggregate_contour(normalized)
  if contour is None or len(contour) < 3:
    return {
      "shape_class": "unknown",
      "vertices": 0,
      "circularity": 0.0,
      "aspect_ratio": 0.0,
      "extent": 0.0,
      "solidity": 0.0,
    }

  area = float(cv2.contourArea(contour))
  perimeter = float(cv2.arcLength(contour, True))
  if area <= 1.0 or perimeter <= 1.0:
    return {
      "shape_class": "unknown",
      "vertices": 0,
      "circularity": 0.0,
      "aspect_ratio": 0.0,
      "extent": 0.0,
      "solidity": 0.0,
    }

  _, _, width, height = cv2.boundingRect(contour)
  aspect_ratio = max(width, height) / max(min(width, height), 1)
  extent = area / max(width * height, 1)
  circularity = (4.0 * np.pi * area) / max(perimeter * perimeter, 1e-9)
  hull = cv2.convexHull(contour)
  hull_area = float(cv2.contourArea(hull))
  solidity = area / max(hull_area, 1e-9)
  rect = cv2.minAreaRect(contour)
  rect_w, rect_h = rect[1]
  rect_aspect_ratio = max(rect_w, rect_h) / max(min(rect_w, rect_h), 1.0)
  approx = cv2.approxPolyDP(contour, 0.035 * perimeter, True)
  vertices = len(approx)

  if aspect_ratio >= 4.0:
    shape_class = "line"
  elif circularity >= 0.82 and vertices >= 6:
    shape_class = "circle"
  elif vertices == 3:
    shape_class = "triangle"
  elif 4 <= vertices <= 6:
    if rect_aspect_ratio >= 1.35:
      shape_class = "rectangle"
    elif extent <= 0.66:
      shape_class = "diamond"
    else:
      shape_class = "square"
  elif circularity >= 0.74 and solidity >= 0.88:
    shape_class = "circle"
  else:
    shape_class = "complex"

  return {
    "shape_class": shape_class,
    "vertices": int(vertices),
    "circularity": round(float(circularity), 4),
    "aspect_ratio": round(float(aspect_ratio), 4),
    "rect_aspect_ratio": round(float(rect_aspect_ratio), 4),
    "extent": round(float(extent), 4),
    "solidity": round(float(solidity), 4),
  }


def _shape_similarity_from_template(component_array, template):
  component = _shape_features(component_array)
  template_class = template["shape_class"]
  component_class = component["shape_class"]
  strict_classes = {"circle", "square", "rectangle", "diamond", "triangle"}

  if template_class in strict_classes:
    if component_class != template_class:
      return 0.0, template, component
    circularity_delta = abs(template["circularity"] - component["circularity"])
    aspect_delta = abs(template["rect_aspect_ratio"] - component["rect_aspect_ratio"])
    extent_delta = abs(template["extent"] - component["extent"])
    score = 1.0 - min((circularity_delta * 0.55) + (aspect_delta * 0.20) + (extent_delta * 0.25), 1.0)
    return float(score), template, component

  if template_class == "line":
    if component_class != "line":
      return 0.0, template, component
    aspect_delta = abs(template["aspect_ratio"] - component["aspect_ratio"]) / max(template["aspect_ratio"], 1.0)
    return float(max(0.0, 1.0 - aspect_delta)), template, component

  return 0.65, template, component


def _shape_similarity(component_array, template_array):
  return _shape_similarity_from_template(component_array, _shape_features(template_array))


def _mask_similarity(component_array, template_array, radial_signature=None, shape_score=None, binary_score=None, hu_score=None, zoning_score=None):
  component = _normalize_mask(component_array)
  template = _normalize_mask(template_array)
  component_mask = component > 0
  template_mask = template > 0
  union = np.logical_or(component_mask, template_mask).sum()
  if union <= 0:
    return 0.0
  intersection = np.logical_and(component_mask, template_mask).sum()
  iou = float(intersection / union)
  horizontal = _projection_score(component, template, axis=0)
  vertical = _projection_score(component, template, axis=1)
  if radial_signature is None:
    radial_signature = _radial_signature_score(component, template)
  if shape_score is None:
    shape_score, _, _ = _shape_similarity(component, template)
  if binary_score is None:
    binary_score = _binary_sequence_similarity(component, template)["score"]
  if hu_score is None:
    hu_score = _match_shapes_score(component, template)
  if zoning_score is None:
    zoning_score = _zoning_similarity(component, template)
  if shape_score <= 0:
    return 0.0
  if radial_signature <= 0:
    return (binary_score * 0.36) + (zoning_score * 0.30) + (horizontal * 0.04) + (vertical * 0.04) + (shape_score * 0.14) + (hu_score * 0.12)
  return (binary_score * 0.32) + (zoning_score * 0.28) + (horizontal * 0.03) + (vertical * 0.03) + (radial_signature * 0.12) + (shape_score * 0.12) + (hu_score * 0.10)


def _template_profile(template_array):
  template = _trim_mask(template_array, padding=1)
  height, width = template.shape[:2]
  area = max(width * height, 1)
  ink = int(np.count_nonzero(template))
  fill_ratio = ink / area
  aspect_ratio = max(width, height) / max(min(width, height), 1)
  if aspect_ratio >= 4.0:
    family = "linear"
  elif fill_ratio >= 0.22 and aspect_ratio <= 2.2:
    family = "solid"
  elif fill_ratio <= 0.09:
    family = "sparse"
  else:
    family = "mixed"
  return {
    "width": int(width),
    "height": int(height),
    "ink": ink,
    "fill_ratio": fill_ratio,
    "aspect_ratio": aspect_ratio,
    "family": family,
  }


def _adaptive_threshold(best_score, profile):
  family = profile["family"]
  minimum_by_family = {
    "solid": 0.40,
    "mixed": 0.32,
    "sparse": 0.30,
    "linear": 0.28,
  }
  ratio_by_family = {
    "solid": 0.90,
    "mixed": 0.88,
    "sparse": 0.90,
    "linear": 0.86,
  }
  margin_by_family = {
    "solid": 0.035,
    "mixed": 0.040,
    "sparse": 0.035,
    "linear": 0.050,
  }
  return max(
    minimum_by_family.get(family, MIN_ADAPTIVE_MATCH_SCORE),
    best_score * ratio_by_family.get(family, ADAPTIVE_SCORE_RATIO),
    best_score - margin_by_family.get(family, ADAPTIVE_SCORE_MARGIN),
  )


def _binarize_page_image(image, target_rgb=None):
  rgb = np.asarray(image.convert("RGB"))
  if target_rgb and max(target_rgb) - min(target_rgb) >= 18:
    target = np.array(target_rgb, dtype=np.int16)
    distance = np.linalg.norm(rgb.astype(np.int16) - target, axis=2)
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    dominant_channel = int(np.argmax(target))
    target_chroma = int(target.max() - target.min())
    channel = rgb[:, :, dominant_channel].astype(np.int16)
    other_channels = np.delete(rgb.astype(np.int16), dominant_channel, axis=2)
    other_max = other_channels.max(axis=2)
    dominance_gap = max(12, int(target_chroma * 0.28))
    hue_mask = (channel >= 70) & ((channel - other_max) >= dominance_gap)
    mask = ((distance <= 130) & (chroma >= 10)) | hue_mask
    mask = mask.astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, KERNEL_4_SMALL)
    mask = cv2.dilate(mask, KERNEL_4_SMALL, iterations=1)
    return mask

  binary = binarize_symbol_image(image)
  return 255 - np.array(binary, dtype=np.uint8)


def _nms(boxes, iou_threshold=0.22):
  if not boxes:
    return []

  boxes = sorted(boxes, key=lambda item: item["score"], reverse=True)[:2000]
  kept = []
  for candidate in boxes:
    keep = True
    for existing in kept:
      if _iou(candidate["bbox"], existing["bbox"]) > iou_threshold:
        keep = False
        break
    if keep:
      kept.append(candidate)
  return kept


def _iou(a, b):
  ax0, ay0, ax1, ay1 = a
  bx0, by0, bx1, by1 = b
  inter_x0 = max(ax0, bx0)
  inter_y0 = max(ay0, by0)
  inter_x1 = min(ax1, bx1)
  inter_y1 = min(ay1, by1)
  inter_w = max(inter_x1 - inter_x0, 0)
  inter_h = max(inter_y1 - inter_y0, 0)
  inter_area = inter_w * inter_h
  if inter_area <= 0:
    return 0.0
  area_a = max(ax1 - ax0, 0) * max(ay1 - ay0, 0)
  area_b = max(bx1 - bx0, 0) * max(by1 - by0, 0)
  union = area_a + area_b - inter_area
  return inter_area / union if union > 0 else 0.0


def _search_clip_for_page(page):
  separator = _detect_vertical_separator(page)
  if separator:
    return fitz.Rect(0, 0, max(separator["x"] - 4.0, 1.0), page.rect.height), separator
  return fitz.Rect(0, 0, page.rect.width, page.rect.height), None


def _grouping_kernel(mask, target_rgb=None):
  ink_ratio = float(np.mean(mask > 0))
  if target_rgb and max(target_rgb) - min(target_rgb) >= 18:
    return KERNEL_4_MEDIUM, 1
  if ink_ratio < 0.025:
    return KERNEL_4_SMALL, 1
  return KERNEL_4_SMALL, 1


def _component_candidates(search_array, template_array, target_rgb=None):
  template_h, template_w = template_array.shape[:2]
  profile = _template_profile(template_array)
  template_shape = _shape_features(template_array)
  minimum_binary_score = _minimum_binary_score(profile, template_shape)
  template_area = max(int(np.count_nonzero(template_array)), 1)
  search_mask = (search_array > 0).astype(np.uint8) * 255
  kernel, iterations = _grouping_kernel(search_mask, target_rgb=target_rgb)
  grouped_mask = cv2.dilate(search_mask, kernel, iterations=iterations)
  grouped_mask = cv2.morphologyEx(grouped_mask, cv2.MORPH_CLOSE, kernel)
  num_labels, _, stats, _ = cv2.connectedComponentsWithStats((grouped_mask > 0).astype(np.uint8), connectivity=4)
  candidate_pool = []
  debug_candidates = []
  max_side = max(template_h, template_w, 1)

  for label in range(1, num_labels):
    x, y, w, h, area = stats[label]
    if area < 6:
      continue
    if w < 3 or h < 3:
      continue
    if w > max(max_side * 3.0, 180) or h > max(max_side * 3.0, 180):
      continue

    pad = 3
    x0 = max(int(x) - pad, 0)
    y0 = max(int(y) - pad, 0)
    x1 = min(int(x + w) + pad, search_array.shape[1])
    y1 = min(int(y + h) + pad, search_array.shape[0])
    component = _trim_mask(search_array[y0:y1, x0:x1], padding=1)
    ink_area = int(np.count_nonzero(component))
    if ink_area < 5:
      continue

    area_ratio = ink_area / template_area
    template_bbox_area = max(template_h * template_w, 1)
    linear_template = (max(template_h, template_w) / max(min(template_h, template_w), 1)) >= 4.0
    max_area_ratio = 80.0 if linear_template else 12.0
    if area_ratio > max_area_ratio:
      continue

    binary_metrics = None
    shape_score, _, component_shape = _shape_similarity_from_template(component, template_shape)
    if shape_score <= 0:
      binary_metrics = _binary_sequence_similarity(component, template_array)
      if binary_metrics["score"] >= 0.45:
        shape_score = 0.35
      else:
        debug_candidates.append(
          {
            "bbox": [x0, y0, x1, y1],
            "score": 0.0,
            "binary_score": round(binary_metrics["score"], 4),
            "binary_iou": round(binary_metrics["iou"], 4),
            "binary_dice": round(binary_metrics["dice"], 4),
            "binary_hamming": round(binary_metrics["hamming"], 4),
            "signature_score": 0.0,
            "shape_score": 0.0,
            "template_shape": template_shape["shape_class"],
            "candidate_shape": component_shape["shape_class"],
            "rejected_by": "shape_class",
            "ink_area": ink_area,
            "area_ratio": round(area_ratio, 4),
            "size": [int(x1 - x0), int(y1 - y0)],
          }
        )
        continue

    if binary_metrics is None:
      binary_metrics = _binary_sequence_similarity(component, template_array)

    if binary_metrics["score"] < minimum_binary_score:
      debug_candidates.append(
        {
          "bbox": [x0, y0, x1, y1],
          "score": 0.0,
          "binary_score": round(binary_metrics["score"], 4),
          "binary_iou": round(binary_metrics["iou"], 4),
          "binary_dice": round(binary_metrics["dice"], 4),
          "binary_hamming": round(binary_metrics["hamming"], 4),
          "signature_score": 0.0,
          "shape_score": round(shape_score, 4),
          "template_shape": template_shape["shape_class"],
          "candidate_shape": component_shape["shape_class"],
          "rejected_by": "binary_score",
          "min_binary_score": minimum_binary_score,
          "ink_area": ink_area,
          "area_ratio": round(area_ratio, 4),
          "size": [int(x1 - x0), int(y1 - y0)],
        }
      )
      continue

    zoning_score = _zoning_similarity(component, template_array)
    signature_score = _radial_signature_score(component, template_array)
    hu_score = _match_shapes_score(component, template_array)
    score = _mask_similarity(
      component,
      template_array,
      radial_signature=signature_score,
      shape_score=shape_score,
      binary_score=binary_metrics["score"],
      hu_score=hu_score,
      zoning_score=zoning_score,
    )
    candidate = {
      "bbox": [x0, y0, x1, y1],
      "score": round(score, 4),
      "binary_score": round(binary_metrics["score"], 4),
      "binary_iou": round(binary_metrics["iou"], 4),
      "binary_dice": round(binary_metrics["dice"], 4),
      "binary_hamming": round(binary_metrics["hamming"], 4),
      "zoning_score": round(zoning_score, 4),
      "signature_score": round(signature_score, 4),
      "hu_score": round(hu_score, 4),
      "shape_score": round(shape_score, 4),
      "template_shape": template_shape["shape_class"],
      "candidate_shape": component_shape["shape_class"],
      "ink_area": ink_area,
      "area_ratio": round(area_ratio, 4),
      "size": [int(x1 - x0), int(y1 - y0)],
    }
    debug_candidates.append(candidate)
    if score < MATCH_SCORE_THRESHOLD:
      continue
    candidate_pool.append(candidate)

  debug_candidates.sort(key=lambda item: item["score"], reverse=True)
  if not candidate_pool:
    return [], debug_candidates[:20]

  best_score = max(item["score"] for item in candidate_pool)
  adaptive_threshold = _adaptive_threshold(best_score, profile)
  binary_threshold = _adaptive_binary_threshold(candidate_pool, profile, template_shape)
  zoning_threshold = _adaptive_zoning_threshold(candidate_pool, profile, template_shape)
  candidates = [
    {
      **item,
      "threshold": round(adaptive_threshold, 4),
      "binary_threshold": round(binary_threshold, 4),
      "zoning_threshold": round(zoning_threshold, 4),
      "family": profile["family"],
      "confidence": "haute" if item["binary_score"] >= max(0.36, binary_threshold) else "moyenne",
    }
    for item in candidate_pool
    if item["score"] >= adaptive_threshold and item["binary_score"] >= binary_threshold and item["zoning_score"] >= zoning_threshold
  ]
  if not candidates:
    fallback_threshold = max(_minimum_binary_score(profile, template_shape), binary_threshold - 0.05)
    fallback_zoning_threshold = max(_minimum_zoning_score(profile, template_shape), zoning_threshold - 0.08)
    candidates = [
      {
        **item,
        "threshold": round(adaptive_threshold, 4),
        "binary_threshold": round(fallback_threshold, 4),
        "zoning_threshold": round(fallback_zoning_threshold, 4),
        "family": profile["family"],
        "confidence": "faible",
        "warning": "fallback_binary_adaptatif",
      }
      for item in candidate_pool
      if item["binary_score"] >= fallback_threshold and item["zoning_score"] >= fallback_zoning_threshold
    ][:30]
  return candidates, debug_candidates[:20]


def _template_match_candidates(search_array, template_array):
  source_template = _trim_mask(template_array, padding=1)
  template_h, template_w = source_template.shape[:2]
  profile = _template_profile(template_array)
  template_shape = _shape_features(source_template)
  minimum_binary_score = _minimum_binary_score(profile, template_shape)
  linear_template = profile["family"] == "linear"
  scales = [0.08, 0.12, 0.16, 0.20, 0.25, 0.30, 0.40, 0.50, 0.70, 1.00] if linear_template else [
    0.18,
    0.22,
    0.26,
    0.30,
    0.34,
    0.40,
    0.48,
    0.56,
    0.66,
  ]
  threshold = 0.65 if linear_template else 0.56
  candidates = []

  for scale in scales:
    width = max(int(round(template_w * scale)), 3)
    height = max(int(round(template_h * scale)), 3)
    if width >= search_array.shape[1] or height >= search_array.shape[0]:
      continue
    template = cv2.resize(source_template, (width, height), interpolation=cv2.INTER_NEAREST)
    if np.count_nonzero(template) < 2:
      continue
    response = cv2.matchTemplate(search_array, template, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(response >= threshold)
    for x, y in zip(xs, ys):
      component = search_array[int(y):int(y + height), int(x):int(x + width)]
      shape_score, _, component_shape = _shape_similarity_from_template(component, template_shape)
      if shape_score <= 0:
        continue
      binary_metrics = _binary_sequence_similarity(component, source_template)
      if binary_metrics["score"] < minimum_binary_score:
        continue
      zoning_score = _zoning_similarity(component, source_template)
      if zoning_score < _minimum_zoning_score(profile, template_shape):
        continue
      signature_score = _radial_signature_score(component, source_template)
      hu_score = _match_shapes_score(component, source_template)
      response_score = float(response[y, x])
      combined_score = (binary_metrics["score"] * 0.34) + (zoning_score * 0.24) + (response_score * 0.16) + (signature_score * 0.08) + (shape_score * 0.08) + (hu_score * 0.10)
      candidates.append(
        {
          "bbox": [int(x), int(y), int(x + width), int(y + height)],
          "score": round(combined_score, 4),
          "template_score": round(response_score, 4),
          "binary_score": round(binary_metrics["score"], 4),
          "binary_iou": round(binary_metrics["iou"], 4),
          "binary_dice": round(binary_metrics["dice"], 4),
          "binary_hamming": round(binary_metrics["hamming"], 4),
          "zoning_score": round(zoning_score, 4),
          "signature_score": round(signature_score, 4),
          "hu_score": round(hu_score, 4),
          "shape_score": round(shape_score, 4),
          "template_shape": template_shape["shape_class"],
          "candidate_shape": component_shape["shape_class"],
          "method": "template",
          "family": profile["family"],
          "threshold": threshold,
          "size": [int(width), int(height)],
        }
      )

  candidates.sort(key=lambda item: item["score"], reverse=True)
  candidates = candidates[:2000]
  return _nms(candidates, iou_threshold=0.30), candidates[:20]


def _match_on_page(page, template_array, target_rgb=None):
  clip_rect, separator = _search_clip_for_page(page)
  clip_pixmap = page.get_pixmap(matrix=fitz.Matrix(PAGE_RENDER_ZOOM, PAGE_RENDER_ZOOM), clip=clip_rect, alpha=False)
  clip_image = Image.frombytes("RGB", [clip_pixmap.width, clip_pixmap.height], clip_pixmap.samples)
  search_array = _binarize_page_image(clip_image, target_rgb=target_rgb)
  candidates, debug_candidates = _component_candidates(search_array, template_array, target_rgb=target_rgb)
  matches = _nms(candidates)
  if not matches:
    matches, template_debug = _template_match_candidates(search_array, template_array)
    debug_candidates = template_debug or debug_candidates
  return matches, clip_rect, separator, debug_candidates, clip_image


def _save_page_preview(page, page_number, matches, output_path, clip_rect):
  full_image = render_page(page, zoom=PAGE_RENDER_ZOOM)
  draw = ImageDraw.Draw(full_image)
  offset_x = clip_rect.x0 * PAGE_RENDER_ZOOM
  offset_y = clip_rect.y0 * PAGE_RENDER_ZOOM
  for match in matches:
    x0, y0, x1, y1 = match["bbox"]
    draw.rectangle((x0 + offset_x, y0 + offset_y, x1 + offset_x, y1 + offset_y), outline="#ef4444", width=3)
  full_image.save(output_path)


def _save_counted_items_sheet(clip_image, page_number, matches, output_path):
  columns = CONTACT_SHEET_COLUMNS
  cell_width = CONTACT_SHEET_CELL_WIDTH
  cell_height = CONTACT_SHEET_CELL_HEIGHT
  header_height = 42
  rows = max((len(matches) + columns - 1) // columns, 1)
  sheet_width = columns * cell_width
  sheet_height = header_height + rows * cell_height
  sheet = Image.new("RGB", (sheet_width, sheet_height), "#f8fafc")
  draw = ImageDraw.Draw(sheet)
  draw.rectangle((0, 0, sheet_width, header_height), fill="#0f172a")
  draw.text((12, 13), f"Page {page_number} - {len(matches)} elements comptes", fill="#ffffff")

  for index, match in enumerate(matches, start=1):
    x0, y0, x1, y1 = [int(value) for value in match["bbox"]]
    pad = 10
    crop_box = (
      max(x0 - pad, 0),
      max(y0 - pad, 0),
      min(x1 + pad, clip_image.width),
      min(y1 + pad, clip_image.height),
    )
    crop = clip_image.crop(crop_box)
    crop.thumbnail((cell_width - 26, cell_height - 42), Image.Resampling.LANCZOS)

    col = (index - 1) % columns
    row = (index - 1) // columns
    cell_x = col * cell_width
    cell_y = header_height + row * cell_height
    draw.rectangle((cell_x, cell_y, cell_x + cell_width - 1, cell_y + cell_height - 1), outline="#cbd5e1")
    draw.text((cell_x + 8, cell_y + 8), f"#{index} score {match.get('score', 'n/a')}", fill="#0f172a")
    draw.text((cell_x + 8, cell_y + 24), f"bin {match.get('binary_score', 'n/a')}", fill="#475569")
    draw.text((cell_x + 8, cell_y + 40), f"zone {match.get('zoning_score', 'n/a')}", fill="#475569")
    draw.text((cell_x + 8, cell_y + 56), f"sig {match.get('signature_score', 'n/a')}", fill="#475569")
    draw.text((cell_x + 8, cell_y + 72), f"hu {match.get('hu_score', 'n/a')}", fill="#475569")
    draw.text((cell_x + 8, cell_y + 88), f"{match.get('candidate_shape', '?')} {match.get('confidence', '')}", fill="#475569")
    image_x = cell_x + (cell_width - crop.width) // 2
    image_y = cell_y + 104 + max((cell_height - 112 - crop.height) // 2, 0)
    sheet.paste(crop, (image_x, image_y))

  output_path.parent.mkdir(parents=True, exist_ok=True)
  sheet.save(output_path)


def match_legend_object(pdf_relative_path, object_payload, page_spec=None):
  pdf_path = resolve_repo_pdf_path(pdf_relative_path)
  object_id = object_payload.get("id")
  binary_crop_path = _resolve_repo_file(object_payload.get("binary_crop_path"))
  label = object_payload.get("label") or object_id

  run_dir = binary_crop_path.parent.parent
  output_dir = run_dir / "plan_matches" / object_id
  output_dir.mkdir(parents=True, exist_ok=True)

  template_array = _load_binary_template(binary_crop_path)
  target_rgb = object_payload.get("dominant_color")
  page_results = []
  total_matches = 0

  with fitz.open(pdf_path) as document:
    if page_spec:
      page_numbers = parse_page_spec(page_spec, document.page_count)
    else:
      raw_pages = object_payload.get("selected_pages") or [object_payload.get("page")]
      page_numbers = [int(page) for page in raw_pages if page]
      if not page_numbers:
        page_numbers = [int(object_payload.get("page") or 1)]
    for page_number in page_numbers:
      page = document[page_number - 1]
      matches, clip_rect, separator, debug_candidates, clip_image = _match_on_page(page, template_array, target_rgb=target_rgb)
      total_matches += len(matches)
      preview_path = output_dir / f"page_{page_number:03d}_matches.png"
      counted_items_path = output_dir / f"page_{page_number:03d}_counted_items.png"
      _save_page_preview(page, page_number, matches, preview_path, clip_rect)
      _save_counted_items_sheet(clip_image, page_number, matches, counted_items_path)
      page_results.append(
        {
          "page": page_number,
          "match_count": len(matches),
          "preview_path": preview_path.relative_to(REPO_ROOT).as_posix(),
          "counted_items_path": counted_items_path.relative_to(REPO_ROOT).as_posix(),
          "separator_x": round(separator["x"], 2) if separator else None,
          "search_clip": [round(clip_rect.x0, 2), round(clip_rect.y0, 2), round(clip_rect.x1, 2), round(clip_rect.y1, 2)],
          "matches": matches[:120],
          "debug_top_candidates": debug_candidates,
        }
      )

  result = {
    "object_id": object_id,
    "label": label,
    "pdf_path": pdf_relative_path,
    "binary_crop_path": object_payload.get("binary_crop_path"),
    "page_count": len(page_results),
    "total_matches": total_matches,
    "pages": page_results,
  }
  result_path = output_dir / "matches.json"
  result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
  return result
