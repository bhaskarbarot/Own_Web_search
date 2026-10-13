"""Local file ingestion (any supported type) through the shared pipeline."""
from pathlib import Path

from .pipeline import Processor
from .util import utc_now

MAX_FILE_BYTES = 200 * 1024 * 1024
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".cache", ".tox"}


def _sidecar_text(path):
    """Optional same-name .txt next to an image provides a description."""
    side = path.with_suffix(".txt")
    if path.suffix.lower() in IMAGE_EXTS and side.exists():
        return side.read_text(encoding="utf-8", errors="replace")
    return ""


def ingest_file(path, engine, processor=None):
    path = Path(path)
    if not path.is_file():
        raise ValueError("Not a file")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(f"File too large ({size} bytes)")
    processor = processor or Processor(engine.settings, engine.store, None)
    url = path.resolve().as_uri()
    data = path.read_bytes()
    out = processor.process(url, url, 200, {}, data, fetched_at=utc_now(), enqueue=False)
    side = _sidecar_text(path)
    if side and out.get("doc_id"):
        doc = engine.store.get(out["doc_id"])
        engine.store.upsert(url, doc["title"], doc["text"] + "\n" + side, source_type=doc["source_type"],
                            metadata=doc["metadata"], extraction_status=doc["extraction_status"] + "+sidecar")
    return {"path": str(path), "id": out.get("doc_id"), "result": out.get("result"), "kind": out.get("kind"),
            "status": out.get("extraction_status")}


def ingest_path(path, engine, log=None):
    path = Path(path)
    processor = Processor(engine.settings, engine.store, None)
    files = [path] if path.is_file() else (
        [p for p in sorted(path.rglob("*")) if p.is_file() and not (set(p.parts) & SKIP_DIRS)] if path.is_dir() else None)
    if files is None:
        raise ValueError(f"Path not found: {path}")
    results = []
    for fp in files:
        if fp.suffix.lower() == ".txt" and any(fp.with_suffix(ext).exists() for ext in IMAGE_EXTS):
            continue                                    # sidecar of an image: merged into the image doc
        try:
            r = ingest_file(fp, engine, processor)
        except Exception as e:
            r = {"path": str(fp), "error": str(e)[:300]}
        results.append(r)
        if log:
            log(f"[ingest] {r.get('result', 'error'):8} {r.get('kind', '')!s:7} {fp}")
    engine.rebuild_index()
    return results
