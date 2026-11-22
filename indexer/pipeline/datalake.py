"""Data Lake, Quarantine, Archive & Registry management (Part A2, Paper §4.2.3).

Directory layout under ``DATA_LAKE_ROOT`` (default ``/corpus`` in K8s,
or ``corpus`` locally — lives on a PersistentVolumeClaim in Kubernetes):
  <root>/datalake/registry.json            — versioned metadata + hashes + chunk_ids
  <root>/datalake/<doc_id>/<version>/<file> — active verified raw documents
  <root>/archive/<doc_id>/<version>/<file>  — archived superseded document versions
  <root>/quarantine/<run_id>/<file>         — failed verification documents (never indexed)
  <root>/reports/verification_<run_id>.json — per-run verification report
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def default_data_root() -> Path:
    return Path(os.environ.get("DATA_LAKE_ROOT", "corpus"))


class DataLakeStore:
    """Manages versioned documents, quarantine, archive, and verification reports."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else default_data_root()
        self.datalake_dir = self.root / "datalake"
        self.quarantine_dir = self.root / "quarantine"
        self.archive_dir = self.root / "archive"
        self.reports_dir = self.root / "reports"
        self.registry_path = self.datalake_dir / "registry.json"
        self._data: dict[str, Any] = {"documents": []}
        self._ensure_dirs()
        self.load()

    def _ensure_dirs(self) -> None:
        for d in (
            self.datalake_dir,
            self.quarantine_dir,
            self.archive_dir,
            self.reports_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if self.registry_path.is_file():
            try:
                loaded = json.loads(self.registry_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("documents"), list):
                    self._data = loaded
                    return self._data
            except json.JSONDecodeError:
                pass
        self._data = {"documents": []}
        return self._data

    def save(self) -> None:
        self._ensure_dirs()
        tmp = self.registry_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(self.registry_path)

    @property
    def documents(self) -> list[dict[str, Any]]:
        return self._data["documents"]

    def active_records(self) -> list[dict[str, Any]]:
        return [d for d in self.documents if d.get("status") == "active"]

    def find_record(
        self, doc_id: str, version: str | None = None, source: str | None = None
    ) -> dict[str, Any] | None:
        for rec in self.documents:
            if rec.get("doc_id") != doc_id:
                continue
            if version is not None and rec.get("version") != version:
                continue
            if source is not None and rec.get("source") != source:
                continue
            return rec
        return None

    def find_active_by_source(self, source: str) -> dict[str, Any] | None:
        for rec in self.documents:
            if rec.get("status") == "active" and rec.get("source") == source:
                return rec
        return None

    def find_active_by_doc_id(self, doc_id: str) -> dict[str, Any] | None:
        for rec in self.documents:
            if rec.get("status") == "active" and rec.get("doc_id") == doc_id:
                return rec
        return None

    def quarantine_file(self, src_path: Path, run_id: str, reason: str) -> Path:
        dest_dir = self.quarantine_dir / run_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src_path.name
        if src_path.is_file():
            shutil.copy2(src_path, dest)
        sidecar = Path(f"{src_path}.meta.json")
        if sidecar.is_file():
            shutil.copy2(sidecar, dest_dir / sidecar.name)
        manifest = dest_dir / "quarantine_reasons.jsonl"
        with manifest.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "source": src_path.name,
                        "quarantined_path": str(dest),
                        "reason": reason,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )
                + "\n"
            )
        return dest

    def store_verified(
        self,
        src_path: Path,
        doc_id: str,
        version: str,
        content_hash: str,
        chunk_ids: list[str],
        doc_embedding: list[float] | None,
        meta: dict[str, Any],
        chunk_size: int,
        chunk_overlap: int,
        embed_model: str,
    ) -> dict[str, Any]:
        dest_dir = self.datalake_dir / doc_id / version
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src_path.name
        if src_path.is_file() and src_path.resolve() != dest.resolve():
            shutil.copy2(src_path, dest)

        now = datetime.now(UTC).isoformat()
        existing = self.find_record(doc_id=doc_id, version=version, source=src_path.name)
        record = {
            "doc_id": doc_id,
            "source": str(meta.get("source") or src_path.name),
            "title": str(meta.get("title") or src_path.name),
            "version": version,
            "date": meta.get("date"),
            "page_count": int(meta.get("page_count") or 1),
            "content_hash": content_hash,
            "chunk_ids": list(chunk_ids),
            "chunk_count": len(chunk_ids),
            "doc_embedding": doc_embedding,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "embed_model": embed_model,
            "datalake_path": str(dest),
            "archive_path": None,
            "status": "active",
            "superseded": False,
            "updated_at": now,
        }
        if existing is not None:
            existing.update(record)
            return existing
        self.documents.append(record)
        return record

    def archive_version(self, doc_id: str, version: str, superseded_by: str) -> dict[str, Any] | None:
        rec = self.find_record(doc_id=doc_id, version=version)
        if rec is None:
            return None
        arch_dir = self.archive_dir / doc_id / version
        arch_dir.mkdir(parents=True, exist_ok=True)
        src = Path(rec["datalake_path"]) if rec.get("datalake_path") else None
        arch_path = arch_dir / (src.name if src else rec["source"])
        if src and src.is_file():
            shutil.copy2(src, arch_path)
        rec["archive_path"] = str(arch_path)
        rec["status"] = "archived_superseded"
        rec["superseded"] = True
        rec["superseded_by"] = superseded_by
        rec["archived_at"] = datetime.now(UTC).isoformat()
        return rec

    def restore_version(self, doc_id: str, target_version: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Restore an archived version as active and archive the current active version."""
        target = self.find_record(doc_id=doc_id, version=target_version)
        if target is None:
            raise ValueError(
                f"No record found for doc_id={doc_id!r}, version={target_version!r}"
            )
        current_active = self.find_active_by_doc_id(doc_id)
        demoted = None
        if current_active and current_active is not target:
            demoted = self.archive_version(
                doc_id=doc_id,
                version=current_active["version"],
                superseded_by=target_version,
            )

        # Restore archived file back into datalake dir if needed
        arch = Path(target["archive_path"]) if target.get("archive_path") else None
        dl_dest = self.datalake_dir / doc_id / target_version / target["source"]
        dl_dest.parent.mkdir(parents=True, exist_ok=True)
        if arch and arch.is_file() and not dl_dest.is_file():
            shutil.copy2(arch, dl_dest)
        target["datalake_path"] = str(dl_dest)
        target["status"] = "active"
        target["superseded"] = False
        target.pop("superseded_by", None)
        target["restored_at"] = datetime.now(UTC).isoformat()
        self.save()
        return target, demoted

    def mark_deleted(self, source: str) -> dict[str, Any] | None:
        rec = self.find_active_by_source(source)
        if rec is None:
            return None
        rec["status"] = "deleted"
        rec["chunk_ids"] = []
        rec["chunk_count"] = 0
        rec["deleted_at"] = datetime.now(UTC).isoformat()
        return rec

    def write_verification_report(
        self, run_id: str, report: dict[str, Any]
    ) -> tuple[Path, Path]:
        self._ensure_dirs()
        ts_path = self.reports_dir / f"verification_{run_id}.json"
        latest_path = self.reports_dir / "verification_latest.json"
        payload = json.dumps(report, indent=2)
        ts_path.write_text(payload, encoding="utf-8")
        latest_path.write_text(payload, encoding="utf-8")
        return ts_path, latest_path
