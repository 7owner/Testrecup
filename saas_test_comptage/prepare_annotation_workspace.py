import argparse
import json
import random
import shutil
from pathlib import Path


def parse_args():
  parser = argparse.ArgumentParser(
    description="Prepare un workspace d'annotation train/val a partir des pages rendues."
  )
  parser.add_argument(
    "--render-manifest",
    default="prepared_data/rendered_examples/render_manifest.json",
    help="Manifeste produit par batch_render_examples.py",
  )
  parser.add_argument(
    "--output-dir",
    default="prepared_data/annotation_workspace",
    help="Dossier du workspace d'annotation.",
  )
  parser.add_argument(
    "--labels-from",
    default="legend_templates_example/templates.json",
    help="Source pour pre-remplir labels.json",
  )
  parser.add_argument("--val-ratio", type=float, default=0.2, help="Part des pages reservees a la validation.")
  parser.add_argument("--seed", type=int, default=42, help="Seed de repartition.")
  return parser.parse_args()


def load_json(path):
  return json.loads(Path(path).read_text(encoding="utf-8"))


def ensure_dirs(root):
  for split in ("train", "val"):
    (root / split / "images").mkdir(parents=True, exist_ok=True)
    (root / split / "sessions").mkdir(parents=True, exist_ok=True)


def collect_labels(labels_from_path):
  data = load_json(labels_from_path)
  if isinstance(data, list):
    return sorted({str(item) for item in data})
  templates = data.get("templates", [])
  return sorted({(item.get("label") or item["id"]) for item in templates})


def copy_page(image_path, destination):
  destination.parent.mkdir(parents=True, exist_ok=True)
  shutil.copy2(image_path, destination)


def main():
  args = parse_args()
  manifest = load_json(args.render_manifest)
  output_dir = Path(args.output_dir)
  ensure_dirs(output_dir)

  pages = []
  for document in manifest["documents"]:
    for page in document["pages"]:
      pages.append(
        {
          "pdf": document["pdf"],
          "slug": document["slug"],
          "page": page["page"],
          "image": page["image"],
          "width": page["width"],
          "height": page["height"],
        }
      )

  rng = random.Random(args.seed)
  rng.shuffle(pages)
  val_count = max(1, int(round(len(pages) * args.val_ratio))) if pages else 0
  val_indexes = set(range(val_count))

  queue = []
  for index, page in enumerate(pages):
    split = "val" if index in val_indexes else "train"
    image_path = Path(page["image"])
    output_name = f"{page['slug']}_page_{page['page']:03d}.png"
    output_path = output_dir / split / "images" / output_name
    copy_page(image_path, output_path)
    queue.append(
      {
        "split": split,
        "image_filename": output_name,
        "image": str(output_path),
        "source_pdf": page["pdf"],
        "source_page": page["page"],
        "width": page["width"],
        "height": page["height"],
      }
    )

  labels = collect_labels(args.labels_from)
  (output_dir / "labels.json").write_text(json.dumps(labels, indent=2, ensure_ascii=False), encoding="utf-8")
  queue_path = output_dir / "annotation_queue.json"
  queue_path.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")

  starter = {
    "instructions": [
      "Ouvrir plan_counter_ui/plan_counter.html",
      "Charger labels.json depuis ce workspace",
      "Charger une image depuis train/images ou val/images",
      "Poser les points manuels puis exporter la session JSON dans le dossier sessions du split correspondant",
      "Convertir ensuite les sessions vers datasets/plans avec export_session_to_dataset.py",
    ],
    "render_manifest": args.render_manifest,
    "labels_file": str(output_dir / "labels.json"),
    "queue_file": str(queue_path),
    "train_images_dir": str(output_dir / "train" / "images"),
    "val_images_dir": str(output_dir / "val" / "images"),
  }
  (output_dir / "README_annotation.json").write_text(
    json.dumps(starter, indent=2, ensure_ascii=False),
    encoding="utf-8",
  )

  print(f"Workspace: {output_dir}")
  print(f"Pages preparees: {len(queue)}")
  print(f"Train: {sum(1 for item in queue if item['split'] == 'train')}")
  print(f"Val: {sum(1 for item in queue if item['split'] == 'val')}")
  print(f"Queue: {queue_path}")


if __name__ == "__main__":
  main()
