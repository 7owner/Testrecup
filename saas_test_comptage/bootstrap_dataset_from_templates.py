import argparse
import json
import random
from pathlib import Path

from PIL import Image


def parse_args():
  parser = argparse.ArgumentParser(
    description="Genere un dataset bootstrap train/val a partir de crops de symboles."
  )
  parser.add_argument(
    "--templates",
    default="legend_templates_example/templates.json",
    help="Fichier templates.json source.",
  )
  parser.add_argument(
    "--dataset",
    default="datasets/bootstrap_symbols",
    help="Dossier racine du dataset de sortie.",
  )
  parser.add_argument("--train-per-class", type=int, default=10, help="Nombre d'images train par symbole.")
  parser.add_argument("--val-per-class", type=int, default=3, help="Nombre d'images val par symbole.")
  parser.add_argument("--canvas-size", type=int, default=128, help="Taille des images de sortie.")
  parser.add_argument("--min-scale", type=float, default=0.85, help="Echelle minimale appliquee au crop.")
  parser.add_argument("--max-scale", type=float, default=1.35, help="Echelle maximale appliquee au crop.")
  parser.add_argument("--max-rotation", type=float, default=8.0, help="Rotation absolue max en degres.")
  parser.add_argument("--seed", type=int, default=42, help="Seed de generation.")
  return parser.parse_args()


def load_json(path):
  return json.loads(Path(path).read_text(encoding="utf-8"))


def ensure_layout(dataset_root, split):
  split_root = dataset_root / split
  images_dir = split_root / "images"
  images_dir.mkdir(parents=True, exist_ok=True)
  return split_root, images_dir


def build_background(canvas_size):
  return Image.new("RGB", (canvas_size, canvas_size), color=(255, 255, 255))


def transform_symbol(image, rng, min_scale, max_scale, max_rotation):
  scale = rng.uniform(min_scale, max_scale)
  rotation = rng.uniform(-max_rotation, max_rotation)
  width = max(10, int(round(image.width * scale)))
  height = max(10, int(round(image.height * scale)))
  resized = image.resize((width, height), Image.Resampling.LANCZOS)
  return resized.rotate(rotation, expand=True, fillcolor=(255, 255, 255))


def paste_symbol(canvas, symbol, rng):
  max_x = max(canvas.width - symbol.width, 0)
  max_y = max(canvas.height - symbol.height, 0)
  x = rng.randint(0, max_x) if max_x > 0 else 0
  y = rng.randint(0, max_y) if max_y > 0 else 0
  canvas.paste(symbol, (x, y))
  return [x, y, x + symbol.width, y + symbol.height]


def create_entry(image_filename, label, box, split):
  return {
    "image": f"{split}/images/{image_filename}",
    "image_filename": image_filename,
    "labels": [label],
    "objects": [
      {
        "label": label,
        "source": "bootstrap_template",
        "box": box,
      }
    ],
    "auto_detections": [],
    "meta": {
      "dataset_format": "json_master",
      "width": 128,
      "height": 128,
    },
  }


def generate_split(entries, items, split, count_per_class, dataset_root, args, rng):
  split_root, images_dir = ensure_layout(dataset_root, split)
  annotations = []

  for item in items:
    label = item.get("label") or item["id"]
    crop_path = Path(item["crop"])
    with Image.open(crop_path).convert("RGB") as source:
      for sample_index in range(count_per_class):
        canvas = build_background(args.canvas_size)
        symbol = transform_symbol(source, rng, args.min_scale, args.max_scale, args.max_rotation)
        box = paste_symbol(canvas, symbol, rng)
        image_filename = f"{label}_{sample_index + 1:03d}.png"
        output_path = images_dir / image_filename
        canvas.save(output_path)
        entry = create_entry(image_filename, label, box, split)
        entry["meta"]["width"] = args.canvas_size
        entry["meta"]["height"] = args.canvas_size
        annotations.append(entry)

  annotations_path = split_root / "annotations.json"
  annotations_path.write_text(json.dumps(annotations, indent=2, ensure_ascii=False), encoding="utf-8")
  entries[split] = len(annotations)


def main():
  args = parse_args()
  rng = random.Random(args.seed)
  manifest = load_json(args.templates)
  items = manifest.get("templates", [])
  if len(items) < 2:
    raise SystemExit("Il faut au moins 2 templates pour generer un dataset bootstrap.")

  dataset_root = Path(args.dataset)
  dataset_root.mkdir(parents=True, exist_ok=True)
  labels = sorted({(item.get("label") or item["id"]) for item in items})
  (dataset_root / "labels.json").write_text(json.dumps(labels, indent=2, ensure_ascii=False), encoding="utf-8")

  counts = {}
  generate_split(counts, items, "train", args.train_per_class, dataset_root, args, rng)
  generate_split(counts, items, "val", args.val_per_class, dataset_root, args, rng)

  summary = {
    "templates": args.templates,
    "dataset": str(dataset_root),
    "num_classes": len(labels),
    "counts": counts,
    "seed": args.seed,
  }
  (dataset_root / "bootstrap_summary.json").write_text(
    json.dumps(summary, indent=2, ensure_ascii=False),
    encoding="utf-8",
  )
  print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
  main()
