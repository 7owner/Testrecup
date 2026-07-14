import argparse
import subprocess
from pathlib import Path


def parse_args():
  parser = argparse.ArgumentParser(
    description="Convertit toutes les sessions d'un workspace d'annotation vers un dataset JSON."
  )
  parser.add_argument(
    "--workspace",
    default="prepared_data/annotation_workspace",
    help="Workspace prepare par prepare_annotation_workspace.py",
  )
  parser.add_argument("--dataset", default="datasets/plans", help="Dossier dataset cible.")
  parser.add_argument("--box-size", type=int, default=24, help="Taille des boites autour des points.")
  parser.add_argument(
    "--python",
    default="C:\\Users\\takot\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
    help="Executable Python a utiliser.",
  )
  return parser.parse_args()


def main():
  args = parse_args()
  workspace = Path(args.workspace)
  script = Path("export_session_to_dataset.py")

  converted = 0
  for split in ("train", "val", "test"):
    sessions_dir = workspace / split / "sessions"
    images_dir = workspace / split / "images"
    if not sessions_dir.exists() or not images_dir.exists():
      continue

    for session_path in sorted(sessions_dir.glob("*.json")):
      image_name = session_path.stem
      image_path = images_dir / f"{image_name}.png"
      if not image_path.exists():
        print(f"Image manquante pour {session_path}")
        continue

      command = [
        args.python,
        str(script),
        "--session",
        str(session_path),
        "--image",
        str(image_path),
        "--dataset",
        args.dataset,
        "--split",
        split,
        "--box-size",
        str(args.box_size),
      ]
      subprocess.run(command, check=True)
      converted += 1

  print(f"Sessions converties: {converted}")


if __name__ == "__main__":
  main()
