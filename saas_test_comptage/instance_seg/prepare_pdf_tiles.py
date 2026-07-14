import argparse
import json
from pathlib import Path

import fitz

from .common import ensure_dir, non_white_ratio, parse_page_spec, render_pdf_page, save_json, slugify, tile_image


def parse_args():
  parser = argparse.ArgumentParser(
    description="Prepare un vrai dataset COCO pour segmentation d'instances a partir de plans PDF."
  )
  parser.add_argument("--pdf", action="append", default=[], help="PDF a rasteriser. Peut etre passe plusieurs fois.")
  parser.add_argument("--pdf-dir", default=None, help="Dossier de PDF a parcourir.")
  parser.add_argument("--output-root", default="instance_seg/data/plans_coco", help="Racine du dataset COCO.")
  parser.add_argument("--split", default="train", choices=["train", "val", "test"])
  parser.add_argument("--pages", default="1", help="Pages a rasteriser, ex: 1 ou 1,3-5.")
  parser.add_argument("--zoom", type=float, default=2.5)
  parser.add_argument("--tile-size", type=int, default=1024)
  parser.add_argument("--overlap", type=int, default=128)
  parser.add_argument("--min-ink-ratio", type=float, default=0.0025)
  parser.add_argument("--categories-json", default=None, help="Template JSON de categories COCO.")
  return parser.parse_args()


def collect_pdfs(args):
  pdfs = [Path(value) for value in args.pdf]
  if args.pdf_dir:
    pdfs.extend(sorted(Path(args.pdf_dir).glob("*.pdf")))
  unique = []
  seen = set()
  for pdf_path in pdfs:
    resolved = pdf_path.resolve()
    if resolved in seen:
      continue
    if not resolved.exists():
      raise FileNotFoundError(f"PDF introuvable: {pdf_path}")
    seen.add(resolved)
    unique.append(resolved)
  if not unique:
    raise SystemExit("Aucun PDF fourni. Utilise --pdf ou --pdf-dir.")
  return unique


def load_categories(categories_json):
  if not categories_json:
    return []
  payload = json.loads(Path(categories_json).read_text(encoding="utf-8"))
  if isinstance(payload, dict):
    return payload.get("categories", [])
  if isinstance(payload, list):
    return payload
  return []


def next_image_id(coco):
  image_ids = [item.get("id", 0) for item in coco.get("images", [])]
  return (max(image_ids) + 1) if image_ids else 1


def main():
  args = parse_args()
  output_root = ensure_dir(args.output_root)
  split_root = ensure_dir(output_root / args.split)
  images_dir = ensure_dir(split_root / "images")
  annotations_path = split_root / "annotations.json"
  pdf_paths = collect_pdfs(args)

  if annotations_path.exists():
    coco = json.loads(annotations_path.read_text(encoding="utf-8"))
  else:
    coco = {
      "info": {
        "description": "Dataset COCO de segmentation d'instances pour plans techniques.",
        "version": "1.0",
      },
      "licenses": [],
      "images": [],
      "annotations": [],
      "categories": load_categories(args.categories_json),
    }

  image_id = next_image_id(coco)

  for pdf_path in pdf_paths:
    with fitz.open(pdf_path) as document:
      page_numbers = parse_page_spec(args.pages, document.page_count)

    for page_number in page_numbers:
      page_image = render_pdf_page(pdf_path, page_number, zoom=args.zoom)
      tiles = tile_image(page_image, tile_size=args.tile_size, overlap=args.overlap)
      pdf_slug = slugify(pdf_path.stem)

      for tile in tiles:
        if non_white_ratio(tile["image"]) < args.min_ink_ratio:
          continue
        file_name = f"{pdf_slug}_p{page_number:03d}_x{tile['x0']:05d}_y{tile['y0']:05d}.png"
        tile["image"].save(images_dir / file_name)
        coco["images"].append(
          {
            "id": image_id,
            "file_name": file_name,
            "width": tile["image"].width,
            "height": tile["image"].height,
            "source_pdf": str(pdf_path),
            "page": page_number,
            "tile_box": [tile["x0"], tile["y0"], tile["x1"], tile["y1"]],
          }
        )
        image_id += 1

  save_json(annotations_path, coco)
  print(f"Dataset COCO initialise: {annotations_path}")
  print(f"Images generees dans: {images_dir}")
  print("Etape suivante: annoter les masks d'instances dans annotations.json via un outil externe.")


if __name__ == "__main__":
  main()
