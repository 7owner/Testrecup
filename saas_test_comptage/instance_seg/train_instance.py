import argparse
import json
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from .common import ensure_dir
from .dataset import CocoInstanceDataset, collate_fn
from .modeling import build_maskrcnn_model, save_checkpoint


def parse_args():
  parser = argparse.ArgumentParser(
    description="Entraine un Mask R-CNN pour vraie segmentation d'instances sur plans."
  )
  parser.add_argument("--dataset-root", default="instance_seg/data/plans_coco")
  parser.add_argument("--output", default="models/instance_seg_maskrcnn.pt")
  parser.add_argument("--run-dir", default="training_runs/instance_seg_run_001")
  parser.add_argument("--epochs", type=int, default=20)
  parser.add_argument("--batch-size", type=int, default=2)
  parser.add_argument("--lr", type=float, default=0.0002)
  parser.add_argument("--weight-decay", type=float, default=0.0001)
  parser.add_argument("--num-workers", type=int, default=0)
  parser.add_argument("--random-hflip", type=float, default=0.5)
  parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
  return parser.parse_args()


def resolve_device(device_arg):
  if device_arg == "cpu":
    return torch.device("cpu")
  if device_arg == "cuda":
    return torch.device("cuda")
  return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def dataset_paths(dataset_root, split):
  root = Path(dataset_root) / split
  return root / "images", root / "annotations.json"


def append_metrics(metrics_path, row):
  with metrics_path.open("a", encoding="utf-8") as file:
    file.write(json.dumps(row, ensure_ascii=False) + "\n")


def mean_loss(loss_dict):
  if not loss_dict:
    return torch.tensor(0.0)
  return sum(loss_dict.values())


def run_train_epoch(model, loader, optimizer, device):
  model.train()
  losses = []
  for images, targets in loader:
    images = [image.to(device) for image in images]
    targets = [{key: value.to(device) for key, value in target.items()} for target in targets]
    loss_dict = model(images, targets)
    loss = mean_loss(loss_dict)
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    losses.append(float(loss.detach().cpu()))
  return sum(losses) / len(losses) if losses else 0.0


def run_val_epoch(model, loader, device):
  model.train()
  losses = []
  with torch.no_grad():
    for images, targets in loader:
      images = [image.to(device) for image in images]
      targets = [{key: value.to(device) for key, value in target.items()} for target in targets]
      loss_dict = model(images, targets)
      loss = mean_loss(loss_dict)
      losses.append(float(loss.detach().cpu()))
  return sum(losses) / len(losses) if losses else 0.0


def main():
  args = parse_args()
  run_dir = ensure_dir(args.run_dir)
  metrics_path = run_dir / "metrics.jsonl"
  if metrics_path.exists():
    metrics_path.unlink()

  train_images, train_annotations = dataset_paths(args.dataset_root, "train")
  val_images, val_annotations = dataset_paths(args.dataset_root, "val")

  train_dataset = CocoInstanceDataset(train_images, train_annotations, random_hflip=args.random_hflip)
  val_dataset = CocoInstanceDataset(val_images, val_annotations, random_hflip=0.0) if val_annotations.exists() else None

  if not train_dataset.categories:
    raise SystemExit("Le dataset train n'a aucune categorie COCO.")
  if len(train_dataset) == 0:
    raise SystemExit("Le dataset train est vide.")

  device = resolve_device(args.device)
  model = build_maskrcnn_model(num_classes=len(train_dataset.categories) + 1, pretrained_backbone=True).to(device)
  optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)

  train_loader = DataLoader(
    train_dataset,
    batch_size=args.batch_size,
    shuffle=True,
    num_workers=args.num_workers,
    collate_fn=collate_fn,
  )
  val_loader = DataLoader(
    val_dataset,
    batch_size=args.batch_size,
    shuffle=False,
    num_workers=args.num_workers,
    collate_fn=collate_fn,
  ) if val_dataset is not None and len(val_dataset) else None

  best_val_loss = float("inf")
  config = {
    "dataset_root": args.dataset_root,
    "epochs": args.epochs,
    "batch_size": args.batch_size,
    "lr": args.lr,
    "weight_decay": args.weight_decay,
  }

  for epoch in range(1, args.epochs + 1):
    train_loss = run_train_epoch(model, train_loader, optimizer, device)
    append_metrics(metrics_path, {"epoch": epoch, "split": "train", "loss": train_loss})

    val_loss = None
    if val_loader is not None:
      val_loss = run_val_epoch(model, val_loader, device)
      append_metrics(metrics_path, {"epoch": epoch, "split": "val", "loss": val_loss})

    latest_metrics = {"train_loss": train_loss, "val_loss": val_loss}
    save_checkpoint(run_dir / "latest.pt", model, train_dataset.categories, config, epoch=epoch, metrics=latest_metrics)

    if val_loss is not None and val_loss < best_val_loss:
      best_val_loss = val_loss
      save_checkpoint(args.output, model, train_dataset.categories, config, epoch=epoch, metrics=latest_metrics)

    print(f"Epoch {epoch}/{args.epochs} train_loss={train_loss:.4f}" + (f" val_loss={val_loss:.4f}" if val_loss is not None else ""))

  if best_val_loss == float("inf"):
    save_checkpoint(args.output, model, train_dataset.categories, config, epoch=args.epochs, metrics={"train_loss": train_loss})

  run_info = {
    "output": str(args.output),
    "best_val_loss": None if best_val_loss == float("inf") else best_val_loss,
    "categories": train_dataset.categories,
    "config": config,
  }
  (run_dir / "run_info.json").write_text(json.dumps(run_info, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
  main()
