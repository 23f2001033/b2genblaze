"""Seed showcase campaigns so the Library and Register are populated for judges.

Runs real campaigns and writes them to the B2-backed run index.
Run:  .venv/Scripts/python.exe scripts/seed_showcase.py
"""

from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "api"))

from app import store  # noqa: E402
from app.campaign import run_campaign  # noqa: E402
from app.models import BrandKit, CampaignRequest  # noqa: E402

SHOWCASE = [
    CampaignRequest(
        brief="Launch a matte steel insulated water bottle for weekend hikers.",
        brand=BrandKit(
            name="Northwind",
            tone="calm, precise, outdoorsy",
            visual_rules=["natural daylight", "no visible text or logos", "matte surfaces"],
            banned_claims=["guaranteed", "unbreakable", "lasts forever"],
            required_disclosure="Contains AI-generated imagery.",
        ),
        scene_count=2, formats=["1:1"], make_video=True, tenant_id="demo",
    ),
    CampaignRequest(
        brief="Promote a single-origin cold brew for early-morning commuters.",
        brand=BrandKit(
            name="Halcyon Coffee",
            tone="warm, unhurried, a little wry",
            visual_rules=["soft morning light", "shallow depth of field", "no text in image"],
            banned_claims=["healthiest", "cures fatigue", "guaranteed energy"],
            required_disclosure="Contains AI-generated imagery.",
        ),
        scene_count=2, formats=["9:16"], make_video=True, tenant_id="demo",
    ),
    CampaignRequest(
        brief="Introduce a linen weekender bag made from deadstock fabric.",
        brand=BrandKit(
            name="Corso",
            tone="understated, tactile, confident",
            visual_rules=["editorial styling", "neutral palette", "no visible branding"],
            banned_claims=["eco-friendly", "zero impact", "guaranteed"],
            required_disclosure="Contains AI-generated imagery.",
        ),
        scene_count=1, formats=["16:9"], make_video=True, tenant_id="demo",
    ),
]


def main() -> int:
    ok = 0
    for i, req in enumerate(SHOWCASE, 1):
        t = time.time()
        print(f"\n[{i}/{len(SHOWCASE)}] {req.brand.name} — {req.formats[0]}")
        result = run_campaign(
            req, lambda e, **d: print(f"    {e:18} {str(d)[:88]}")
        )
        if result.status == "succeeded":
            store.save_run(result)
            ok += 1
            print(f"    -> OK {result.campaign_title!r} "
                  f"{len(result.assets)} assets in {time.time()-t:.0f}s")
        else:
            print(f"    -> FAILED: {result.error}")

    print(f"\nseeded {ok}/{len(SHOWCASE)} showcase runs")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
