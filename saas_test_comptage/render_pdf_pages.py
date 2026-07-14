import argparse
import json
from pathlib import Path

import fitz
from PIL import Image


def parse_args():
  parser = argparse.ArgumentParser(
    description="Rend un PDF multipage en images PNG page par page."
  )
  parser.add_argument("--pdf", required=True, help="PDF a rendre.")
  parser.add_argument("--output", default="rendered_pages", help="Dossier de sortie.")
  parser.add_argument("--dpi", type=int, default=220, help="Resolution de rendu.")
  return parser.parse_args()


def main():
  args = parse_args()
  output_dir = Path(args.output)
  output_dir.mkdir(parents=True, exist_ok=True)

  document = fitz.open(args.pdf)
  zoom = args.dpi / 72.0
  matrix = fitz.Matrix(zoom, zoom)

  manifest = {"pdf": args.pdf, "dpi": args.dpi, "pages": []}
  for page_index in range(document.page_count):
    page = document.load_page(page_index)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
    path = output_dir / f"page_{page_index + 1:03d}.png"
    image.save(path)
    manifest["pages"].append({"page": page_index + 1, "image": str(path)})
    print(f"Page {page_index + 1}: {path}")

  manifest_path = output_dir / "pages_manifest.json"
  manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
  print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
  main()
