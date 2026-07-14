import re
import unicodedata
from pathlib import Path

import fitz
from PIL import Image

from .settings import IGNORED_SCAN_DIRS, REPO_ROOT, UPLOADS_DIR


def normalize_text(value):
  ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
  return re.sub(r"\s+", " ", ascii_value).strip()


def slugify(value):
  cleaned = normalize_text(value).lower()
  cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
  return cleaned or "run"


def list_project_pdfs():
  pdfs = []
  seen = set()
  for pdf_path in REPO_ROOT.rglob("*.pdf"):
    relative = pdf_path.relative_to(REPO_ROOT)
    if any(part in IGNORED_SCAN_DIRS for part in relative.parts):
      continue
    key = relative.as_posix()
    seen.add(key)
    pdfs.append(
      {
        "name": pdf_path.name,
        "title": pdf_path.stem,
        "relative_path": key,
        "folder": relative.parent.as_posix(),
        "source": "repo",
      }
    )

  if UPLOADS_DIR.exists():
    for pdf_path in UPLOADS_DIR.rglob("*.pdf"):
      relative = pdf_path.relative_to(REPO_ROOT)
      key = relative.as_posix()
      if key in seen:
        continue
      pdfs.append(
        {
          "name": pdf_path.name,
          "title": pdf_path.stem,
          "relative_path": key,
          "folder": relative.parent.as_posix(),
          "source": "upload",
        }
      )
  pdfs.sort(key=lambda item: (item["folder"].lower(), item["name"].lower()))
  return pdfs


def resolve_repo_pdf_path(raw_path):
  if not raw_path:
    raise ValueError("Chemin PDF manquant.")
  candidate = (REPO_ROOT / raw_path).resolve()
  if REPO_ROOT not in candidate.parents and candidate != REPO_ROOT:
    raise ValueError("Chemin hors depot.")
  if not candidate.exists():
    raise FileNotFoundError(f"PDF introuvable: {raw_path}")
  if candidate.suffix.lower() != ".pdf":
    raise ValueError("Le fichier selectionne n'est pas un PDF.")
  return candidate


def parse_page_spec(spec, page_count):
  if not spec:
    return list(range(1, page_count + 1))
  pages = set()
  for chunk in spec.split(","):
    part = chunk.strip()
    if not part:
      continue
    if "-" in part:
      start_raw, end_raw = part.split("-", 1)
      start = max(int(start_raw), 1)
      end = min(int(end_raw), page_count)
      if start > end:
        start, end = end, start
      pages.update(range(start, end + 1))
    else:
      page_number = int(part)
      if 1 <= page_number <= page_count:
        pages.add(page_number)
  if not pages:
    raise ValueError("Specification de pages invalide.")
  return sorted(pages)


def group_words_into_lines(words):
  lines = {}
  for word in words:
    key = (word[5], word[6])
    lines.setdefault(key, []).append(word)

  grouped = []
  for items in lines.values():
    items.sort(key=lambda item: item[0])
    x0 = min(item[0] for item in items)
    y0 = min(item[1] for item in items)
    x1 = max(item[2] for item in items)
    y1 = max(item[3] for item in items)
    text = " ".join(item[4] for item in items).strip()
    grouped.append({"bbox": [x0, y0, x1, y1], "text": text})
  grouped.sort(key=lambda line: (line["bbox"][1], line["bbox"][0]))
  return grouped


def render_clip(page, rect, zoom=3.0):
  pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect, alpha=False)
  return Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)


def render_page(page, zoom=2.0):
  pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
  return Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
