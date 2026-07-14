import argparse
import json
from pathlib import Path

from PIL import Image


def parse_args():
  parser = argparse.ArgumentParser(
    description="Decoupe une image composite plan + legende en zones exploitables."
  )
  parser.add_argument("--image", required=True, help="Image composite a decouper.")
  parser.add_argument("--output", default="split_output", help="Dossier de sortie.")
  parser.add_argument(
    "--legend-width-ratio",
    type=float,
    default=0.235,
    help="Part relative reservee a la legende a gauche.",
  )
  parser.add_argument(
    "--top-plan-top-ratio",
    type=float,
    default=0.0,
    help="Haut relatif du plan superieur dans la zone hors legende.",
  )
  parser.add_argument(
    "--top-plan-bottom-ratio",
    type=float,
    default=0.50,
    help="Bas relatif du plan superieur dans la zone hors legende.",
  )
  parser.add_argument(
    "--bottom-plan-top-ratio",
    type=float,
    default=0.50,
    help="Haut relatif du plan inferieur dans la zone hors legende.",
  )
  parser.add_argument(
    "--bottom-plan-bottom-ratio",
    type=float,
    default=1.0,
    help="Bas relatif du plan inferieur dans la zone hors legende.",
  )
  return parser.parse_args()


def crop(image, bbox):
  x1, y1, x2, y2 = bbox
  return image.crop((x1, y1, x2, y2))


def main():
  args = parse_args()
  image_path = Path(args.image)
  output_dir = Path(args.output)
  output_dir.mkdir(parents=True, exist_ok=True)

  image = Image.open(image_path).convert("RGB")
  width, height = image.size

  legend_right = int(width * args.legend_width_ratio)
  plan_left = legend_right

  top_y1 = int(height * args.top_plan_top_ratio)
  top_y2 = int(height * args.top_plan_bottom_ratio)
  bottom_y1 = int(height * args.bottom_plan_top_ratio)
  bottom_y2 = int(height * args.bottom_plan_bottom_ratio)

  legend_bbox = [0, 0, legend_right, height]
  top_plan_bbox = [plan_left, top_y1, width, top_y2]
  bottom_plan_bbox = [plan_left, bottom_y1, width, bottom_y2]

  outputs = {
    "legend": {"bbox": legend_bbox, "path": str(output_dir / "legend.png")},
    "top_plan": {"bbox": top_plan_bbox, "path": str(output_dir / "plan_r_plus_1.png")},
    "bottom_plan": {"bbox": bottom_plan_bbox, "path": str(output_dir / "plan_rdc.png")},
  }

  crop(image, legend_bbox).save(outputs["legend"]["path"])
  crop(image, top_plan_bbox).save(outputs["top_plan"]["path"])
  crop(image, bottom_plan_bbox).save(outputs["bottom_plan"]["path"])

  manifest_path = output_dir / "split_manifest.json"
  manifest_path.write_text(json.dumps(outputs, indent=2), encoding="utf-8")

  print(f"Legend: {outputs['legend']['path']}")
  print(f"Top plan: {outputs['top_plan']['path']}")
  print(f"Bottom plan: {outputs['bottom_plan']['path']}")
  print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
  main()
