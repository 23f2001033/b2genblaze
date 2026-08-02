"""Runtime configuration. Single source of truth for env-derived settings."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Repo root = .../Gen Media  (services/api/app/config.py -> up 4)
REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env")


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- storage ---
    b2_bucket: str = os.environ.get("B2_BUCKET", "")
    b2_region: str = os.environ.get("B2_REGION", "us-east-005")
    b2_key_id: str = os.environ.get("B2_KEY_ID", "")
    b2_app_key: str = os.environ.get("B2_APP_KEY", "")

    # Prefixes inside the bucket.
    prefix_runs: str = "runs"
    prefix_brand: str = "brandkits"
    prefix_attest: str = "attest"

    # Object Lock retention for attestation manifests (EU AI Act evidence).
    attest_retention_days: int = int(os.environ.get("ATTEST_RETENTION_DAYS", "365"))

    # --- providers ---
    featherless_key: str = os.environ.get("FEATHERLESS_API_KEY", "")
    featherless_base: str = "https://api.featherless.ai/v1"
    featherless_model: str = os.environ.get("FEATHERLESS_MODEL", "deepseek-ai/DeepSeek-V3.2")

    nvidia_key: str = os.environ.get("NVIDIA_API_KEY", "")
    image_model: str = os.environ.get("IMAGE_MODEL", "black-forest-labs/flux.1-dev")
    vision_model: str = os.environ.get("VISION_MODEL", "nvidia/nemotron-nano-12b-v2-vl")

    gemini_key: str = os.environ.get("GEMINI_API_KEY", "")
    gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    elevenlabs_key: str = os.environ.get("ELEVENLABS_API_KEY", "")
    tts_model: str = os.environ.get("TTS_MODEL", "eleven_flash_v2_5")
    tts_voice_id: str = os.environ.get("TTS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")

    # --- behavior ---
    demo_mode: bool = _flag("DEMO_MODE", False)
    # Free-tier hosts give ~0.1 vCPU, where a 1080p x264 encode is painfully
    # slow. LOW_RESOURCE shrinks the composed video and uses the fastest
    # preset; set it on constrained deploys, leave it off locally.
    low_resource: bool = _flag("LOW_RESOURCE", False)
    video_seconds_per_scene: float = float(os.environ.get("VIDEO_SECONDS_PER_SCENE", "4"))
    max_judge_iterations: int = int(os.environ.get("MAX_JUDGE_ITERATIONS", "3"))
    judge_pass_score: float = float(os.environ.get("JUDGE_PASS_SCORE", "0.75"))
    step_timeout: int = int(os.environ.get("STEP_TIMEOUT", "240"))
    signed_url_ttl: int = int(os.environ.get("SIGNED_URL_TTL", "3600"))

    # Provider scratch space. MUST live under the system temp dir: genblaze's
    # asset-transfer layer allowlists only temp roots for file:// reads, and
    # ObjectStorageSink has no way to widen that allowlist (it never forwards
    # allowed_roots to AssetTransfer). Anything written elsewhere fails to
    # upload with "outside allowed directories". Ephemeral scratch is also the
    # right shape for a container.
    work_dir: Path = field(
        default_factory=lambda: Path(tempfile.gettempdir()) / "hallmark"
    )

    # --- capability flags, derived ---
    @property
    def has_storage(self) -> bool:
        return bool(self.b2_bucket and self.b2_key_id and self.b2_app_key)

    @property
    def has_planner(self) -> bool:
        return bool(self.featherless_key)

    @property
    def has_image(self) -> bool:
        return bool(self.nvidia_key)

    @property
    def has_vision_judge(self) -> bool:
        return bool(self.nvidia_key)

    @property
    def has_tts(self) -> bool:
        return bool(self.elevenlabs_key)

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_key)

    def capability_report(self) -> dict[str, object]:
        """Surfaced at /healthz so the deployed app self-reports what it can do."""
        return {
            "storage_b2": self.has_storage,
            "planner_featherless": self.has_planner,
            "image_nvidia": self.has_image,
            "vision_judge": self.has_vision_judge,
            "tts_elevenlabs": self.has_tts,
            "image_fallback_gemini": self.has_gemini,
            "demo_mode": self.demo_mode,
            "bucket": self.b2_bucket or None,
            "region": self.b2_region,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.work_dir.mkdir(parents=True, exist_ok=True)
    return s
