"""Run index + read paths on top of B2.

B2 is the system of record: run records live in the bucket as JSON, so the
library and the disclosure register survive restarts and redeploys with no
separate database.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

from .config import Settings, get_settings
from .models import RunOut

_lock = threading.Lock()
_cache: dict[str, RunOut] = {}
_backend = None


def backend():
    """Lazily built, process-wide. The S3 client is thread-safe for our use."""
    global _backend
    if _backend is None:
        from .pipelines import build_backend

        _backend = build_backend()
    return _backend


def _index_key(s: Settings, tenant: str, run_id: str) -> str:
    return f"index/{tenant}/{run_id}.json"


# --------------------------------------------------------------------------
# Write
# --------------------------------------------------------------------------
def save_run(run: RunOut) -> None:
    s = get_settings()
    with _lock:
        _cache[run.run_id] = run
    try:
        backend().put(
            _index_key(s, run.tenant_id, run.run_id),
            run.model_dump_json(indent=2).encode("utf-8"),
            content_type="application/json",
        )
    except Exception:  # noqa: BLE001
        # The in-memory copy still serves this process; losing the index
        # write must never fail a completed campaign.
        pass


# --------------------------------------------------------------------------
# Read
# --------------------------------------------------------------------------
def get_run(run_id: str) -> RunOut | None:
    with _lock:
        if run_id in _cache:
            return _cache[run_id]
    for run in list_runs():
        if run.run_id == run_id:
            return run
    return None


def list_runs(tenant: str | None = None, limit: int = 60) -> list[RunOut]:
    s = get_settings()
    prefix = f"index/{tenant}/" if tenant else "index/"
    runs: dict[str, RunOut] = {}

    try:
        page = backend().list(prefix=prefix)
        entries = getattr(page, "entries", None) or getattr(page, "files", None) or []
        for entry in entries[: limit * 2]:
            key = getattr(entry, "key", None) or getattr(entry, "name", None)
            if not key or not key.endswith(".json"):
                continue
            try:
                raw = backend().get(key)
                if isinstance(raw, tuple):
                    raw = raw[0]
                run = RunOut.model_validate(json.loads(raw))
                runs[run.run_id] = run
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass

    with _lock:
        for run_id, run in _cache.items():
            runs.setdefault(run_id, run)

    ordered = sorted(runs.values(), key=lambda r: r.created_at, reverse=True)
    return ordered[:limit]


# --------------------------------------------------------------------------
# Asset delivery — private bucket, short-lived signed URLs
# --------------------------------------------------------------------------
def sign(durable_url: str, ttl: int | None = None) -> str | None:
    """Durable (manifest) URL -> short-lived presigned URL for the browser.

    Manifests keep credential-free durable URLs so provenance never decays;
    delivery uses SigV4 URLs minted on demand. Assets are never public.
    """
    s = get_settings()
    key = backend().key_from_url(durable_url)
    if not key:
        return None
    return backend().presigned_get_url(key, expires_in=ttl or s.signed_url_ttl)


# --------------------------------------------------------------------------
# EU AI Act Article 50 disclosure register
# --------------------------------------------------------------------------
REGISTER_COLUMNS = [
    "run_id", "created_at", "tenant_id", "brand", "campaign",
    "asset_id", "asset_kind", "format", "media_type",
    "manifest_hash", "verified", "retain_until", "storage_uri",
]


def register_rows(tenant: str | None = None) -> list[dict[str, Any]]:
    """One row per delivered asset — the evidence pack a compliance officer asks for."""
    rows: list[dict[str, Any]] = []
    for run in list_runs(tenant):
        if run.status != "succeeded":
            continue
        for asset in run.assets:
            rows.append(
                {
                    "run_id": run.run_id,
                    "created_at": run.created_at.isoformat(),
                    "tenant_id": run.tenant_id,
                    "brand": run.brand_name,
                    "campaign": run.campaign_title,
                    "asset_id": asset.asset_id,
                    "asset_kind": asset.kind,
                    "format": asset.fmt or "",
                    "media_type": asset.media_type,
                    "manifest_hash": run.canonical_hash or "",
                    "verified": str(bool(run.verified)).lower(),
                    "retain_until": run.retain_until.isoformat() if run.retain_until else "",
                    "storage_uri": asset.durable_url,
                }
            )
    return rows


def register_csv(tenant: str | None = None) -> str:
    import csv
    import io

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=REGISTER_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in register_rows(tenant):
        writer.writerow(row)
    return buf.getvalue()


def register_meta(tenant: str | None = None) -> dict[str, Any]:
    rows = register_rows(tenant)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "regulation": "EU AI Act Article 50 — transparency obligations (applicable 2 Aug 2026)",
        "total_assets": len(rows),
        "verified_assets": sum(1 for r in rows if r["verified"] == "true"),
        "rows": rows,
    }
