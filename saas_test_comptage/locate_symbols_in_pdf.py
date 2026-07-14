import argparse
import json
from pathlib import Path

import cv2
import fitz
import numpy as np


def parse_args():
  parser = argparse.ArgumentParser(
    description="Localise dans un PDF ou une image les symboles issus d'une legende."
  )
  parser.add_argument("--pdf", help="PDF plan a analyser.")
  parser.add_argument("--image", help="Image plan a analyser.")
  parser.add_argument("--templates", required=True, help="templates.json issu de l'extraction.")
  parser.add_argument("--output", default="results", help="Dossier de sortie.")
  parser.add_argument("--dpi", type=int, default=220, help="Resolution de rendu des pages PDF.")
  parser.add_argument("--threshold", type=float, default=0.62, help="Score minimum de matching.")
  parser.add_argument("--min-scale", type=float, default=0.5, help="Echelle minimale des templates.")
  parser.add_argument("--max-scale", type=float, default=1.6, help="Echelle maximale des templates.")
  parser.add_argument("--scale-step", type=float, default=0.1, help="Pas d'echelle.")
  parser.add_argument("--nms-distance", type=int, default=18, help="Distance mini entre deux detections.")
  return parser.parse_args()


def validate_args(args):
  if bool(args.pdf) == bool(args.image):
    raise SystemExit("Il faut fournir exactement un seul input: --pdf ou --image.")


def render_pdf(pdf_path, dpi):
  document = fitz.open(pdf_path)
  zoom = dpi / 72.0
  matrix = fitz.Matrix(zoom, zoom)
  pages = []
  for page_index in range(document.page_count):
    page = document.load_page(page_index)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
    pages.append(cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
  return pages


def load_image_as_single_page(image_path):
  image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
  if image is None:
    raise FileNotFoundError(f"Impossible de lire l'image: {image_path}")
  return [image]


def load_manifest(manifest_path):
  data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
  templates = []
  for item in data["templates"]:
    crop_path = Path(item["crop"])
    image = cv2.imread(str(crop_path), cv2.IMREAD_COLOR)
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


def generate_scales(min_scale, max_scale, step):
  scales = []
  value = min_scale
  while value <= max_scale + 1e-9:
    scales.append(round(value, 4))
    value += step
  return scales


def locate_template(page_image, template_image, threshold, scales, min_distance):
  page_edges = grayscale_edges(page_image)
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
      score = float(result[y, x])
      candidates.append(
        {
          "x1": int(x),
          "y1": int(y),
          "x2": int(x + width),
          "y2": int(y + height),
          "score": score,
          "scale": scale,
        }
      )

  return non_max_suppression(candidates, min_distance)


def annotate_page(page_image, detections):
  annotated = page_image.copy()
  for detection in detections:
    color = (0, 0, 255)
    cv2.rectangle(annotated, (detection["x1"], detection["y1"]), (detection["x2"], detection["y2"]), color, 2)
    text = f'{detection["label"]} {detection["score"]:.2f}'
    (text_width, text_height), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    y_text = max(detection["y1"] - 8, text_height + 4)
    cv2.rectangle(
      annotated,
      (detection["x1"], y_text - text_height - 4),
      (detection["x1"] + text_width + 8, y_text + baseline),
      color,
      -1,
    )
    cv2.putText(
      annotated,
      text,
      (detection["x1"] + 4, y_text - 2),
      cv2.FONT_HERSHEY_SIMPLEX,
      0.45,
      (255, 255, 255),
      1,
      cv2.LINE_AA,
    )
  return annotated


def main():
  args = parse_args()
  validate_args(args)
  output_dir = Path(args.output)
  pages_dir = output_dir / "pages"
  output_dir.mkdir(parents=True, exist_ok=True)
  pages_dir.mkdir(parents=True, exist_ok=True)

  templates = load_manifest(args.templates)
  if args.pdf:
    pages = render_pdf(args.pdf, args.dpi)
    input_descriptor = {"type": "pdf", "path": args.pdf}
  else:
    pages = load_image_as_single_page(args.image)
    input_descriptor = {"type": "image", "path": args.image}
  scales = generate_scales(args.min_scale, args.max_scale, args.scale_step)

  report = {"input": input_descriptor, "pages": []}
  for page_index, page_image in enumerate(pages, start=1):
    page_detections = []
    for template in templates:
      detections = locate_template(
        page_image,
        template["image"],
        args.threshold,
        scales,
        args.nms_distance,
      )
      for detection in detections:
        page_detections.append(
          {
            "template_id": template["id"],
            "label": template["label"],
            "score": detection["score"],
            "scale": detection["scale"],
            "x1": detection["x1"],
            "y1": detection["y1"],
            "x2": detection["x2"],
            "y2": detection["y2"],
          }
        )

    annotated = annotate_page(page_image, page_detections)
    output_page = pages_dir / f"page_{page_index:03d}.png"
    cv2.imwrite(str(output_page), annotated)
    report["pages"].append(
      {
        "page": page_index,
        "image": str(output_page),
        "detections": page_detections,
      }
    )
    print(f"Page {page_index}: {len(page_detections)} detections")

  report_path = output_dir / "detections.json"
  report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
  print(f"Rapport: {report_path}")


if __name__ == "__main__":
  main()
