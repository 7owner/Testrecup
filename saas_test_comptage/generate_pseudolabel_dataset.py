import argparse
import json
import shutil
from pathlib import Path

import cv2
import numpy as np


def parse_args():
  parser = argparse.ArgumentParser(
    description="Genere un dataset pseudo-annote a partir des pages rendues et des templates."
  )
  parser.add_argument(
    "--workspace",
    default="prepared_data/annotation_workspace",
    help="Workspace prepare avec train/images et val/images.",
  )
  parser.add_argument(
    "--templates",
    default="legend_templates_example/templates.json",
    help="templates.json contenant les symboles.",
  )
  parser.add_argument(
    "--dataset",
    default="datasets/plans_auto",
    help="Dataset cible a generer.",
  )
  parser.add_argument(
    "--max-page-size",
    type=int,
    default=2200,
    help="Taille max du grand cote pour accelerer le matching.",
  )
  parser.add_argument(
    "--threshold",
    type=float,
    default=0.74,
    help="Seuil minimum de matching.",
  )
  parser.add_argument(
    "--min-scale",
    type=float,
    default=0.7,
    help="Echelle minimale des templates.",
  )
  parser.add_argument(
    "--max-scale",
    type=float,
    default=1.35,
    help="Echelle maximale des templates.",
  )
  parser.add_argument(
    "--scale-step",
    type=float,
    default=0.15,
    help="Pas d'echelle.",
  )
  parser.add_argument(
    "--nms-distance",
    type=int,
    default=18,
    help="Distance mini entre deux detections conservees.",
  )
  parser.add_argument(
    "--max-per-template",
    type=int,
    default=60,
    help="Nombre max de detections conservees par template et par image.",
  )
  return parser.parse_args()


def load_json(path):
  return json.loads(Path(path).read_text(encoding="utf-8"))


def ensure_dataset_layout(dataset_root):
  for split in ("train", "val", "test"):
    (dataset_root / split / "images").mkdir(parents=True, exist_ok=True)
    (dataset_root / split / "sessions").mkdir(parents=True, exist_ok=True)


def generate_scales(min_scale, max_scale, step):
  scales = []
  value = min_scale
  while value <= max_scale + 1e-9:
    scales.append(round(value, 4))
    value += step
  return scales


def load_templates(path):
  data = load_json(path)
  templates = []
  for item in data.get("templates", []):
    image = cv2.imread(str(item["crop"]), cv2.IMREAD_COLOR)
    if image is None:
      continue
    templates.append(
      {
        "id": item["id"],
        "label": item.get("label") or item["id"],
        "image": image,
      }
    )
  return templates


def resize_for_matching(image, max_page_size):
  height, width = image.shape[:2]
  longest = max(width, height)
  if longest <= max_page_size:
    return image, 1.0
  ratio = max_page_size / float(longest)
  resized = cv2.resize(image, (int(round(width * ratio)), int(round(height * ratio))), interpolation=cv2.INTER_AREA)
  return resized, ratio


def grayscale_edges(image):
  gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
  blurred = cv2.GaussianBlur(gray, (3, 3), 0)
  return cv2.Canny(blurred, 60, 180)


def non_max_suppression(candidates, min_distance):
  ordered = sorted(candidates, key=lambda candidate: candidate["score"], reverse=True)
  kept = []
  for candidate in ordered:
    center_x = (candidate["x1"] + candidate["x2"]) / 2
    center_y = (candidate["y1"] + candidate["y2"]) / 2
    too_close = False
    for existing in kept:
      existing_x = (existing["x1"] + existing["x2"]) / 2
      existing_y = (existing["y1"] + existing["y2"]) / 2
      if abs(center_x - existing_x) <= min_distance and abs(center_y - existing_y) <= min_distance:
        too_close = True
        break
    if not too_close:
      kept.append(candidate)
  return kept


def locate_template(page_edges, template_image, threshold, scales, min_distance, max_per_template):
  candidates = []

  for scale in scales:
    width = max(int(template_image.shape[1] * scale), 8)
    height = max(int(template_image.shape[0] * scale), 8)
    if width >= page_edges.shape[1] or height >= page_edges.shape[0]:
      continue

    resized = cv2.resize(template_image, (width, height), interpolation=cv2.INTER_AREA)
    template_edges = grayscale_edges(resized)
    if template_edges.sum() == 0:
      continue

    result = cv2.matchTemplate(page_edges, template_edges, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(result >= threshold)
    for y, x in zip(ys.tolist(), xs.tolist()):
      candidates.append(
        {
          "x1": int(x),
          "y1": int(y),
          "x2": int(x + width),
          "y2": int(y + height),
          "score": float(result[y, x]),
        }
      )

  kept = non_max_suppression(candidates, min_distance)
  return kept[:max_per_template]


def copy_image(image_path, dataset_root, split):
  destination = dataset_root / split / "images" / image_path.name
  if not destination.exists():
    shutil.copy2(image_path, destination)
  return destination


def detect_on_image(image_path, templates, scales, args):
  original = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
  if original is None:
    raise FileNotFoundError(f"Image introuvable: {image_path}")

  resized, ratio = resize_for_matching(original, args.max_page_size)
  page_edges = grayscale_edges(resized)
  detections = []

  for template in templates:
    matches = locate_template(
      page_edges,
      template["image"],
      args.threshold,
      scales,
      args.nms_distance,
      args.max_per_template,
    )
    for match in matches:
      detections.append(
        {
          "label": template["label"],
          "score": round(match["score"], 4),
          "box": [
            round(match["x1"] / ratio, 2),
            round(match["y1"] / ratio, 2),
            round(match["x2"] / ratio, 2),
            round(match["y2"] / ratio, 2),
          ],
        }
      )

  detections.sort(key=lambda item: (item["label"], -item["score"]))
  return detections, original.shape[1], original.shape[0]


def build_annotation_entry(image_name, width, height, split, detections):
  return {
    "image": f"{split}/images/{image_name}",
    "image_filename": image_name,
    "labels": sorted({item["label"] for item in detections}),
    "objects": [
      {
        "label": item["label"],
        "source": "pseudo_template_matching",
        "score": item["score"],
        "box": item["box"],
      }
      for item in detections
    ],
    "auto_detections": [],
    "meta": {
      "dataset_format": "json_master",
      "width": width,
      "height": height,
      "pseudo_labels": True,
    },
  }


def write_split_annotations(dataset_root, split, annotations):
  output = dataset_root / split / "annotations.json"
  output.write_text(json.dumps(annotations, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
  args = parse_args()
  workspace = Path(args.workspace)
  dataset_root = Path(args.dataset)
  ensure_dataset_layout(dataset_root)

  templates = load_templates(args.templates)
  if not templates:
    raise SystemExit("Aucun template exploitable.")

  scales = generate_scales(args.min_scale, args.max_scale, args.scale_step)
  labels = sorted({template["label"] for template in templates})
  (dataset_root / "labels.json").write_text(json.dumps(labels, indent=2, ensure_ascii=False), encoding="utf-8")

  summary = {
    "workspace": str(workspace),
    "dataset": str(dataset_root),
    "threshold": args.threshold,
    "max_page_size": args.max_page_size,
    "documents": [],
    "counts": {},
  }

  for split in ("train", "val"):
    images_dir = workspace / split / "images"
    if not images_dir.exists():
      continue

    annotations = []
    split_images = sorted(images_dir.glob("*.png"))
    total_detections = 0

    for image_path in split_images:
      destination = copy_image(image_path, dataset_root, split)
      detections, width, height = detect_on_image(image_path, templates, scales, args)
      total_detections += len(detections)
      annotations.append(build_annotation_entry(destination.name, width, height, split, detections))
      print(f"{split} {image_path.name}: {len(detections)} pseudo-detections")

    write_split_annotations(dataset_root, split, annotations)
    summary["counts"][split] = {
      "images": len(annotations),
      "detections": total_detections,
    }

  summary_path = dataset_root / "pseudo_summary.json"
  summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
  print(f"Summary: {summary_path}")


if __name__ == "__main__":
  main()
