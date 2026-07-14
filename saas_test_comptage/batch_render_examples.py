import argparse
import json
import re
import unicodedata
from pathlib import Path

import fitz
from PIL import Image


def parse_args():
  parser = argparse.ArgumentParser(
    description="Rend tous les PDF d'un dossier en pages PNG avec manifeste global."
  )
  parser.add_argument("--input-dir", default="exemples", help="Dossier contenant les PDF source.")
  parser.add_argument("--output-dir", default="prepared_data/rendered_examples", help="Dossier de sortie.")
  parser.add_argument("--dpi", type=int, default=180, help="Resolution de rendu.")
  return parser.parse_args()


def slugify(value):
  normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
  normalized = normalized.lower()
  normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
  return normalized or "document"


def render_pdf(pdf_path, output_dir, dpi):
  document = fitz.open(pdf_path)
  zoom = dpi / 72.0
  matrix = fitz.Matrix(zoom, zoom)

  pdf_slug = slugify(pdf_path.stem)
  pdf_dir = output_dir / pdf_slug
  pdf_dir.mkdir(parents=True, exist_ok=True)

  pages = []
  for page_index in range(document.page_count):
    page = document.load_page(page_index)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
    page_name = f"page_{page_index + 1:03d}.png"
    page_path = pdf_dir / page_name
    image.save(page_path)
    pages.append(
      {
        "page": page_index + 1,
        "image": str(page_path),
        "width": pixmap.width,
        "height": pixmap.height,
      }
    )

  document.close()
  return {
    "pdf": str(pdf_path),
    "slug": pdf_slug,
    "pages": pages,
  }


def main():
  args = parse_args()
  input_dir = Path(args.input_dir)
  output_dir = Path(args.output_dir)
  output_dir.mkdir(parents=True, exist_ok=True)

  pdfs = sorted(input_dir.glob("*.pdf"))
  if not pdfs:
    raise SystemExit(f"Aucun PDF trouve dans {input_dir}")

  manifest = {
    "input_dir": str(input_dir),
    "output_dir": str(output_dir),
    "dpi": args.dpi,
    "documents": [],
  }

  for pdf_path in pdfs:
    record = render_pdf(pdf_path, output_dir, args.dpi)
    manifest["documents"].append(record)
    print(f"{pdf_path.name}: {len(record['pages'])} page(s)")

  total_pages = sum(len(doc["pages"]) for doc in manifest["documents"])
  manifest["document_count"] = len(manifest["documents"])
  manifest["page_count"] = total_pages

  manifest_path = output_dir / "render_manifest.json"
  manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
  print(f"Manifest: {manifest_path}")
  print(f"Total documents: {len(manifest['documents'])}")
  print(f"Total pages: {total_pages}")


if __name__ == "__main__":
  main()
