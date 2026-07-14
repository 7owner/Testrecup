import json

import cv2
import fitz
import numpy as np
from PIL import Image

from .pdf_utils import parse_page_spec, resolve_repo_pdf_path
from .settings import REPO_ROOT
from .plan_matcher import (
  PAGE_RENDER_ZOOM,
  KERNEL_4_SMALL,
  _binarize_page_image,
  _binary_sequence_mask,
  _binary_sequence_similarity,
  _grouping_kernel,
  _load_binary_template,
  _match_shapes_score,
  _nms,
  _radial_signature_score,
  _resolve_repo_file,
  _save_counted_items_sheet,
  _save_page_preview,
  _search_clip_for_page,
  _shape_features,
  _shape_similarity_from_template,
  _template_profile,
  _trim_mask,
  _zoning_signature,
  _zoning_similarity,
)


DESCRIPTOR_BINARY_SIZE = 32
DESCRIPTOR_GRID_SIZE = 8
MAX_KMEANS_CANDIDATES = 2500
STRICT_DISTANCE_RATIO = 1.28
STRICT_DISTANCE_MARGIN = 0.18

SHAPE_CLASSES = ["circle", "square", "rectangle", "diamond", "triangle", "line", "complex", "unknown"]


def _safe_float(value, default=0.0):
  try:
    value = float(value)
  except (TypeError, ValueError):
    return default
  if not np.isfinite(value):
    return default
  return value


def _shape_one_hot(shape_class):
  output = np.zeros(len(SHAPE_CLASSES), dtype=np.float32)
  try:
    output[SHAPE_CLASSES.index(shape_class)] = 1.0
  except ValueError:
    output[-1] = 1.0
  return output


def _descriptor(mask):
  normalized = _binary_sequence_mask(mask, size=DESCRIPTOR_BINARY_SIZE).astype(np.float32)
  _, zone_distribution = _zoning_signature(mask, grid_size=DESCRIPTOR_GRID_SIZE)
  shape = _shape_features(mask)
  profile = _template_profile(mask)

  aspect_ratio = _safe_float(profile.get("aspect_ratio"), 1.0)
  features = np.array(
    [
      _safe_float(profile.get("fill_ratio")),
      min(np.log1p(aspect_ratio) / np.log(16.0), 1.0),
      _safe_float(shape.get("circularity")),
      min(_safe_float(shape.get("rect_aspect_ratio"), 1.0) / 8.0, 1.0),
      _safe_float(shape.get("extent")),
      _safe_float(shape.get("solidity")),
    ],
    dtype=np.float32,
  )

  return np.concatenate(
    [
      normalized.flatten() * 0.90,
      zone_distribution.astype(np.float32) * 2.40,
      features * 2.00,
      _shape_one_hot(shape.get("shape_class")) * 2.80,
    ]
  ).astype(np.float32)


def _descriptor_distance(a, b):
  if a.size == 0 or b.size == 0:
    return float("inf")
  return float(np.linalg.norm(a - b) / np.sqrt(max(a.size, 1)))


def _extract_candidate_components(search_array, template_array, target_rgb=None):
  template_h, template_w = template_array.shape[:2]
  template_area = max(int(np.count_nonzero(template_array)), 1)
  template_profile = _template_profile(template_array)
  template_shape = _shape_features(template_array)
  template_descriptor = _descriptor(template_array)
  search_mask = (search_array > 0).astype(np.uint8) * 255
  kernel, iterations = _grouping_kernel(search_mask, target_rgb=target_rgb)

  grouped_mask = cv2.dilate(search_mask, kernel, iterations=iterations)
  grouped_mask = cv2.morphologyEx(grouped_mask, cv2.MORPH_CLOSE, kernel)
  grouped_mask = cv2.morphologyEx(grouped_mask, cv2.MORPH_OPEN, KERNEL_4_SMALL)
  num_labels, _, stats, _ = cv2.connectedComponentsWithStats((grouped_mask > 0).astype(np.uint8), connectivity=4)

  candidates = []
  max_template_side = max(template_h, template_w, 1)
  min_template_side = max(min(template_h, template_w), 1)
  linear_template = template_profile["family"] == "linear"

  for label in range(1, num_labels):
    x, y, w, h, area = stats[label]
    if area < 5 or w < 3 or h < 3:
      continue
    if w > max(max_template_side * 3.2, 190) or h > max(max_template_side * 3.2, 190):
      continue
    if min(w, h) > min_template_side * 4.0 and not linear_template:
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
    max_area_ratio = 80.0 if linear_template else 10.0
    min_area_ratio = 0.03 if linear_template else 0.06
    if area_ratio < min_area_ratio or area_ratio > max_area_ratio:
      continue

    descriptor = _descriptor(component)
    distance = _descriptor_distance(descriptor, template_descriptor)
    binary_metrics = _binary_sequence_similarity(component, template_array)
    zoning_score = _zoning_similarity(component, template_array)
    signature_score = _radial_signature_score(component, template_array)
    hu_score = _match_shapes_score(component, template_array)
    shape_score, _, component_shape = _shape_similarity_from_template(component, template_shape)

    candidates.append(
      {
        "bbox": [x0, y0, x1, y1],
        "descriptor": descriptor,
        "distance": distance,
        "binary_score": binary_metrics["score"],
        "binary_iou": binary_metrics["iou"],
        "binary_dice": binary_metrics["dice"],
        "binary_hamming": binary_metrics["hamming"],
        "zoning_score": zoning_score,
        "signature_score": signature_score,
        "hu_score": hu_score,
        "shape_score": shape_score,
        "template_shape": template_shape["shape_class"],
        "candidate_shape": component_shape["shape_class"],
        "ink_area": ink_area,
        "area_ratio": area_ratio,
        "size": [int(x1 - x0), int(y1 - y0)],
      }
    )

  candidates.sort(key=lambda item: item["distance"])
  return candidates[:MAX_KMEANS_CANDIDATES], template_descriptor, template_profile, template_shape


def _fixed_center_kmeans(candidates, legend_center, iterations=10):
  if not candidates:
    return None

  descriptors = np.vstack([item["descriptor"] for item in candidates]).astype(np.float32)
  distances = np.linalg.norm(descriptors - legend_center, axis=1)
  farthest_count = max(len(candidates) // 4, 1)
  farthest_indexes = np.argsort(distances)[-farthest_count:]
  other_center = descriptors[farthest_indexes].mean(axis=0)
  labels = np.zeros(len(candidates), dtype=np.int32)

  for _ in range(iterations):
    legend_distances = np.linalg.norm(descriptors - legend_center, axis=1)
    other_distances = np.linalg.norm(descriptors - other_center, axis=1)
    labels = (other_distances < legend_distances).astype(np.int32)
    other_members = descriptors[labels == 1]
    if len(other_members):
      other_center = other_members.mean(axis=0)

  return labels


def _strict_distance_threshold(cluster_distances, all_distances, profile, template_shape):
  if len(cluster_distances) == 0:
    return 0.0

  best_distance = float(np.min(all_distances)) if len(all_distances) else float(np.min(cluster_distances))
  median = float(np.median(cluster_distances))
  mad = float(np.median(np.abs(cluster_distances - median))) if len(cluster_distances) > 1 else 0.0
  family_factor = {
    "solid": 1.16,
    "mixed": 1.20,
    "sparse": 1.24,
    "linear": 1.30,
  }.get(profile["family"], STRICT_DISTANCE_RATIO)
  shape_factor = 1.12 if template_shape["shape_class"] in {"circle", "square", "rectangle", "diamond", "triangle"} else 1.0
  return min(
    median + (mad * 1.35) + STRICT_DISTANCE_MARGIN,
    (best_distance * family_factor * shape_factor) + STRICT_DISTANCE_MARGIN,
  )


def _cluster_matches(candidates, template_descriptor, profile, template_shape):
  if not candidates:
    return [], []

  labels = _fixed_center_kmeans(candidates, template_descriptor)
  if labels is None:
    return [], []

  all_distances = np.array([item["distance"] for item in candidates], dtype=np.float32)
  if not np.any(labels == 0):
    best_distance = float(np.min(all_distances))
    labels = np.where(all_distances <= best_distance + STRICT_DISTANCE_MARGIN, 0, 1).astype(np.int32)
  cluster_distances = all_distances[labels == 0]
  threshold = _strict_distance_threshold(cluster_distances, all_distances, profile, template_shape)
  min_binary = 0.18 if profile["family"] in {"sparse", "linear"} else 0.24
  min_zoning = 0.42 if profile["family"] in {"sparse", "linear"} else 0.50

  accepted = []
  debug = []
  for index, item in enumerate(candidates):
    in_legend_cluster = int(labels[index]) == 0
    accepted_by_distance = item["distance"] <= threshold
    accepted_by_shape = item["shape_score"] > 0 or item["binary_score"] >= 0.42
    accepted_by_binary = item["binary_score"] >= min_binary
    accepted_by_zone = item["zoning_score"] >= min_zoning
    score = 1.0 / (1.0 + item["distance"])
    rejected_by = None
    if not in_legend_cluster:
      rejected_by = "cluster_autre"
    elif not accepted_by_distance:
      rejected_by = "distance_stricte"
    elif not accepted_by_shape:
      rejected_by = "forme"
    elif not accepted_by_binary:
      rejected_by = "suite_binaire"
    elif not accepted_by_zone:
      rejected_by = "zones"

    public_item = {
      "bbox": item["bbox"],
      "score": round(score, 4),
      "distance": round(float(item["distance"]), 4),
      "distance_threshold": round(float(threshold), 4),
      "binary_score": round(float(item["binary_score"]), 4),
      "binary_iou": round(float(item["binary_iou"]), 4),
      "binary_dice": round(float(item["binary_dice"]), 4),
      "binary_hamming": round(float(item["binary_hamming"]), 4),
      "zoning_score": round(float(item["zoning_score"]), 4),
      "signature_score": round(float(item["signature_score"]), 4),
      "hu_score": round(float(item["hu_score"]), 4),
      "shape_score": round(float(item["shape_score"]), 4),
      "template_shape": item["template_shape"],
      "candidate_shape": item["candidate_shape"],
      "cluster": "legende" if in_legend_cluster else "autre",
      "confidence": "haute" if item["distance"] <= threshold * 0.82 else "moyenne",
      "method": "kmeans_strict",
      "ink_area": item["ink_area"],
      "area_ratio": round(float(item["area_ratio"]), 4),
      "size": item["size"],
    }
    if rejected_by:
      debug.append({**public_item, "rejected_by": rejected_by})
      continue
    accepted.append(public_item)
    debug.append(public_item)

  accepted = _nms(accepted, iou_threshold=0.20)
  debug.sort(key=lambda item: item["score"], reverse=True)
  return accepted, debug[:60]


def _match_kmeans_on_page(page, template_array, target_rgb=None):
  clip_rect, separator = _search_clip_for_page(page)
  clip_pixmap = page.get_pixmap(matrix=fitz.Matrix(PAGE_RENDER_ZOOM, PAGE_RENDER_ZOOM), clip=clip_rect, alpha=False)
  clip_image = Image.frombytes("RGB", [clip_pixmap.width, clip_pixmap.height], clip_pixmap.samples)
  search_array = _binarize_page_image(clip_image, target_rgb=target_rgb)
  candidates, template_descriptor, profile, template_shape = _extract_candidate_components(
    search_array,
    template_array,
    target_rgb=target_rgb,
  )
  matches, debug_candidates = _cluster_matches(candidates, template_descriptor, profile, template_shape)
  return matches, clip_rect, separator, debug_candidates, clip_image, len(candidates), profile, template_shape


def match_legend_object_kmeans(pdf_relative_path, object_payload, page_spec=None):
  pdf_path = resolve_repo_pdf_path(pdf_relative_path)
  object_id = object_payload.get("id")
  binary_crop_path = _resolve_repo_file(object_payload.get("binary_crop_path"))
  label = object_payload.get("label") or object_id

  run_dir = binary_crop_path.parent.parent
  output_dir = run_dir / "plan_matches_kmeans" / object_id
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
      matches, clip_rect, separator, debug_candidates, clip_image, candidate_count, profile, template_shape = _match_kmeans_on_page(
        page,
        template_array,
        target_rgb=target_rgb,
      )
      total_matches += len(matches)
      preview_path = output_dir / f"page_{page_number:03d}_matches.png"
      counted_items_path = output_dir / f"page_{page_number:03d}_counted_items.png"
      _save_page_preview(page, page_number, matches, preview_path, clip_rect)
      _save_counted_items_sheet(clip_image, page_number, matches, counted_items_path)
      page_results.append(
        {
          "page": page_number,
          "match_count": len(matches),
          "candidate_count": candidate_count,
          "mode": "kmeans_strict",
          "preview_path": preview_path.relative_to(REPO_ROOT).as_posix(),
          "counted_items_path": counted_items_path.relative_to(REPO_ROOT).as_posix(),
          "separator_x": round(separator["x"], 2) if separator else None,
          "search_clip": [round(clip_rect.x0, 2), round(clip_rect.y0, 2), round(clip_rect.x1, 2), round(clip_rect.y1, 2)],
          "template_profile": profile,
          "template_shape": template_shape,
          "matches": matches[:160],
          "debug_top_candidates": debug_candidates,
        }
      )

  result = {
    "object_id": object_id,
    "label": label,
    "pdf_path": pdf_relative_path,
    "binary_crop_path": object_payload.get("binary_crop_path"),
    "mode": "kmeans_strict",
    "page_count": len(page_results),
    "total_matches": total_matches,
    "pages": page_results,
  }
  result_path = output_dir / "matches.json"
  result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
  return result
