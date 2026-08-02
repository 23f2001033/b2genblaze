"""Full campaign orchestration test: plan -> judge -> keyframes -> disclosure
-> video -> attestation with Object Lock.

Run:  .venv/Scripts/python.exe scripts/test_campaign.py
"""

from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "api"))

from app.campaign import run_campaign  # noqa: E402
from app.models import BrandKit, CampaignRequest  # noqa: E402

REQ = CampaignRequest(
    brief="Launch a matte steel insulated water bottle for weekend hikers.",
    brand=BrandKit(
        name="Northwind Bottles",
        tone="calm, precise, outdoorsy",
        palette=["#0F3D3E", "#E8E1D9"],
        visual_rules=["natural daylight", "no visible text or logos", "matte surfaces"],
        banned_claims=["guaranteed", "unbreakable", "lasts forever"],
        required_disclosure="Contains AI-generated imagery.",
    ),
    scene_count=2,
    formats=["1:1"],
    make_video=True,
    tenant_id="smoke",
)

t0 = time.time()


def emit(evt: str, **data) -> None:
    print(f"  [{time.time()-t0:6.1f}s] {evt:20} {data}")


def main() -> int:
    out = run_campaign(REQ, emit)
    print("\n" + "=" * 68)
    print(f"status        : {out.status}")
    print(f"error         : {out.error}")
    print(f"campaign      : {out.campaign_title}")
    print(f"iterations    : {out.iterations}")
    print(f"lineage runs  : {len(out.lineage)}")
    print(f"manifest hash : {out.canonical_hash}")
    print(f"verified      : {out.verified}")
    print(f"attest prefix : {out.attest_uri}")
    print(f"retain until  : {out.retain_until}")
    print(f"assets        : {len(out.assets)}")
    for a in out.assets:
        print(f"   - {a.kind:5} {a.fmt or '':5} {a.label[:34]:34} {a.durable_url[-56:]}")
    if out.verdict:
        print(f"verdict       : passed={out.verdict.passed} score={out.verdict.score}")
        print(f"  brand issues: {out.verdict.brand_issues}")
        print(f"  policy      : {out.verdict.policy_issues}")
    print(f"total elapsed : {time.time()-t0:.1f}s")
    return 0 if out.status == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())
