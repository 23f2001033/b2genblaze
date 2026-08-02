"""Campaign orchestration — sequences the Genblaze stages and emits progress.

Keeps SDK calls in pipelines.py; this module owns flow control, parallelism,
degradation, and the shape of the result the API returns.
"""

from __future__ import annotations

import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from genblaze_core import Asset, KeyStrategy, ObjectLockConfig, Pipeline

from .config import Settings, get_settings
from .models import AssetOut, CampaignRequest, RunOut, Verdict
from .pipelines import (
    build_backend,
    build_sink,
    compose_video,
    embed_manifest,
    fetch_bytes,
    generate_scene,
    judge_copy,
    last_ffmpeg_error,
    overlay_disclosure_image,
    plan_campaign,
    synthesize_voiceover,
)

Emit = Callable[..., None]


def _noop(*_a: Any, **_k: Any) -> None:
    return None


def run_campaign(req: CampaignRequest, emit: Emit | None = None) -> RunOut:
    emit = emit or _noop
    s = get_settings()
    run_id = uuid.uuid4().hex[:12]
    started = datetime.now(timezone.utc)

    out = RunOut(
        run_id=run_id,
        status="running",
        created_at=started,
        brand_name=req.brand.name,
        tenant_id=req.tenant_id,
    )

    try:
        backend = build_backend(s)
        sink = build_sink(
            backend, prefix="hallmark", key_strategy=KeyStrategy.HIERARCHICAL,
            lock_days=s.attest_retention_days,
        )
    except Exception as exc:  # noqa: BLE001
        out.status, out.error = "failed", f"storage unavailable: {exc}"
        emit("run.failed", error=out.error)
        return out

    work = s.work_dir
    work.mkdir(parents=True, exist_ok=True)
    pool = ThreadPoolExecutor(max_workers=4)

    try:
        emit("run.started", run_id=run_id, brand=req.brand.name)

        # ---------------- A. plan ----------------
        planning_with = "demo-plan" if (s.demo_mode or not s.has_planner) else s.featherless_model
        emit("plan.started", model=planning_with)
        spec, plan_result = plan_campaign(
            req.brief, req.brand, req.scene_count,
            sink=sink, tenant_id=req.tenant_id, s=s,
        )
        out.campaign_title = spec.campaign_title
        out.lineage.append(plan_result.run.run_id)
        emit("plan.completed", title=spec.campaign_title, audience=spec.audience,
             scenes=[{"headline": x.headline, "voiceover": x.voiceover} for x in spec.scenes])

        # Copy judge runs alongside image generation — it gates nothing upstream.
        copy_future = pool.submit(judge_copy, spec, req.brand, s)

        # ---------------- B. keyframes ----------------
        deliverables: list[tuple[Path, str, int, str]] = []  # (path, fmt, scene, label)
        approved_stills: list[Path] = []

        for idx, scene in enumerate(spec.scenes):
            for fmt in req.formats:
                asset, verdict, lineage, iters = generate_scene(
                    scene, req.brand, fmt,
                    backend=backend, sink=sink, tenant_id=req.tenant_id,
                    s=s, emit=emit, scene_index=idx,
                )
                out.iterations += iters
                out.lineage.extend(lineage)
                if not asset:
                    emit("scene.failed", scene=idx, fmt=fmt)
                    continue

                raw = fetch_bytes(backend, asset.url)
                if raw is None:
                    continue
                local = work / f"{run_id}-s{idx}-{fmt.replace(':', 'x')}.png"
                local.write_bytes(raw)

                # C. disclosure overlay (human-readable Art.50 marking)
                disclosed = overlay_disclosure_image(local, spec.disclosure_line, work)
                deliverables.append((disclosed, fmt, idx, scene.headline))
                if fmt == req.formats[0]:
                    approved_stills.append(disclosed)

                out.verdict = verdict
                emit("scene.completed", scene=idx, fmt=fmt,
                     score=verdict.score, iterations=iters)

        if not deliverables:
            out.status, out.error = "failed", "no approved creative was produced"
            emit("run.failed", error=out.error)
            return out

        # ---------------- D. voiceover ----------------
        voice_tracks: list[Path] = []
        if s.has_tts:
            emit("voice.started", model=s.tts_model)
            for idx, scene in enumerate(spec.scenes):
                if not scene.voiceover:
                    continue
                try:
                    track = synthesize_voiceover(
                        scene.voiceover, sink=sink, tenant_id=req.tenant_id,
                        s=s, index=idx,
                    )
                    if track:
                        voice_tracks.append(track)
                except Exception as exc:  # noqa: BLE001
                    emit("voice.failed", scene=idx, error=type(exc).__name__)
            emit("voice.completed", tracks=len(voice_tracks))

        # ---------------- E. compose video ----------------
        video_path: Path | None = None
        if req.make_video and approved_stills:
            emit("video.started", stills=len(approved_stills))
            try:
                video_path = compose_video(
                    approved_stills, voice_tracks, work / f"{run_id}-ad.mp4",
                    fmt=req.formats[0],
                )
            except Exception as exc:  # noqa: BLE001
                emit("video.failed", error=f"{type(exc).__name__}: {exc}")
            if video_path:
                emit("video.completed", ok=True, file=video_path.name)
            else:
                emit("video.failed", error=last_ffmpeg_error()[-300:] or "ffmpeg produced no clips")
            if video_path:
                deliverables.append((video_path, req.formats[0], -1, "composed ad"))

        # ---------------- copy verdict ----------------
        try:
            copy_verdict: Verdict = copy_future.result(timeout=180)
        except Exception:  # noqa: BLE001
            copy_verdict = Verdict(passed=True, score=0.0, feedback="copy judge timed out")
        emit("copy.judged", passed=copy_verdict.passed, score=copy_verdict.score,
             issues=copy_verdict.policy_issues)
        if out.verdict:
            out.verdict.policy_issues = copy_verdict.policy_issues
            out.verdict.passed = out.verdict.passed and copy_verdict.passed

        # ---------------- F. attest ----------------
        emit("attest.started", files=len(deliverables))
        ingest_assets = [
            Asset(
                url=p.as_uri(),
                media_type="video/mp4" if p.suffix == ".mp4" else "image/png",
            )
            for p, *_ in deliverables
        ]
        attest_result = Pipeline.ingest(
            assets=ingest_assets,
            source="hallmark-delivery",
            source_metadata={
                "run_id": run_id,
                "campaign": spec.campaign_title,
                "brand": req.brand.name,
                "disclosure": spec.disclosure_line,
                "regulation": "EU AI Act Article 50",
                "plan_run_id": plan_result.run.run_id,
            },
            sink=sink,
            name="hallmark-attest",
            tenant_id=req.tenant_id,
        )
        manifest = attest_result.manifest
        out.manifest_uri = str(manifest.manifest_uri or "")
        out.canonical_hash = manifest.canonical_hash
        out.verified = bool(manifest.verify())
        out.lineage.append(attest_result.run.run_id)

        # Embed the manifest INTO each delivered file (machine-readable Art.50
        # marking), then store that stamped copy under Object Lock.
        retain_until = datetime.now(timezone.utc) + timedelta(days=s.attest_retention_days)
        lock = ObjectLockConfig(retain_until=retain_until, mode="GOVERNANCE")
        out.retain_until = retain_until

        for i, (path, fmt, scene_i, label) in enumerate(deliverables):
            stamped = embed_manifest(path, manifest)
            key = f"{s.prefix_attest}/{req.tenant_id}/{run_id}/{path.name}"
            try:
                backend.put(
                    key, path.read_bytes(),
                    content_type="video/mp4" if path.suffix == ".mp4" else "image/png",
                    metadata={"run_id": run_id, "stamped": str(stamped).lower()},
                    object_lock=lock,
                )
                durable = backend.get_durable_url(key)
            except Exception as exc:  # noqa: BLE001
                emit("attest.warn", file=path.name, error=f"{type(exc).__name__}: {exc}")
                durable = ""

            if durable:
                out.assets.append(
                    AssetOut(
                        asset_id=f"{run_id}-{i}",
                        kind="video" if path.suffix == ".mp4" else "image",
                        media_type="video/mp4" if path.suffix == ".mp4" else "image/png",
                        durable_url=durable,
                        fmt=fmt,
                        label=label,
                    )
                )

        out.attest_uri = f"{s.prefix_attest}/{req.tenant_id}/{run_id}/"
        emit("attest.completed", hash=out.canonical_hash, verified=out.verified,
             retain_until=retain_until.isoformat())

        out.cost_usd = float(getattr(attest_result.run, "cost_usd", 0.0) or 0.0)
        out.status = "succeeded"
        emit("run.completed", run_id=run_id, assets=len(out.assets),
             verified=out.verified, hash=out.canonical_hash)
        return out

    except Exception as exc:  # noqa: BLE001
        out.status = "failed"
        out.error = f"{type(exc).__name__}: {exc}"
        emit("run.failed", error=out.error, trace=traceback.format_exc(limit=3))
        return out
    finally:
        pool.shutdown(wait=False)
        try:
            sink.close()
        except Exception:  # noqa: BLE001
            pass
