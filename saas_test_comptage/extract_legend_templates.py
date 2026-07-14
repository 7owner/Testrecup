import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def parse_args():
  parser = argparse.ArgumentParser(
    description="Extrait les symboles d'une image de legende en templates exploitables."
  )
  parser.add_argument("--image", required=True, help="Image de legende a analyser.")
  parser.add_argument(
    "--output",
    default="legend_templates",
    help="Dossier de sortie pour les crops et le manifeste.",
  )
  parser.add_argument(
    "--min-area",
    type=int,
    default=40,
    help="Surface minimale d'un symbole candidate.",
  )
  parser.add_argument(
    "--padding",
    type=int,
    default=6,
    help="Padding ajoute autour des symboles detectes.",
  )
  return parser.parse_args()


def load_image(path):
  image = cv2.imread(str(path), cv2.IMREAD_COLOR)
  if image is None:
    raise FileNotFoundError(f"Impossible de lire l'image: {path}")
  return image


def build_color_mask(image):
  hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
  saturation = hsv[:, :, 1]
  value = hsv[:, :, 2]
  mask = np.where((saturation >= 35) & (value <= 250), 255, 0).astype(np.uint8)

  kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
  kernel_dilate = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
  mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open)
  mask = cv2.dilate(mask, kernel_dilate, iterations=1)
  return mask


def extract_components(mask, min_area, max_width):
  num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
  components = []
  for label in range(1, num_labels):
    x, y, w, h, area = stats[label]
    if area < min_area:
      continue
    if w < 5 or h < 5:
      continue
    if w > max_width:
      continue
    components.append({"x": int(x), "y": int(y), "w": int(w), "h": int(h), "area": int(area)})
  return components


def sort_components(components, image_width):
  center_x = image_width // 2
  left = [component for component in components if component["x"] + component["w"] / 2 < center_x]
  right = [component for component in components if component["x"] + component["w"] / 2 >= center_x]
  left.sort(key=lambda component: (component["y"], component["x"]))
  right.sort(key=lambda component: (component["y"], component["x"]))
  ordered = []
  ordered.extend(left)
  ordered.extend(right)
  return ordered


def crop_with_padding(image, component, padding):
  height, width = image.shape[:2]
  x1 = max(component["x"] - padding, 0)
  y1 = max(component["y"] - padding, 0)
  x2 = min(component["x"] + component["w"] + padding, width)
  y2 = min(component["y"] + component["h"] + padding, height)
  return image[y1:y2, x1:x2], (x1, y1, x2, y2)


def save_manifest(output_dir, entries):
  manifest_path = output_dir / "templates.json"
  manifest = {
    "templates": entries,
    "instructions": [
      "Verifier les crops produits.",
      "Renseigner le champ label avec le nom metier attendu.",
      "Supprimer les entrees parasites avant la localisation sur PDF.",
    ],
  }
  manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
  return manifest_path


def main():
  args = parse_args()
  image_path = Path(args.image)
  output_dir = Path(args.output)
  crops_dir = output_dir / "crops"
  output_dir.mkdir(parents=True, exist_ok=True)
  crops_dir.mkdir(parents=True, exist_ok=True)

  image = load_image(image_path)
  mask = build_color_mask(image)
  max_width = max(int(image.shape[1] * 0.22), 40)
  components = sort_components(extract_components(mask, args.min_area, max_width), image.shape[1])

  debug_mask_path = output_dir / "legend_mask.png"
  cv2.imwrite(str(debug_mask_path), mask)

  entries = []
  for index, component in enumerate(components, start=1):
    crop, bbox = crop_with_padding(image, component, args.padding)
    filename = f"symbol_{index:03d}.png"
    crop_path = crops_dir / filename
    cv2.imwrite(str(crop_path), crop)
    x1, y1, x2, y2 = bbox
    entries.append(
      {
        "id": f"symbol_{index:03d}",
        "label": f"symbol_{index:03d}",
        "crop": str(crop_path),
        "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
      }
    )

  manifest_path = save_manifest(output_dir, entries)
  print(f"Templates extraits: {len(entries)}")
  print(f"Masque debug: {debug_mask_path}")
  print(f"Manifeste: {manifest_path}")


if __name__ == "__main__":
  main()
