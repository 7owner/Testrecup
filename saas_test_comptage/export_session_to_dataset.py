import argparse
import json
import shutil
from pathlib import Path

from PIL import Image


def parse_args():
  parser = argparse.ArgumentParser(
    description="Convertit une session de comptage en dataset local exploitable."
  )
  parser.add_argument("--session", required=True, help="Session JSON exportee depuis l'interface.")
  parser.add_argument("--image", required=True, help="Image de plan associee a la session.")
  parser.add_argument("--dataset", default="datasets/plans", help="Dossier dataset cible.")
  parser.add_argument("--split", default="train", choices=["train", "val", "test"], help="Sous-ensemble cible.")
  parser.add_argument(
    "--box-size",
    type=int,
    default=24,
    help="Taille par defaut des boites creees autour des points manuels.",
  )
  return parser.parse_args()


def load_json(path):
  return json.loads(Path(path).read_text(encoding="utf-8"))


def ensure_dataset_layout(dataset_root, split):
  split_root = dataset_root / split
  images_dir = split_root / "images"
  sessions_dir = split_root / "sessions"
  images_dir.mkdir(parents=True, exist_ok=True)
  sessions_dir.mkdir(parents=True, exist_ok=True)
  return split_root, images_dir, sessions_dir


def load_existing_annotations(path):
  if not path.exists():
    return []
  return json.loads(path.read_text(encoding="utf-8"))


def marker_to_box(marker, label_lookup, box_size):
  half = box_size / 2
  label = label_lookup.get(marker["labelId"])
  if not label:
    return None
  return {
    "label": label["name"],
    "source": "manual_point",
    "point": {
      "x": marker["x"],
      "y": marker["y"],
    },
    "box": [
      round(marker["x"] - half, 2),
      round(marker["y"] - half, 2),
      round(marker["x"] + half, 2),
      round(marker["y"] + half, 2),
    ],
  }


def convert_session(session_data, image_filename, split, box_size):
  label_lookup = {label["id"]: label for label in session_data.get("labels", [])}
  objects = []
  for marker in session_data.get("markers", []):
    box = marker_to_box(marker, label_lookup, box_size)
    if box:
      objects.append(box)

  detections_pages = session_data.get("detectionsByPage", [])
  auto_detections = []
  for page in detections_pages:
    for detection in page.get("detections", []):
      auto_detections.append(
        {
          "label": detection["label"],
          "source": "auto_detection",
          "score": detection.get("score"),
          "box": [
            detection["x1"],
            detection["y1"],
            detection["x2"],
            detection["y2"],
          ],
        }
      )

  return {
    "image": f"{split}/images/{image_filename}",
    "image_filename": image_filename,
    "labels": [label["name"] for label in session_data.get("labels", [])],
    "objects": objects,
    "auto_detections": auto_detections,
    "meta": {
      "selectedDetectionPage": session_data.get("selectedDetectionPage"),
      "imageName": session_data.get("imageName"),
      "dataset_format": "json_master",
    },
  }


def main():
  args = parse_args()
  session_path = Path(args.session)
  image_path = Path(args.image)
  dataset_root = Path(args.dataset)

  if not session_path.exists():
    raise FileNotFoundError(f"Session introuvable: {session_path}")
  if not image_path.exists():
    raise FileNotFoundError(f"Image introuvable: {image_path}")

  split_root, images_dir, sessions_dir = ensure_dataset_layout(dataset_root, args.split)
  annotations_path = split_root / "annotations.json"
  labels_path = dataset_root / "labels.json"

  copied_image_path = images_dir / image_path.name
  copied_session_path = sessions_dir / session_path.name
  shutil.copy2(image_path, copied_image_path)
  shutil.copy2(session_path, copied_session_path)

  session_data = load_json(session_path)
  with Image.open(image_path) as image:
    width, height = image.size
  entry = convert_session(session_data, image_path.name, args.split, args.box_size)
  entry["meta"]["width"] = width
  entry["meta"]["height"] = height

  annotations = load_existing_annotations(annotations_path)
  annotations = [item for item in annotations if item.get("image_filename") != image_path.name]
  annotations.append(entry)
  annotations_path.write_text(json.dumps(annotations, indent=2, ensure_ascii=False), encoding="utf-8")

  label_names = sorted({label["name"] for label in session_data.get("labels", [])})
  existing_labels = []
  if labels_path.exists():
    existing_labels = json.loads(labels_path.read_text(encoding="utf-8"))
  merged_labels = sorted(set(existing_labels) | set(label_names))
  labels_path.write_text(json.dumps(merged_labels, indent=2, ensure_ascii=False), encoding="utf-8")

  print(f"Image copiee: {copied_image_path}")
  print(f"Session copiee: {copied_session_path}")
  print(f"Annotations: {annotations_path}")
  print(f"Labels: {labels_path}")


if __name__ == "__main__":
  main()
