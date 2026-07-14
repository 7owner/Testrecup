import json
import shutil

import fitz

from .legend_detector import choose_best_legend_page
from .pdf_utils import list_project_pdfs, parse_page_spec, resolve_repo_pdf_path, slugify
from .settings import REPO_ROOT, RUNS_DIR


def _run_dir_for_pdf(pdf_path):
  relative_key = pdf_path.relative_to(REPO_ROOT).as_posix().replace("/", "-")
  return RUNS_DIR / slugify(relative_key)


def _reset_run_dir(run_dir):
  if run_dir.exists():
    resolved = run_dir.resolve()
    runs_root = RUNS_DIR.resolve()
    if runs_root not in resolved.parents:
      raise ValueError("Refus de nettoyer un dossier hors legend_zero/runs.")
    shutil.rmtree(run_dir)
  run_dir.mkdir(parents=True, exist_ok=True)


def _relative(path):
  return path.relative_to(REPO_ROOT).as_posix()


def run_legend_extraction(pdf_relative_path, page_spec=None):
  pdf_path = resolve_repo_pdf_path(pdf_relative_path)
  run_dir = _run_dir_for_pdf(pdf_path)
  _reset_run_dir(run_dir)

  with fitz.open(pdf_path) as document:
    page_numbers = parse_page_spec(page_spec, document.page_count)
    best_page, page_summaries = choose_best_legend_page(document, page_numbers, run_dir / "pages")

  if best_page is None or best_page["entry_count"] == 0:
    raise ValueError("Aucun objet de legende exploitable detecte.")

  objects = []
  crops_dir = run_dir / "objects"
  binary_dir = run_dir / "objects_binary"
  crops_dir.mkdir(parents=True, exist_ok=True)
  binary_dir.mkdir(parents=True, exist_ok=True)
  for entry in best_page["entries"]:
    source_crop = entry["crop_path"]
    source_binary_crop = entry["binary_crop_path"]
    target_crop = crops_dir / source_crop.name
    target_binary_crop = binary_dir / source_binary_crop.name
    shutil.copy2(source_crop, target_crop)
    shutil.copy2(source_binary_crop, target_binary_crop)
    objects.append(
      {
        "id": entry["id"],
        "label": entry["label"],
        "page": entry["page"],
        "line_bbox": entry["line_bbox"],
        "symbol_bbox": entry["symbol_bbox"],
        "symbol_size": entry["symbol_size"],
        "dominant_color": entry["dominant_color"],
        "symbol_side": entry.get("symbol_side"),
        "symbol_score": entry.get("symbol_score"),
        "binary_foreground_ratio": entry.get("binary_foreground_ratio"),
        "crop_path": _relative(target_crop),
        "binary_crop_path": _relative(target_binary_crop),
      }
    )

  result = {
    "title": pdf_path.stem,
    "pdf_path": _relative(pdf_path),
    "selected_pages": page_numbers,
    "legend_page": best_page["page"],
    "legend_anchor_text": best_page.get("anchor_text"),
    "legend_object_count": len(objects),
    "preview_path": _relative(best_page["preview_path"]),
    "objects": objects,
    "page_summaries": [
      {
        "page": summary["page"],
        "entry_count": summary["entry_count"],
        "anchor_text": summary.get("anchor_text"),
        "preview_path": _relative(summary["preview_path"]),
      }
      for summary in page_summaries
    ],
  }

  result_path = run_dir / "result.json"
  result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
  return result


def export_index():
  items = []
  for result_path in sorted(RUNS_DIR.rglob("result.json")):
    try:
      data = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception:
      continue
    items.append(
      {
        "title": data.get("title"),
        "pdf_path": data.get("pdf_path"),
        "legend_page": data.get("legend_page"),
        "legend_object_count": data.get("legend_object_count", 0),
        "result_path": result_path.relative_to(REPO_ROOT).as_posix(),
      }
    )
  return items


__all__ = ["export_index", "list_project_pdfs", "run_legend_extraction"]
