"""B2 + Genblaze wiring smoke test — costs $0 in provider credits.

Validates the entire storage layer before any real generation happens:

  1. Credentials + region resolve (preflight HeadBucket).
  2. A pipeline run transfers an asset into B2 and hash-binds it.
  3. The manifest lands in B2 and ``verify()`` passes.
  4. durable URL -> key -> presigned URL round-trips and actually fetches bytes.
  5. Object Lock retention is applied to the manifest and reads back.

Run:  .venv/Scripts/python.exe scripts/smoke_b2.py
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from genblaze_core import (  # noqa: E402
    Asset,
    KeyStrategy,
    Modality,
    ObjectLockConfig,
    ObjectStorageSink,
    Pipeline,
)
from genblaze_core.mocks import MockProvider  # noqa: E402
from genblaze_s3 import S3StorageBackend  # noqa: E402

# 1x1 red PNG — smallest valid payload that exercises a real byte transfer.
_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

PASS, FAIL = "[PASS]", "[FAIL]"
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {PASS if ok else FAIL} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        failures.append(label)
    return ok


def main() -> int:
    bucket = os.environ.get("B2_BUCKET")
    region = os.environ.get("B2_REGION")
    print(f"\nBucket={bucket}  Region={region}\n")

    # --- 1. Backend construction (preflight HeadBucket validates creds + region) ---
    print("1. Backend / credentials")
    try:
        backend = S3StorageBackend.for_backblaze(bucket, region=region)
        check("for_backblaze() preflight", True, f"endpoint ok, region {region}")
    except Exception as exc:  # noqa: BLE001
        check("for_backblaze() preflight", False, f"{type(exc).__name__}: {exc}")
        print("\nCannot continue without a working backend.\n")
        return 1

    # --- 2. Pipeline run -> asset transferred into B2 ---
    print("\n2. Pipeline run + asset transfer")
    tmp = Path(tempfile.gettempdir()) / "genblaze_smoke.png"
    tmp.write_bytes(base64.b64decode(_PNG_B64))

    retain_until = datetime.now(timezone.utc) + timedelta(days=1)
    sink = ObjectStorageSink(
        backend,
        prefix="smoke",
        key_strategy=KeyStrategy.HIERARCHICAL,
        manifest_lock=ObjectLockConfig(retain_until=retain_until, mode="GOVERNANCE"),
    )

    provider = MockProvider(
        name="smoke-mock",
        assets=[Asset(url=tmp.as_uri(), media_type="image/png")],
        cost_usd=0.0,
    )

    try:
        result = (
            Pipeline("b2-smoke-test")
            .step(provider, model="mock-image", prompt="smoke test", modality=Modality.IMAGE)
            .run(sink=sink, timeout=120)
        )
    except Exception as exc:  # noqa: BLE001
        check("pipeline.run(sink=...)", False, f"{type(exc).__name__}: {exc}")
        return 1

    asset = result.run.steps[0].assets[0]
    check("pipeline completed", result.run.steps[0].status is not None)
    check("asset uploaded to B2", "backblazeb2.com" in asset.url, asset.url[:78])
    check("sha256 hash-bound by sink", bool(asset.sha256) and asset.sha256 != "0" * 64,
          (asset.sha256 or "")[:16] + "...")

    # --- 3. Manifest integrity ---
    print("\n3. Manifest")
    manifest = result.manifest
    check("manifest uploaded", bool(manifest.manifest_uri), str(manifest.manifest_uri or "")[:78])
    check("canonical_hash present", bool(manifest.canonical_hash),
          (manifest.canonical_hash or "")[:16] + "...")
    check("manifest.verify() is True", manifest.verify() is True)

    # --- 4. durable URL -> key -> presigned URL -> real fetch ---
    print("\n4. Private-bucket read path")
    key = backend.key_from_url(asset.url)
    check("key_from_url() inverts durable URL", key is not None, str(key))

    if key:
        signed = backend.presigned_get_url(key, expires_in=900)
        check("presigned_get_url() minted", signed.startswith("https://") and "X-Amz-" in signed)
        try:
            resp = httpx.get(signed, timeout=30, follow_redirects=True)
            check("presigned URL fetches bytes", resp.status_code == 200,
                  f"HTTP {resp.status_code}, {len(resp.content)} bytes")
            check("bytes match what we uploaded", resp.content == tmp.read_bytes())
        except Exception as exc:  # noqa: BLE001
            check("presigned URL fetches bytes", False, f"{type(exc).__name__}: {exc}")

        # The durable URL must NOT be publicly readable — bucket is private.
        try:
            bare = httpx.get(asset.url, timeout=20, follow_redirects=True)
            check("durable URL is NOT public (private bucket)", bare.status_code in (401, 403),
                  f"HTTP {bare.status_code}")
        except Exception:  # noqa: BLE001
            check("durable URL is NOT public (private bucket)", True, "request refused")

    # --- 5. Object Lock retention on the manifest ---
    print("\n5. Object Lock (WORM) on manifest")
    m_key = backend.key_from_url(str(manifest.manifest_uri)) if manifest.manifest_uri else None
    if m_key:
        try:
            raw = backend._client.get_object_retention(Bucket=backend._bucket, Key=m_key)
            mode = raw.get("Retention", {}).get("Mode")
            until = raw.get("Retention", {}).get("RetainUntilDate")
            check("manifest carries Object Lock retention", mode == "GOVERNANCE", f"{mode} until {until}")
        except Exception as exc:  # noqa: BLE001
            check("manifest carries Object Lock retention", False, f"{type(exc).__name__}: {exc}")
    else:
        check("manifest key resolved for retention check", False)

    print("\n" + "=" * 62)
    if failures:
        print(f"{FAIL} {len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print(f"{PASS} All checks passed — B2 + Genblaze wiring is good.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
