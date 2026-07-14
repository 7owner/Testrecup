import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def parse_args():
  parser = argparse.ArgumentParser(
    description="Genere les courbes de metriques d'entrainement a partir d'un metrics.jsonl."
  )
  parser.add_argument("--metrics", required=True, help="Fichier metrics.jsonl.")
  parser.add_argument("--output", default="training_runs/latest", help="Dossier de sortie des graphes.")
  return parser.parse_args()


def load_metrics(path):
  rows = []
  for line in Path(path).read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
      continue
    rows.append(json.loads(line))
  return rows


def series(rows, split, metric):
  xs = []
  ys = []
  for row in rows:
    if row.get("split") != split:
      continue
    if metric not in row:
      continue
    xs.append(row.get("epoch", row.get("step", len(xs))))
    ys.append(row[metric])
  return xs, ys


def plot_two_splits(rows, metric, output_path, title):
  plt.figure(figsize=(8, 4.5))
  plotted = False
  for split, color in (("train", "#1f77b4"), ("val", "#d62728")):
    xs, ys = series(rows, split, metric)
    if xs:
      plt.plot(xs, ys, marker="o", linewidth=1.8, markersize=3.5, label=split, color=color)
      plotted = True

  if not plotted:
    plt.close()
    return False

  plt.title(title)
  plt.xlabel("epoch")
  plt.ylabel(metric)
  plt.grid(True, alpha=0.25)
  plt.legend()
  plt.tight_layout()
  plt.savefig(output_path, dpi=160)
  plt.close()
  return True


def export_summary(rows, output_dir):
  summary = {
    "best_val_loss": None,
    "best_val_accuracy": None,
    "best_val_symbol_accuracy": {},
  }

  for row in rows:
    if row.get("split") != "val":
      continue
    if "loss" in row and (summary["best_val_loss"] is None or row["loss"] < summary["best_val_loss"]):
      summary["best_val_loss"] = row["loss"]
    if "accuracy" in row and (summary["best_val_accuracy"] is None or row["accuracy"] > summary["best_val_accuracy"]):
      summary["best_val_accuracy"] = row["accuracy"]
    for key, value in row.items():
      if key.startswith("symbol_accuracy/"):
        label = key.split("/", 1)[1]
        previous = summary["best_val_symbol_accuracy"].get(label)
        if previous is None or value > previous:
          summary["best_val_symbol_accuracy"][label] = value

  summary_path = output_dir / "summary.json"
  summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
  return summary_path


def main():
  args = parse_args()
  rows = load_metrics(args.metrics)
  output_dir = Path(args.output)
  output_dir.mkdir(parents=True, exist_ok=True)

  generated = []
  for metric, filename, title in (
    ("loss", "loss_curve.png", "Loss"),
    ("accuracy", "accuracy_curve.png", "Accuracy"),
    ("precision", "precision_curve.png", "Precision"),
    ("recall", "recall_curve.png", "Recall"),
    ("f1", "f1_curve.png", "F1"),
  ):
    path = output_dir / filename
    if plot_two_splits(rows, metric, path, title):
      generated.append(str(path))

  summary_path = export_summary(rows, output_dir)
  print("Graphes generes:")
  for path in generated:
    print(path)
  print(f"Resume: {summary_path}")


if __name__ == "__main__":
  main()
