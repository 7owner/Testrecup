import argparse
import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset


def parse_args():
  parser = argparse.ArgumentParser(
    description="Entraine un premier classifieur de symboles a partir du dataset JSON."
  )
  parser.add_argument("--dataset", default="datasets/plans")
  parser.add_argument("--output", default="models/symbol_classifier.pt")
  parser.add_argument("--run-dir", default="training_runs/latest")
  parser.add_argument("--epochs", type=int, default=12)
  parser.add_argument("--batch-size", type=int, default=32)
  parser.add_argument("--lr", type=float, default=0.001)
  parser.add_argument("--image-size", type=int, default=64)
  parser.add_argument("--min-samples-per-class", type=int, default=1)
  return parser.parse_args()


def load_json(path):
  return json.loads(Path(path).read_text(encoding="utf-8"))


def safe_crop(image, box):
  width, height = image.size
  x1, y1, x2, y2 = box
  x1 = max(int(round(x1)), 0)
  y1 = max(int(round(y1)), 0)
  x2 = min(int(round(x2)), width)
  y2 = min(int(round(y2)), height)
  if x2 <= x1 or y2 <= y1:
    return None
  return image.crop((x1, y1, x2, y2))


def collect_split_samples(dataset_root, split):
  split_root = Path(dataset_root) / split
  annotations_path = split_root / "annotations.json"
  if not annotations_path.exists():
    return []

  annotations = load_json(annotations_path)
  samples = []
  for entry in annotations:
    image_path = split_root / "images" / entry["image_filename"]
    if not image_path.exists():
      continue
    for obj in entry.get("objects", []):
      samples.append(
        {
          "image_path": str(image_path),
          "label": obj["label"],
          "box": obj["box"],
        }
      )
  return samples


def filter_classes(train_samples, val_samples, min_samples_per_class):
  counts = {}
  for sample in train_samples:
    counts[sample["label"]] = counts.get(sample["label"], 0) + 1

  allowed = {label for label, count in counts.items() if count >= min_samples_per_class}
  train_filtered = [sample for sample in train_samples if sample["label"] in allowed]
  val_filtered = [sample for sample in val_samples if sample["label"] in allowed]
  labels = sorted(allowed)
  return train_filtered, val_filtered, labels


class SymbolCropDataset(Dataset):
  def __init__(self, samples, label_to_index, image_size):
    self.samples = []
    self.label_to_index = label_to_index
    self.image_size = image_size
    self._build_samples(samples)

  def __len__(self):
    return len(self.samples)

  def _build_samples(self, raw_samples):
    for sample in raw_samples:
      with Image.open(sample["image_path"]).convert("RGB") as image:
        crop = safe_crop(image, sample["box"])
        if crop is None:
          crop = Image.new("RGB", (self.image_size, self.image_size), color=(255, 255, 255))
        crop = crop.resize((self.image_size, self.image_size))
        array = np.asarray(crop, dtype=np.float32) / 255.0
      tensor = torch.from_numpy(array).permute(2, 0, 1)
      label = torch.tensor(self.label_to_index[sample["label"]], dtype=torch.long)
      self.samples.append((tensor, label))

  def __getitem__(self, index):
    return self.samples[index]


class SimpleSymbolClassifier(nn.Module):
  def __init__(self, num_classes):
    super().__init__()
    self.features = nn.Sequential(
      nn.Conv2d(3, 16, kernel_size=3, padding=1),
      nn.ReLU(),
      nn.MaxPool2d(2),
      nn.Conv2d(16, 32, kernel_size=3, padding=1),
      nn.ReLU(),
      nn.MaxPool2d(2),
      nn.Conv2d(32, 64, kernel_size=3, padding=1),
      nn.ReLU(),
      nn.MaxPool2d(2),
      nn.Conv2d(64, 96, kernel_size=3, padding=1),
      nn.ReLU(),
      nn.AdaptiveAvgPool2d((1, 1)),
    )
    self.classifier = nn.Sequential(
      nn.Flatten(),
      nn.Linear(96, 128),
      nn.ReLU(),
      nn.Dropout(0.2),
      nn.Linear(128, num_classes),
    )

  def forward(self, x):
    return self.classifier(self.features(x))


def init_confusion(num_classes):
  return [[0 for _ in range(num_classes)] for _ in range(num_classes)]


def update_confusion(confusion, targets, predictions):
  for target, prediction in zip(targets, predictions):
    confusion[target][prediction] += 1


def compute_metrics(confusion, labels):
  num_classes = len(labels)
  total = sum(sum(row) for row in confusion)
  correct = sum(confusion[i][i] for i in range(num_classes))
  accuracy = correct / total if total else 0.0

  precisions = []
  recalls = []
  f1s = []
  metrics = {"accuracy": accuracy}

  for index, label in enumerate(labels):
    tp = confusion[index][index]
    fp = sum(confusion[row][index] for row in range(num_classes) if row != index)
    fn = sum(confusion[index][col] for col in range(num_classes) if col != index)
    support = sum(confusion[index])

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    precisions.append(precision)
    recalls.append(recall)
    f1s.append(f1)
    metrics[f"symbol_accuracy/{label}"] = tp / support if support else 0.0

  metrics["precision"] = sum(precisions) / num_classes if num_classes else 0.0
  metrics["recall"] = sum(recalls) / num_classes if num_classes else 0.0
  metrics["f1"] = sum(f1s) / num_classes if num_classes else 0.0
  return metrics


def run_epoch(model, loader, criterion, optimizer, device, labels):
  training = optimizer is not None
  model.train(training)
  total_loss = 0.0
  total_batches = 0
  confusion = init_confusion(len(labels))

  with torch.set_grad_enabled(training):
    for inputs, targets in loader:
      inputs = inputs.to(device)
      targets = targets.to(device)
      outputs = model(inputs)
      loss = criterion(outputs, targets)

      if training:
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

      total_loss += loss.item()
      total_batches += 1
      predictions = outputs.argmax(dim=1)
      update_confusion(
        confusion,
        targets.detach().cpu().tolist(),
        predictions.detach().cpu().tolist(),
      )

  metrics = compute_metrics(confusion, labels)
  metrics["loss"] = total_loss / total_batches if total_batches else 0.0
  return metrics


def append_metrics(metrics_path, row):
  with metrics_path.open("a", encoding="utf-8") as file:
    file.write(json.dumps(row, ensure_ascii=False) + "\n")


def save_checkpoint(output_path, model, labels, image_size):
  output_path.parent.mkdir(parents=True, exist_ok=True)
  torch.save(
    {
      "state_dict": model.state_dict(),
      "labels": labels,
      "image_size": image_size,
    },
    output_path,
  )


def main():
  args = parse_args()
  dataset_root = Path(args.dataset)
  run_dir = Path(args.run_dir)
  run_dir.mkdir(parents=True, exist_ok=True)
  metrics_path = run_dir / "metrics.jsonl"
  if metrics_path.exists():
    metrics_path.unlink()

  train_samples = collect_split_samples(dataset_root, "train")
  val_samples = collect_split_samples(dataset_root, "val")
  train_samples, val_samples, labels = filter_classes(train_samples, val_samples, args.min_samples_per_class)

  if not train_samples:
    raise SystemExit("Aucun sample d'entrainement exploitable dans datasets/plans/train/annotations.json")
  if len(labels) < 2:
    raise SystemExit("Il faut au moins 2 classes pour ce premier entrainement.")

  label_to_index = {label: index for index, label in enumerate(labels)}
  train_dataset = SymbolCropDataset(train_samples, label_to_index, args.image_size)
  val_dataset = SymbolCropDataset(val_samples, label_to_index, args.image_size)

  train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)
  val_loader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False) if val_dataset else None

  device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
  model = SimpleSymbolClassifier(num_classes=len(labels)).to(device)
  criterion = nn.CrossEntropyLoss()
  optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

  best_val_accuracy = -1.0
  best_state = None

  for epoch in range(1, args.epochs + 1):
    train_metrics = run_epoch(model, train_loader, criterion, optimizer, device, labels)
    train_row = {"epoch": epoch, "split": "train", **train_metrics}
    append_metrics(metrics_path, train_row)
    print(json.dumps(train_row, ensure_ascii=False))

    if val_loader is not None and len(val_dataset) > 0:
      val_metrics = run_epoch(model, val_loader, criterion, None, device, labels)
      val_row = {"epoch": epoch, "split": "val", **val_metrics}
      append_metrics(metrics_path, val_row)
      print(json.dumps(val_row, ensure_ascii=False))
      if val_metrics["accuracy"] > best_val_accuracy:
        best_val_accuracy = val_metrics["accuracy"]
        best_state = {key: value.cpu() for key, value in model.state_dict().items()}

  if best_state is not None:
    model.load_state_dict(best_state)

  save_checkpoint(Path(args.output), model, labels, args.image_size)

  info = {
    "model": str(args.output),
    "run_dir": str(run_dir),
    "num_classes": len(labels),
    "labels": labels,
    "train_samples": len(train_dataset),
    "val_samples": len(val_dataset),
    "metrics": str(metrics_path),
  }
  (run_dir / "run_info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
  print(json.dumps(info, indent=2, ensure_ascii=False))


if __name__ == "__main__":
  main()
