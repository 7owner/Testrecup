import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont
import torch

from .common import ensure_dir, mask_to_polygons, nms_records, parse_page_spec, render_pdf_page, save_json, tile_image
from .modeling import load_model_from_checkpoint


def parse_args():
  parser = argparse.ArgumentParser(
    description="Inference de segmentation d'instances sur image ou PDF, avec comptage par classe."
  )
  parser.add_argument("--checkpoint", required=True)
  parser.add_argument("--input", required=True, help="Image ou PDF.")
  parser.add_argument("--output-dir", default="outputs/instance_seg")
  parser.add_argument("--pages", default="1", help="Seulement si l'entree est un PDF.")
  parser.add_argument("--tile-size", type=int, default=1024)
  parser.add_argument("--overlap", type=int, default=128)
  parser.add_argument("--score-threshold", type=float, default=0.50)
  parser.add_argument("--mask-threshold", type=float, default=0.50)
  parser.add_argument("--nms-threshold", type=float, default=0.35)
  parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
  return parser.parse_args()


def resolve_device(device_arg):
  if device_arg == "cpu":
    return torch.device("cpu")
  if device_arg == "cuda":
    return torch.device("cuda")
  return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_inputs(input_path, pages):
  input_path = Path(input_path)
  if not input_path.exists():
    raise FileNotFoundError(f"Entree introuvable: {input_path}")

  if input_path.suffix.lower() == ".pdf":
    import fitz
    with fitz.open(input_path) as document:
      page_numbers = parse_page_spec(pages, document.page_count)
    return [
      {
        "name": f"{input_path.stem}_page_{page_number:03d}",
        "image": render_pdf_page(input_path, page_number, zoom=2.5),
        "page": page_number,
      }
      for page_number in page_numbers
    ]

  with Image.open(input_path).convert("RGB") as image:
    return [{"name": input_path.stem, "image": image.copy(), "page": 1}]


def image_to_tensor(image):
  array = np.asarray(image, dtype=np.float32) / 255.0
  return torch.from_numpy(array).permute(2, 0, 1)


def palette_color(index):
  palette = ["#ef4444", "#2563eb", "#16a34a", "#d97706", "#9333ea", "#0891b2", "#be123c", "#4f46e5"]
  return ImageColor.getrgb(palette[index % len(palette)])


def draw_records(image, records):
  overlay = image.convert("RGBA").copy()
  draw = ImageDraw.Draw(overlay, "RGBA")
  try:
    font = ImageFont.truetype("DejaVuSans.ttf", 18)
  except OSError:
    font = ImageFont.load_default()

  for record in records:
    color = palette_color(record["category_id"])
    fill = (color[0], color[1], color[2], 56)
    outline = (color[0], color[1], color[2], 220)
    for polygon in record.get("segmentation", []):
      points = [(polygon[i], polygon[i + 1]) for i in range(0, len(polygon), 2)]
      if len(points) >= 3:
        draw.polygon(points, fill=fill, outline=outline)
    x0, y0, x1, y1 = record["bbox_xyxy"]
    draw.rectangle((x0, y0, x1, y1), outline=outline, width=2)
    label = f"{record['category_name']} {record['score']:.2f}"
    tx0, ty0, tx1, ty1 = draw.textbbox((x0, y0), label, font=font)
    draw.rectangle((tx0, ty0, tx1 + 8, ty1 + 6), fill=outline)
    draw.text((x0 + 4, y0 + 3), label, fill=(255, 255, 255, 255), font=font)

  return overlay.convert("RGB")


def count_by_category(records):
  counts = {}
  for record in records:
    name = record["category_name"]
    counts[name] = counts.get(name, 0) + 1
  return counts


def run_on_image(model, categories, image, args, device):
  records = []
  tiles = tile_image(image, tile_size=args.tile_size, overlap=args.overlap)

  with torch.no_grad():
    for tile in tiles:
      tensor = image_to_tensor(tile["image"]).to(device)
      predictions = model([tensor])[0]
      boxes = predictions["boxes"].detach().cpu().numpy()
      scores = predictions["scores"].detach().cpu().numpy()
      labels = predictions["labels"].detach().cpu().numpy()
      masks = predictions["masks"].detach().cpu().numpy() if "masks" in predictions else []

      for index, score in enumerate(scores):
        if float(score) < args.score_threshold:
          continue
        label_id = int(labels[index])
        if label_id <= 0 or label_id > len(categories):
          continue
        mask = masks[index, 0] > args.mask_threshold
        if int(mask.sum()) <= 4:
          continue
        polygons = mask_to_polygons(mask.astype(np.uint8), offset_x=tile["x0"], offset_y=tile["y0"])
        if not polygons:
          continue
        x0, y0, x1, y1 = boxes[index].tolist()
        records.append(
          {
            "score": float(score),
            "category_id": int(categories[label_id - 1]["id"]),
            "category_name": categories[label_id - 1]["name"],
            "bbox_xyxy": [
              float(x0 + tile["x0"]),
              float(y0 + tile["y0"]),
              float(x1 + tile["x0"]),
              float(y1 + tile["y0"]),
            ],
            "bbox": [
              float(x0 + tile["x0"]),
              float(y0 + tile["y0"]),
              float(x1 - x0),
              float(y1 - y0),
            ],
            "segmentation": polygons,
          }
        )

  return nms_records(records, iou_threshold=args.nms_threshold)


def main():
  args = parse_args()
  output_dir = ensure_dir(args.output_dir)
  device = resolve_device(args.device)
  model, categories, checkpoint = load_model_from_checkpoint(args.checkpoint, device=device)

  inputs = load_inputs(args.input, args.pages)
  summary = {
    "checkpoint": args.checkpoint,
    "config": checkpoint.get("config") or {},
    "pages": [],
  }

  for item in inputs:
    records = run_on_image(model, categories, item["image"], args, device)
    annotated = draw_records(item["image"], records)
    image_name = f"{item['name']}_instances.png"
    json_name = f"{item['name']}_instances.json"
    annotated.save(output_dir / image_name)
    page_payload = {
      "name": item["name"],
      "page": item["page"],
      "counts": count_by_category(records),
      "instance_count": len(records),
      "instances": records,
      "preview_path": str((output_dir / image_name).as_posix()),
    }
    save_json(output_dir / json_name, page_payload)
    summary["pages"].append(page_payload)
    print(f"{item['name']}: {len(records)} instances")

  save_json(output_dir / "summary.json", summary)


if __name__ == "__main__":
  main()
