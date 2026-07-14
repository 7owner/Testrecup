import argparse
import json
from pathlib import Path

import h5py
import numpy as np


def parse_args():
  parser = argparse.ArgumentParser(
    description="Exporte le dataset JSON maitre vers un conteneur HDF5 optionnel."
  )
  parser.add_argument("--dataset", default="datasets/plans", help="Racine du dataset JSON.")
  parser.add_argument("--output", default="datasets/plans_dataset.h5", help="Fichier HDF5 de sortie.")
  return parser.parse_args()


def load_json(path):
  return json.loads(Path(path).read_text(encoding="utf-8"))


def encode_text_list(values):
  return np.array([value.encode("utf-8") for value in values], dtype=h5py.string_dtype("utf-8"))


def export_split(h5_file, dataset_root, split):
  split_root = Path(dataset_root) / split
  annotations_path = split_root / "annotations.json"
  if not annotations_path.exists():
    return 0

  annotations = load_json(annotations_path)
  group = h5_file.create_group(split)
  variable_bytes = h5py.vlen_dtype(np.dtype("uint8"))

  image_names = []
  image_blobs = []
  annotation_blobs = []
  widths = []
  heights = []

  for entry in annotations:
    image_name = entry["image_filename"]
    image_path = split_root / "images" / image_name
    if not image_path.exists():
      continue

    image_names.append(image_name)
    image_blobs.append(np.frombuffer(image_path.read_bytes(), dtype=np.uint8))
    annotation_blobs.append(json.dumps(entry, ensure_ascii=False).encode("utf-8"))

    meta = entry.get("meta", {})
    widths.append(int(meta.get("width", 0)))
    heights.append(int(meta.get("height", 0)))

  group.create_dataset("image_filenames", data=encode_text_list(image_names))
  group.create_dataset("images", data=np.array(image_blobs, dtype=object), dtype=variable_bytes)
  group.create_dataset("annotations_json", data=encode_text_list([blob.decode("utf-8") for blob in annotation_blobs]))
  group.create_dataset("widths", data=np.array(widths, dtype=np.int32))
  group.create_dataset("heights", data=np.array(heights, dtype=np.int32))
  return len(image_names)


def main():
  args = parse_args()
  dataset_root = Path(args.dataset)
  output_path = Path(args.output)
  output_path.parent.mkdir(parents=True, exist_ok=True)

  labels_path = dataset_root / "labels.json"
  labels = load_json(labels_path) if labels_path.exists() else []

  with h5py.File(output_path, "w") as h5_file:
    h5_file.attrs["dataset_root"] = str(dataset_root)
    h5_file.create_dataset("labels", data=encode_text_list(labels))

    counts = {}
    for split in ("train", "val", "test"):
      counts[split] = export_split(h5_file, dataset_root, split)

    h5_file.attrs["counts_json"] = json.dumps(counts)

  print(f"HDF5: {output_path}")
  print(json.dumps(counts, indent=2, ensure_ascii=False))


if __name__ == "__main__":
  main()
