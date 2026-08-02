"""Hallmark API — governed AI creative with verifiable provenance."""

from __future__ import annotations

import asyncio
import hashlib
import json
import queue
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from . import store
from .campaign import run_campaign
from .config import get_settings
from .models import CampaignRequest, RunOut, VerifyResult

app = FastAPI(title="Hallmark", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# run_id -> event queue (live progress fan-out)
_streams: dict[str, queue.Queue] = {}
_stream_lock = threading.Lock()

WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"


# ==========================================================================
# Health
# ==========================================================================
@app.get("/healthz")
def healthz() -> dict[str, Any]:
    s = get_settings()
    return {
        "ok": True,
        "service": "hallmark",
        "time": datetime.now(timezone.utc).isoformat(),
        "capabilities": s.capability_report(),
    }


# ==========================================================================
# Campaign runs
# ==========================================================================
@app.post("/api/runs")
def start_run(req: CampaignRequest) -> dict[str, str]:
    """Kick off a campaign; progress streams from /api/runs/{id}/events."""
    stream_id = uuid.uuid4().hex[:12]
    q: queue.Queue = queue.Queue(maxsize=512)
    with _stream_lock:
        _streams[stream_id] = q

    def emit(event: str, **data: Any) -> None:
        try:
            q.put_nowait({"event": event, "data": data})
        except queue.Full:
            pass

    def work() -> None:
        try:
            result = run_campaign(req, emit)
            store.save_run(result)
            emit("done", run=json.loads(result.model_dump_json()))
        except Exception as exc:  # noqa: BLE001
            emit("run.failed", error=f"{type(exc).__name__}: {exc}")
            emit("done", run=None)
        finally:
            q.put({"event": "__eof__", "data": {}})

    threading.Thread(target=work, daemon=True).start()
    return {"stream_id": stream_id}


@app.get("/api/runs/{stream_id}/events")
async def run_events(stream_id: str) -> StreamingResponse:
    with _stream_lock:
        q = _streams.get(stream_id)
    if q is None:
        raise HTTPException(404, "unknown stream")

    async def gen():
        loop = asyncio.get_running_loop()
        try:
            while True:
                try:
                    item = await loop.run_in_executor(None, q.get, True, 90)
                except Exception:  # timeout -> keepalive
                    yield ": keepalive\n\n"
                    continue
                if item["event"] == "__eof__":
                    break
                payload = json.dumps(item["data"], default=str)
                yield f"event: {item['event']}\ndata: {payload}\n\n"
        finally:
            with _stream_lock:
                _streams.pop(stream_id, None)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs")
def list_runs(tenant: str | None = None, limit: int = 60) -> list[RunOut]:
    return store.list_runs(tenant, limit)


@app.get("/api/runs/detail/{run_id}")
def run_detail(run_id: str) -> RunOut:
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(404, "unknown run")
    return run


# ==========================================================================
# Asset delivery — private bucket, signed on demand
# ==========================================================================
@app.get("/api/assets/sign")
def sign_asset(url: str = Query(..., description="durable B2 URL from a manifest")):
    signed = store.sign(url)
    if not signed:
        raise HTTPException(400, "not a recognized bucket URL")
    return {"url": signed, "expires_in": get_settings().signed_url_ttl}


# ==========================================================================
# Verification portal
# ==========================================================================
@app.post("/api/verify")
async def verify(file: UploadFile = File(...)) -> VerifyResult:
    """Drop any delivered file here: extract the embedded manifest and check it."""
    from .pipelines import extract_manifest

    raw = await file.read()
    if not raw:
        return VerifyResult(found_manifest=False, message="empty file")

    file_sha = hashlib.sha256(raw).hexdigest()
    suffix = Path(file.filename or "upload.bin").suffix or ".bin"
    tmp = Path(tempfile.gettempdir()) / f"hallmark-verify-{uuid.uuid4().hex[:10]}{suffix}"
    tmp.write_bytes(raw)

    try:
        manifest = extract_manifest(tmp)
        if manifest is None:
            return VerifyResult(
                found_manifest=False,
                file_sha256=file_sha,
                message=(
                    "No Hallmark provenance manifest found in this file. It was "
                    "either not produced by Hallmark, or the metadata was stripped "
                    "(re-encoding and some social platforms remove it)."
                ),
            )

        verified = False
        try:
            verified = bool(manifest.verify())
        except Exception:  # noqa: BLE001
            pass

        run = getattr(manifest, "run", None)
        steps = getattr(run, "steps", None) or []
        providers = sorted({str(s.provider) for s in steps if getattr(s, "provider", None)})
        models = sorted({str(s.model) for s in steps if getattr(s, "model", None)})
        assets = [a for s in steps for a in (getattr(s, "assets", None) or [])]
        asset_sha = next((a.sha256 for a in assets if getattr(a, "sha256", None)), None)

        meta = getattr(run, "metadata", None) or {}
        disclosure = meta.get("disclosure") if isinstance(meta, dict) else None

        return VerifyResult(
            found_manifest=True,
            verified=verified,
            source="embedded",
            canonical_hash=getattr(manifest, "canonical_hash", None),
            run_id=getattr(run, "run_id", None),
            pipeline=getattr(run, "name", None) or getattr(run, "pipeline", None),
            created_at=getattr(run, "created_at", None),
            providers=providers,
            models=models,
            parent_run_id=getattr(run, "parent_run_id", None),
            asset_sha256=asset_sha,
            file_sha256=file_sha,
            disclosure=disclosure,
            message=(
                "Manifest found and integrity verified."
                if verified
                else "Manifest found, but integrity verification did not pass."
            ),
        )
    finally:
        tmp.unlink(missing_ok=True)


# ==========================================================================
# EU AI Act Article 50 disclosure register
# ==========================================================================
@app.get("/api/register.json")
def register_json(tenant: str | None = None) -> dict[str, Any]:
    return store.register_meta(tenant)


@app.get("/api/register.csv")
def register_csv(tenant: str | None = None) -> PlainTextResponse:
    csv_text = store.register_csv(tenant)
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="ai-disclosure-register.csv"'},
    )


# ==========================================================================
# Static frontend (same origin — no CORS in production)
# ==========================================================================
if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "not found")
        candidate = WEB_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
else:

    @app.get("/")
    def root() -> JSONResponse:
        return JSONResponse(
            {
                "service": "hallmark",
                "note": "frontend not built; run `npm run build` in web/",
                "docs": "/docs",
                "health": "/healthz",
            }
        )
