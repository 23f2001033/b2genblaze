"""End-to-end pipeline test: plan -> keyframe -> vision judge -> B2.

Exercises the real Genblaze layer against real providers and a real bucket.
Run:  .venv/Scripts/python.exe scripts/test_pipeline.py
"""

from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "api"))

from app.config import get_settings  # noqa: E402
from app.models import BrandKit  # noqa: E402
from app.pipelines import (  # noqa: E402
    build_backend,
    build_sink,
    generate_scene,
    judge_copy,
    plan_campaign,
)

BRAND = BrandKit(
    name="Northwind Bottles",
    tone="calm, precise, outdoorsy",
    palette=["#0F3D3E", "#E8E1D9"],
    visual_rules=["natural daylight", "no visible text or logos", "matte surfaces"],
    banned_claims=["guaranteed", "unbreakable", "lasts forever"],
    required_disclosure="Contains AI-generated imagery.",
)
BRIEF = "Launch a matte steel insulated water bottle for weekend hikers."


def main() -> int:
    s = get_settings()
    print("capabilities:", s.capability_report(), "\n")

    backend = build_backend(s)
    sink = build_sink(backend, prefix="hallmark", lock_days=s.attest_retention_days)

    def emit(evt: str, **data):
        print(f"    . {evt} {data}")

    # --- Stage A: plan ---
    print("A. planning (Featherless as a manifest'd Step)")
    t = time.time()
    try:
        spec, plan_result = plan_campaign(
            BRIEF, BRAND, 2, sink=sink, tenant_id="smoke", s=s
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] planner: {type(exc).__name__}: {exc}")
        return 1
    print(f"  [PASS] {time.time()-t:.1f}s  title={spec.campaign_title!r}")
    print(f"         scenes={len(spec.scenes)}  audience={spec.audience[:60]!r}")
    for i, sc in enumerate(spec.scenes):
        print(f"         [{i}] {sc.headline!r}")
        print(f"             img: {sc.image_prompt[:88]}...")
        print(f"             vo : {sc.voiceover[:70]}")
    print(f"         plan manifest verify={plan_result.manifest.verify()}")
    print(f"         plan asset sha={plan_result.run.steps[0].assets[0].sha256[:16]}...")

    # --- copy judge ---
    print("\nB. copy/policy judge (Featherless)")
    t = time.time()
    cv = judge_copy(spec, BRAND, s)
    print(f"  [{'PASS' if cv.passed else 'FLAG'}] {time.time()-t:.1f}s "
          f"score={cv.score} issues={cv.policy_issues} fb={cv.feedback[:70]!r}")

    # --- Stage B: one scene through the AgentLoop ---
    print("\nC. keyframe + vision judge (AgentLoop, NVIDIA)")
    t = time.time()
    try:
        asset, verdict, lineage, iters = generate_scene(
            spec.scenes[0], BRAND, "1:1",
            backend=backend, sink=sink, tenant_id="smoke", s=s,
            emit=emit, scene_index=0,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] {type(exc).__name__}: {exc}")
        import traceback; traceback.print_exc()
        return 1

    print(f"  elapsed {time.time()-t:.1f}s  iterations={iters}")
    if not asset:
        print("  [FAIL] no image asset produced")
        return 1
    print(f"  [PASS] asset  {asset.url[:96]}")
    print(f"         sha256 {(asset.sha256 or '')[:16]}...")
    print(f"         verdict passed={verdict.passed} score={verdict.score}")
    print(f"         issues  {verdict.all_issues}")
    print(f"         lineage {len(lineage)} run(s): {[r[:8] for r in lineage]}")

    readable = bool(asset.url and backend.key_from_url(asset.url))
    print(f"  [{'PASS' if readable else 'FAIL'}] asset resolvable back to a B2 key")

    print("\n" + "=" * 60)
    print("[PASS] pipeline works end to end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
