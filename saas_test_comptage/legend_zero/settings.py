from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
RUNS_DIR = PACKAGE_DIR / "runs"
WEB_DIR = PACKAGE_DIR / "web"
UPLOADS_DIR = PACKAGE_DIR / "uploads"
HOST = "127.0.0.1"
PORT = 8870

IGNORED_SCAN_DIRS = {
  ".venv",
  "__pycache__",
  "datasets",
  "hybrid_feedback",
  "hybrid_runs",
  "legend_zero",
  "models",
  "plan_counter_ui",
  "prepared_data",
  "rendered_cci",
  "split_output",
  "tmp_detect_one",
  "tmp_legend_debug",
  "training_runs",
  "unsupervised_kmeans_lab",
}

IGNORED_LABEL_KEYWORDS = {
  "BATIMENT",
  "EXISTANT",
  "LIMITE",
  "PARCELLAIRE",
  "COUR",
  "FACADE",
  "VOIRIE",
  "ACCES",
  "CLOTURE",
  "EMPRISE",
  "ENROBES",
  "ESPACES VERTS",
}

LEGEND_ANCHOR_WORDS = {"LEGENDE", "LEGEND"}
