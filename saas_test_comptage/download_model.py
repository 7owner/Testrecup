from pathlib import Path

from huggingface_hub import snapshot_download


MODEL_ID = "google/owlv2-base-patch16-ensemble"
MODEL_DIR = Path("models/owlv2-base-patch16-ensemble")


def main():
  MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
  path = snapshot_download(
    repo_id=MODEL_ID,
    local_dir=str(MODEL_DIR),
    local_dir_use_symlinks=False,
    allow_patterns=[
      "*.json",
      "*.txt",
      "*.safetensors",
      "merges.txt",
      "vocab.json",
      "preprocessor_config.json",
      "tokenizer.json",
      "tokenizer_config.json",
    ],
    ignore_patterns=[
      "*.bin",
      "*.h5",
      "*.msgpack",
      "*.ot",
    ],
  )
  print(f"Modele telecharge dans: {path}")


if __name__ == "__main__":
  main()
