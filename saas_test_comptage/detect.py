import argparse
import json
from pathlib import Path

import torch
from PIL import Image, ImageDraw, ImageFont
from transformers import pipeline


DEFAULT_MODEL_DIR = Path("models/owlv2-base-patch16-ensemble")
DEFAULT_MODEL_ID = "google/owlv2-base-patch16-ensemble"


def parse_args():
  parser = argparse.ArgumentParser(
    description="Detecte des objets/appareils depuis une image et des libelles utilisateur."
  )
  parser.add_argument("--image", required=True, help="Chemin de l'image a analyser.")
  parser.add_argument(
    "--labels",
    nargs="+",
    required=True,
    help="Choix utilisateur a rechercher, ex: compteur electrique disjoncteur.",
  )
  parser.add_argument(
    "--threshold",
    type=float,
    default=0.12,
    help="Score minimum de detection. Baisser si rien n'est detecte.",
  )
  parser.add_argument(
    "--output",
    default="outputs/result.jpg",
    help="Chemin de l'image annotee produite.",
  )
  parser.add_argument(
    "--model",
    default=None,
    help="Chemin local ou identifiant Hugging Face. Par defaut: modele telecharge localement.",
  )
  return parser.parse_args()


def get_model_name(model_arg):
  if model_arg:
    return model_arg
  if DEFAULT_MODEL_DIR.exists():
    return str(DEFAULT_MODEL_DIR)
  return DEFAULT_MODEL_ID


def draw_detections(image, detections):
  annotated = image.convert("RGB").copy()
  draw = ImageDraw.Draw(annotated)

  try:
    font = ImageFont.truetype("DejaVuSans.ttf", 18)
  except OSError:
    font = ImageFont.load_default()

  for detection in detections:
    box = detection["box"]
    xmin = int(box["xmin"])
    ymin = int(box["ymin"])
    xmax = int(box["xmax"])
    ymax = int(box["ymax"])
    label = f'{detection["label"]} {detection["score"]:.2f}'

    draw.rectangle((xmin, ymin, xmax, ymax), outline="red", width=4)
    left, top, right, bottom = draw.textbbox((xmin, ymin), label, font=font)
    draw.rectangle((left, top, right + 8, bottom + 6), fill="red")
    draw.text((xmin + 4, ymin + 3), label, fill="white", font=font)

  return annotated


def main():
  args = parse_args()
  image_path = Path(args.image)
  output_path = Path(args.output)

  if not image_path.exists():
    raise FileNotFoundError(f"Image introuvable: {image_path}")

  device = 0 if torch.cuda.is_available() else -1
  detector = pipeline(
    task="zero-shot-object-detection",
    model=get_model_name(args.model),
    device=device,
  )

  image = Image.open(image_path).convert("RGB")
  detections = detector(
    image,
    candidate_labels=args.labels,
    threshold=args.threshold,
  )

  output_path.parent.mkdir(parents=True, exist_ok=True)
  annotated = draw_detections(image, detections)
  annotated.save(output_path)

  print(json.dumps(detections, ensure_ascii=False, indent=2))
  print(f"Image annotee: {output_path}")


if __name__ == "__main__":
  main()
