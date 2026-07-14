import argparse

from .common import load_json, save_json


def parse_args():
  parser = argparse.ArgumentParser(
    description="Injecte ou remplace les categories d'un annotations.json COCO."
  )
  parser.add_argument("--annotations", required=True, help="Chemin vers annotations.json.")
  parser.add_argument("--categories-json", required=True, help="Chemin vers le template des categories.")
  return parser.parse_args()


def main():
  args = parse_args()
  annotations = load_json(args.annotations)
  categories_payload = load_json(args.categories_json)
  categories = categories_payload.get("categories", categories_payload if isinstance(categories_payload, list) else [])
  if not categories:
    raise SystemExit("Aucune categorie exploitable dans le fichier fourni.")
  annotations["categories"] = categories
  save_json(args.annotations, annotations)
  print(f"{len(categories)} categories injectees dans {args.annotations}")


if __name__ == "__main__":
  main()
