import argparse
import json
from collections import defaultdict
from pathlib import Path


def parse_args():
  parser = argparse.ArgumentParser(description="Construit des priors de detection a partir des feedbacks hybrides.")
  parser.add_argument("--feedback-root", default="hybrid_feedback", help="Dossier racine des feedbacks.")
  parser.add_argument("--output", default="hybrid_feedback/learned_priors.json", help="JSON de sortie.")
  return parser.parse_args()


def aggregate_feedback(feedback_root):
  by_signature = defaultdict(lambda: {
    "label": None,
    "statuses": defaultdict(int),
    "decisions": defaultdict(int),
    "samples": 0,
  })

  for feedback_path in Path(feedback_root).rglob("feedback.json"):
    try:
      payload = json.loads(feedback_path.read_text(encoding="utf-8"))
    except Exception:
      continue

    for signature, entry in payload.get("legend_feedback", {}).items():
      record = by_signature[signature]
      record["label"] = entry.get("label") or record["label"]
      record["statuses"][entry.get("status") or "unknown"] += 1
      record["samples"] += 1

    for signature, entry in payload.get("group_feedback", {}).items():
      record = by_signature[signature]
      record["label"] = entry.get("label") or record["label"]
      record["decisions"][entry.get("decision") or "unknown"] += 1
      record["samples"] += 1

  return by_signature


def rule_from_record(record):
  statuses = record["statuses"]
  decisions = record["decisions"]

  if statuses.get("ignorer", 0) or decisions.get("supprimer", 0):
    return {
      "rule": "ignore",
      "ignore": True,
    }

  if statuses.get("surcompte", 0):
    return {
      "rule": "strict",
      "score_delta": 0.04,
      "shape_multiplier": 0.82,
      "color_multiplier": 0.78,
      "scale_multiplier": 0.7,
      "prefer_color_only": True,
      "allow_mono_fallback": False,
    }

  if statuses.get("manquant", 0):
    return {
      "rule": "recall",
      "score_delta": -0.05,
      "shape_multiplier": 1.18,
      "color_multiplier": 1.12,
      "scale_multiplier": 1.18,
      "prefer_color_only": False,
      "allow_mono_fallback": True,
    }

  if statuses.get("correct", 0) or decisions.get("garder", 0):
    return {
      "rule": "trusted",
      "score_delta": 0.0,
      "shape_multiplier": 1.0,
      "color_multiplier": 1.0,
      "scale_multiplier": 1.0,
      "prefer_color_only": False,
      "allow_mono_fallback": True,
    }

  return {
    "rule": "neutral",
    "score_delta": 0.0,
    "shape_multiplier": 1.0,
    "color_multiplier": 1.0,
    "scale_multiplier": 1.0,
    "prefer_color_only": False,
    "allow_mono_fallback": True,
  }


def main():
  args = parse_args()
  records = aggregate_feedback(args.feedback_root)
  priors = {}

  for signature, record in records.items():
    prior = rule_from_record(record)
    prior["label"] = record["label"]
    prior["samples"] = record["samples"]
    prior["statuses"] = dict(record["statuses"])
    prior["decisions"] = dict(record["decisions"])
    priors[signature] = prior

  output_path = Path(args.output)
  output_path.parent.mkdir(parents=True, exist_ok=True)
  payload = {
    "feedback_root": str(Path(args.feedback_root)),
    "count": len(priors),
    "by_signature": priors,
  }
  output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
  print(f"Priors: {output_path}")
  print(f"Signatures: {len(priors)}")


if __name__ == "__main__":
  main()
