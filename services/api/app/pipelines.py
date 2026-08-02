"""The Genblaze layer. ALL SDK usage is confined to this module.

Everything else in the app talks to plain domain models, so the orchestration
boundary stays inspectable (and testable) in one place.

Pipeline shape:

    A  plan        Featherless DeepSeek-V3.2, wrapped in a SyncProvider so the
                   LLM call is a first-class manifest'd Step (not a side call).
    B  keyframes   NVIDIA flux.1-dev, one AgentLoop per scene:
                     generate -> vision judge -> retry with feedback
                   Every iteration persists to B2 and links parent_run_id.
    C  disclose    FFmpegTransform burns the EU AI Act Art.50 disclosure onto
                   the delivered creative (the human-readable half).
    D  voiceover   ElevenLabs TTS, when a key is present.
    E  compose     ffmpeg Ken Burns over the stills + VO -> MP4.
    F  attest      Manifest embedded INTO the media file (machine-readable
                   half of Art.50) + an Object-Locked copy in B2.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from genblaze_core import (
    AgentContext,
    AgentLoop,
    Asset,
    CallableEvaluator,
    EvaluationResult,
    FFmpegTransform,
    KeyStrategy,
    Modality,
    ObjectLockConfig,
    ObjectStorageSink,
    Pipeline,
    PromptVisibility,
    StepType,
    SyncProvider,
)
from genblaze_core.media import Mp4Handler, PngHandler
from genblaze_s3 import S3StorageBackend

from .config import Settings, get_settings
from .models import BrandKit, CampaignSpec, Scene, Verdict

Emit = Callable[..., None]

# flux.1-dev only accepts these dimensions (422s otherwise).
FORMAT_DIMS: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "9:16": (768, 1344),
    "16:9": (1344, 768),
}


# ==========================================================================
# Storage
# ==========================================================================
def build_backend(s: Settings | None = None) -> S3StorageBackend:
    s = s or get_settings()
    return S3StorageBackend.for_backblaze(s.b2_bucket, region=s.b2_region)


def build_sink(
    backend: S3StorageBackend,
    *,
    prefix: str,
    key_strategy: KeyStrategy = KeyStrategy.HIERARCHICAL,
    lock_days: int | None = None,
) -> ObjectStorageSink:
    """A fresh sink per campaign run (documented guidance)."""
    lock = None
    if lock_days:
        lock = ObjectLockConfig(
            retain_until=datetime.now(timezone.utc) + timedelta(days=lock_days),
            mode="GOVERNANCE",
        )
    return ObjectStorageSink(
        backend, prefix=prefix, key_strategy=key_strategy, manifest_lock=lock
    )


def fetch_bytes(backend: S3StorageBackend, durable_url: str) -> bytes | None:
    """Read an asset back out of B2 by its manifest (durable) URL."""
    key = backend.key_from_url(durable_url)
    if not key:
        return None
    got = backend.get(key)
    if isinstance(got, tuple):
        got = got[0]
    return got if isinstance(got, bytes) else None


# ==========================================================================
# Demo mode — real pipeline, real B2, real manifests, zero provider spend
# ==========================================================================
DEMO_PALETTE = [
    ((16, 46, 44), (86, 128, 106)),
    ((32, 28, 44), (128, 96, 140)),
    ((44, 34, 20), (176, 138, 74)),
    ((18, 34, 52), (74, 124, 168)),
]


def demo_image(path: Path, caption: str, width: int, height: int, seed: int = 0) -> Path:
    """A deterministic placeholder still, so demo runs still exercise the full
    transfer / hash / manifest / Object Lock path with no provider call."""
    from PIL import Image, ImageDraw

    top, bottom = DEMO_PALETTE[seed % len(DEMO_PALETTE)]
    img = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(1, height - 1)
        draw.line(
            [(0, y), (width, y)],
            fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)),
        )
    font = _font(max(20, width // 26))
    box = draw.textbbox((0, 0), caption, font=font)
    draw.text(
        ((width - (box[2] - box[0])) / 2, (height - (box[3] - box[1])) / 2),
        caption, font=font, fill=(255, 255, 255, 230),
    )
    img.save(path, "PNG")
    return path


DEMO_PLAN = {
    "campaign_title": "Steady State (demo)",
    "audience": "Weekend hikers who value durable, minimalist gear.",
    "scenes": [
        {
            "headline": "Your water, unaffected by the trail.",
            "image_prompt": "A matte steel bottle on sun-warmed granite in a pine clearing.",
            "voiceover": "Built to hold temperature, so your focus stays on the path.",
        },
        {
            "headline": "The quiet companion to every ascent.",
            "image_prompt": "Close-up of a condensation-beaded bottle beside an alpine lake.",
            "voiceover": "A precise balance of weight and insulation.",
        },
        {
            "headline": "Designed for the moment you stop.",
            "image_prompt": "A bottle resting on a summit cairn at golden hour.",
            "voiceover": "For the view you earned.",
        },
        {
            "headline": "Carry less. Notice more.",
            "image_prompt": "Overhead flat lay of a packed daybag with a steel bottle.",
            "voiceover": "Everything you need, nothing you don't.",
        },
    ],
    "disclosure_line": "Contains AI-generated imagery.",
}


class DemoPlanProvider(SyncProvider):
    """Stands in for the planner LLM; still writes a hash-bound file:// artifact."""

    name = "demo-planner"

    def __init__(self, out_dir: Path, scene_count: int):
        super().__init__()
        self._out_dir = Path(out_dir)
        self._scene_count = scene_count

    def generate(self, step, config=None):  # noqa: ANN001
        plan = dict(DEMO_PLAN)
        plan["scenes"] = DEMO_PLAN["scenes"][: self._scene_count]
        text = json.dumps(plan, indent=2)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        path = self._out_dir / f"plan-demo-{digest[:16]}.json"
        path.write_text(text, encoding="utf-8")
        step.assets.append(
            Asset(url=path.as_uri(), media_type="application/json",
                  sha256=digest, metadata={"text": text})
        )
        return step


class DemoImageProvider(SyncProvider):
    """Stands in for flux.1-dev — real bytes, real hashing, no provider call."""

    name = "demo-image"

    def __init__(self, out_dir: Path):
        super().__init__()
        self._out_dir = Path(out_dir)

    def generate(self, step, config=None):  # noqa: ANN001
        width = int(step.params.get("width", 1024))
        height = int(step.params.get("height", 1024))
        caption = (step.prompt or "demo")[:38]
        seed = int(step.metadata.get("scene", 0) or 0) if step.metadata else 0
        path = self._out_dir / f"demo-{uuid.uuid4().hex[:12]}.png"
        demo_image(path, caption, width, height, seed)
        step.assets.append(Asset(url=path.as_uri(), media_type="image/png"))
        return step


# ==========================================================================
# A — Planner: Featherless as a first-class Genblaze Step
# ==========================================================================
def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_json_loose(text: str) -> dict[str, Any]:
    """Featherless' response_format is unreliable ('model is busy'), so we
    enforce JSON in the prompt and parse defensively."""
    cleaned = _strip_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            raise
        return json.loads(match.group())


class FeatherlessChatStep(SyncProvider):
    """Wraps Featherless chat so the LLM call lands in the manifest.

    genblaze ships chat() as a bare function outside the Pipeline machinery,
    so a plain call leaves no provenance. This adapter makes the planning
    step a real Step with a hash-bound TEXT asset.
    """

    name = "featherless-chat"
    # The planner's output is written to disk as a real file:// asset so the
    # sink can transfer and SHA-256-bind it. A "text:" pseudo-URL would be
    # rejected by the transfer layer (https/file only) and would leave the
    # campaign plan outside the verified provenance chain.

    def __init__(self, *, api_key: str, base_url: str, out_dir: Path,
                 system: str | None = None):
        super().__init__()
        self._api_key = api_key
        self._base_url = base_url
        self._system = system
        self._out_dir = Path(out_dir)
        self._out_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, step, config=None):  # noqa: ANN001
        from genblaze_openai import chat

        resp = chat(
            step.model,
            prompt=step.prompt,
            system=self._system,
            api_key=self._api_key,
            base_url=self._base_url,
            max_tokens=step.params.get("max_tokens", 1200),
            temperature=step.params.get("temperature", 0.7),
            timeout=step.params.get("timeout", 120),
        )
        text = resp.text or ""
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        path = self._out_dir / f"plan-{digest[:16]}.json"
        path.write_text(text, encoding="utf-8")
        step.assets.append(
            Asset(
                url=path.as_uri(),
                media_type="application/json",
                sha256=digest,
                metadata={"text": text},
            )
        )
        return step


PLANNER_SYSTEM = (
    "You are a senior advertising creative director. You produce compact, "
    "on-brand campaign plans. You return ONLY valid JSON — no prose, no code fences."
)


def _planner_prompt(brief: str, brand: BrandKit, scene_count: int) -> str:
    return f"""Create a {scene_count}-scene ad campaign.

BRIEF: {brief}

BRAND: {brand.name}
TONE: {brand.tone}
VISUAL RULES: {"; ".join(brand.visual_rules) or "none"}
BANNED CLAIMS (must never appear anywhere): {", ".join(brand.banned_claims) or "none"}

Return ONLY this JSON:
{{
  "campaign_title": "short title",
  "audience": "one line on who this targets",
  "scenes": [
    {{
      "headline": "max 8 words, no banned claims",
      "image_prompt": "a vivid photographic prompt for a text-free image; describe subject, setting, lighting, mood, lens. Do NOT ask for any words or lettering in the image.",
      "voiceover": "one spoken sentence, max 22 words"
    }}
  ],
  "disclosure_line": "{brand.required_disclosure}"
}}

Exactly {scene_count} scene(s)."""


def plan_campaign(
    brief: str,
    brand: BrandKit,
    scene_count: int,
    *,
    sink: ObjectStorageSink,
    tenant_id: str,
    s: Settings,
) -> tuple[CampaignSpec, Any]:
    """Stage A. Returns the spec plus the PipelineResult for lineage."""
    demo = s.demo_mode or not s.has_planner
    provider = (
        DemoPlanProvider(s.work_dir, scene_count)
        if demo
        else FeatherlessChatStep(
            api_key=s.featherless_key,
            base_url=s.featherless_base,
            out_dir=s.work_dir,
            system=PLANNER_SYSTEM,
        )
    )
    result = (
        Pipeline("hallmark-plan", tenant_id=tenant_id)
        .metadata(stage="plan", brand=brand.name)
        .step(
            provider,
            model="demo-plan" if demo else s.featherless_model,
            prompt=_planner_prompt(brief, brand, scene_count),
            modality=Modality.TEXT,
            metadata={"stage": "plan"},
        )
        .run(sink=sink, timeout=180, raise_on_failure=True)
    )

    text = result.run.steps[0].assets[0].metadata["text"]
    data = parse_json_loose(text)
    scenes = [
        Scene(
            headline=str(x.get("headline", "")).strip(),
            image_prompt=str(x.get("image_prompt", "")).strip(),
            voiceover=str(x.get("voiceover", "")).strip(),
        )
        for x in data.get("scenes", [])
    ][:scene_count]
    if not scenes:
        raise ValueError("planner returned no scenes")

    spec = CampaignSpec(
        campaign_title=str(data.get("campaign_title", "Untitled campaign")),
        audience=str(data.get("audience", "")),
        scenes=scenes,
        disclosure_line=str(data.get("disclosure_line") or brand.required_disclosure),
    )
    return spec, result


# ==========================================================================
# Judges
# ==========================================================================
JUDGE_SYSTEM = (
    "You are a strict brand-compliance reviewer for advertising creative. "
    "You return ONLY valid JSON."
)


def judge_copy(spec: CampaignSpec, brand: BrandKit, s: Settings) -> Verdict:
    """Text/policy judge (Featherless): banned claims, tone, disclosure."""
    if s.demo_mode or not s.has_planner:
        blob = " ".join(f"{x.headline} {x.voiceover}" for x in spec.scenes).lower()
        hits = [c for c in brand.banned_claims if c.lower() in blob]
        return Verdict(
            passed=not hits,
            score=0.0 if hits else 0.9,
            policy_issues=[f"banned claim: {h}" for h in hits],
            feedback="demo mode: rule-based copy check",
        )

    from genblaze_openai import chat

    prompt = f"""Review this ad copy against the brand policy.

BRAND: {brand.name} | TONE: {brand.tone}
BANNED CLAIMS (flag only if the copy makes this claim): {", ".join(brand.banned_claims) or "none"}

Judge ONLY the copy below: banned claims, tone fit, and unsupported absolutes.
Do NOT flag a missing AI disclosure — the disclosure "{brand.required_disclosure}"
is applied automatically to the delivered creative in a later pipeline stage.

COPY:
{json.dumps([{"headline": x.headline, "voiceover": x.voiceover} for x in spec.scenes], indent=2)}

Return ONLY:
{{"passed": true/false, "score": 0.0-1.0, "policy_issues": ["..."], "feedback": "how to fix"}}"""

    try:
        resp = chat(
            s.featherless_model,
            prompt=prompt,
            system=JUDGE_SYSTEM,
            api_key=s.featherless_key,
            base_url=s.featherless_base,
            max_tokens=400,
            temperature=0.2,
            timeout=120,
        )
        d = parse_json_loose(resp.text or "")
        return Verdict(
            passed=bool(d.get("passed", True)),
            score=float(d.get("score", 0.0) or 0.0),
            policy_issues=[str(x) for x in d.get("policy_issues", [])],
            feedback=str(d.get("feedback", "")),
        )
    except Exception as exc:  # noqa: BLE001
        # A judge outage must not fail the campaign — degrade to a
        # deterministic substring check so policy is still enforced.
        blob = " ".join(f"{x.headline} {x.voiceover}" for x in spec.scenes).lower()
        hits = [c for c in brand.banned_claims if c.lower() in blob]
        return Verdict(
            passed=not hits,
            score=0.0 if hits else 0.8,
            policy_issues=[f"banned claim: {h}" for h in hits],
            feedback=f"copy judge unavailable ({type(exc).__name__}); used rule-based fallback",
        )


def judge_image(image_bytes: bytes, scene: Scene, brand: BrandKit, s: Settings) -> Verdict:
    """Vision judge (NVIDIA NIM) — brand adherence of the rendered image."""
    if s.demo_mode or not s.has_vision_judge:
        return Verdict(passed=True, score=0.88, feedback="demo mode: judge stubbed")

    from genblaze_nvidia import chat as nchat

    b64 = base64.b64encode(image_bytes).decode()
    prompt = f"""Review this advertising image for brand compliance.

BRAND: {brand.name}
TONE: {brand.tone}
VISUAL RULES: {"; ".join(brand.visual_rules) or "none"}
INTENDED SUBJECT: {scene.image_prompt}

Judge: does it match the intended subject, is it on-tone, is it usable as an ad
(well composed, not distorted, no garbled text or extra limbs)?

Return ONLY:
{{"passed": true/false, "score": 0.0-1.0, "brand_issues": ["..."], "feedback": "a concrete instruction to improve the image prompt"}}"""

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }
    ]
    resp = nchat(s.vision_model, messages=messages, max_tokens=600, temperature=0.2)
    d = parse_json_loose(resp.text or "")
    return Verdict(
        passed=bool(d.get("passed", False)),
        score=float(d.get("score", 0.0) or 0.0),
        brand_issues=[str(x) for x in d.get("brand_issues", [])],
        feedback=str(d.get("feedback", "")),
    )


# ==========================================================================
# B — Keyframes with an evaluate/retry AgentLoop
# ==========================================================================
def generate_scene(
    scene: Scene,
    brand: BrandKit,
    fmt: str,
    *,
    backend: S3StorageBackend,
    sink: ObjectStorageSink,
    tenant_id: str,
    s: Settings,
    emit: Emit,
    scene_index: int,
) -> tuple[Asset | None, Verdict, list[str], int]:
    """One scene -> one approved image. Returns (asset, verdict, lineage, iters)."""
    demo = s.demo_mode or not s.has_image
    if not demo:
        from genblaze_nvidia import NvidiaImageProvider

    width, height = FORMAT_DIMS.get(fmt, FORMAT_DIMS["1:1"])
    lineage: list[str] = []
    verdicts: list[Verdict] = []

    def image_provider():
        if demo:
            return DemoImageProvider(s.work_dir)
        return NvidiaImageProvider(output_dir=str(s.work_dir))

    def build(ctx: AgentContext) -> Pipeline:
        prompt = scene.image_prompt
        prior = getattr(ctx, "last_evaluation", None)
        if prior is not None and getattr(prior, "feedback", None):
            prompt = f"{prompt}. Revision note: {prior.feedback}"
            emit("scene.retry", scene=scene_index, note=prior.feedback[:180])
        return (
            Pipeline(f"hallmark-scene-{scene_index}", tenant_id=tenant_id)
            .metadata(stage="keyframe", scene=scene_index, fmt=fmt, brand=brand.name)
            .step(
                image_provider(),
                model="demo-image" if demo else s.image_model,
                prompt=prompt,
                modality=Modality.IMAGE,
                width=width,
                height=height,
                metadata={"scene": scene_index, "fmt": fmt},
                prompt_visibility=PromptVisibility.PUBLIC,
            )
        )

    def evaluate(result: Any) -> EvaluationResult:
        step = result.run.steps[-1]
        lineage.append(result.run.run_id)
        assets = step.assets or []
        if not assets:
            v = Verdict(passed=False, score=0.0, feedback="no image produced; retry")
            verdicts.append(v)
            return EvaluationResult(passed=False, score=0.0, feedback=v.feedback)

        raw = fetch_bytes(backend, assets[0].url)
        if raw is None:
            # Can't judge what we can't read — accept rather than burn retries.
            v = Verdict(passed=True, score=0.5, feedback="image unreadable for judging")
            verdicts.append(v)
            return EvaluationResult(passed=True, score=0.5)

        try:
            v = judge_image(raw, scene, brand, s)
        except Exception as exc:  # noqa: BLE001
            v = Verdict(passed=True, score=0.5,
                        feedback=f"vision judge unavailable ({type(exc).__name__})")
        verdicts.append(v)
        emit("scene.judged", scene=scene_index, score=v.score,
             passed=v.passed, issues=v.all_issues[:3])
        passed = v.passed and v.score >= s.judge_pass_score
        return EvaluationResult(passed=passed, score=v.score, feedback=v.feedback)

    emit("scene.started", scene=scene_index, fmt=fmt, headline=scene.headline)
    loop = AgentLoop(build, CallableEvaluator(evaluate),
                     max_iterations=s.max_judge_iterations,
                     stop_on_pipeline_failure=False)
    out = loop.run(sink=sink, timeout=s.step_timeout, raise_on_failure=False)

    asset = None
    for it in reversed(getattr(out, "iterations", []) or []):
        res = getattr(it, "result", None)
        steps = getattr(getattr(res, "run", None), "steps", None) or []
        if steps and steps[-1].assets:
            asset = steps[-1].assets[0]
            break

    final = verdicts[-1] if verdicts else Verdict(passed=False, feedback="no iterations ran")
    return asset, final, lineage, len(verdicts)


# ==========================================================================
# C — Disclosure overlay (the human-readable half of Art.50)
# ==========================================================================
def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _font(size: int):
    """Best-effort truetype lookup; falls back to Pillow's bitmap font."""
    from PIL import ImageFont

    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:  # noqa: BLE001
            continue
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def overlay_disclosure_image(src: Path, disclosure: str, out_dir: Path) -> Path:
    """Human-readable half of Art.50, burned onto the still.

    genblaze's FFmpegTransform declares only VIDEO/AUDIO modalities, so the
    image path uses Pillow directly; the video path below still goes through
    FFmpegTransform as a real pipeline Step.
    """
    from PIL import Image, ImageDraw

    img = Image.open(src).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    size = max(16, img.width // 46)
    font = _font(size)
    pad = size // 2

    box = draw.textbbox((0, 0), disclosure, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    x, y = pad * 2, img.height - th - pad * 3
    draw.rectangle([x - pad, y - pad, x + tw + pad, y + th + pad * 2], fill=(0, 0, 0, 140))
    draw.text((x, y), disclosure, font=font, fill=(255, 255, 255, 235))

    out = out_dir / f"{src.stem}-disclosed.png"
    img.save(out, "PNG")
    return out


def overlay_disclosure_video(
    video_path: Path, disclosure: str, *, sink: ObjectStorageSink,
    tenant_id: str, s: Settings,
) -> Any:
    """Burn the disclosure onto the MP4 via Genblaze's FFmpegTransform."""
    asset = Asset(
        url=video_path.as_uri(),
        media_type="video/mp4",
        sha256=_sha256_file(video_path),  # keeps the canonical hash stable
    )
    return (
        Pipeline("hallmark-disclose", tenant_id=tenant_id)
        .metadata(stage="disclosure")
        .step(
            FFmpegTransform(output_dir=str(s.work_dir)),
            model="transform",
            modality=Modality.VIDEO,
            step_type=StepType.EDIT,
            operation="overlay_text",
            text=disclosure,
            fontsize=24,
            x=32,
            y=32,
            fontcolor="white",
            external_inputs=[asset],
        )
        .run(sink=sink, timeout=180, raise_on_failure=False)
    )


# ==========================================================================
# D — Voiceover (optional; only when an ElevenLabs key is present)
# ==========================================================================
def synthesize_voiceover(
    line: str, *, sink: ObjectStorageSink, tenant_id: str, s: Settings, index: int
) -> Path | None:
    """TTS narration as a real pipeline Step. Returns a local audio path."""
    if not s.has_tts:
        return None
    try:
        from genblaze_elevenlabs import ElevenLabsTTSProvider
    except ImportError:
        return None

    result = (
        Pipeline("hallmark-voice", tenant_id=tenant_id)
        .metadata(stage="voiceover")
        .step(
            ElevenLabsTTSProvider(output_dir=str(s.work_dir)),
            model=s.tts_model,
            prompt=line,
            modality=Modality.AUDIO,
            voice_id=s.tts_voice_id,
            metadata={"scene": index},
        )
        .run(sink=sink, timeout=180, raise_on_failure=False)
    )
    step = result.run.steps[-1]
    if not step.assets:
        return None

    # The sink rewrites asset.url to B2; pull the bytes back for local muxing.
    raw = fetch_bytes(build_backend(s), step.assets[0].url)
    if raw is None:
        return None
    path = s.work_dir / f"vo-{index}-{hashlib.sha256(raw).hexdigest()[:12]}.mp3"
    path.write_bytes(raw)
    return path


# ==========================================================================
# F — Attestation: embed the manifest into the file itself
# ==========================================================================
def embed_manifest(path: Path, manifest: Any) -> bool:
    """Machine-readable marking: the provenance record travels inside the file."""
    try:
        handler = Mp4Handler() if path.suffix.lower() == ".mp4" else PngHandler()
        handler.embed(path, manifest)
        return True
    except Exception:  # noqa: BLE001
        return False


def extract_manifest(path: Path) -> Any | None:
    for handler in (Mp4Handler(), PngHandler()):
        try:
            return handler.extract(path)
        except Exception:  # noqa: BLE001
            continue
    return None


# ==========================================================================
# E — Video composition (no video model required)
# ==========================================================================
# Ring buffer of the most recent ffmpeg stderr tails, so a composition
# failure reports a cause instead of a bare False.
_last_ffmpeg_error: list[str] = []


def last_ffmpeg_error() -> str:
    return _last_ffmpeg_error[-1] if _last_ffmpeg_error else ""


def ffmpeg_bin() -> str | None:
    return shutil.which("ffmpeg")


VIDEO_DIMS: dict[str, tuple[int, int]] = {
    "1:1": (1080, 1080),
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}


def compose_video(
    stills: list[Path],
    voice_tracks: list[Path],
    out_path: Path,
    *,
    seconds_per_scene: float = 4.0,
    fmt: str = "1:1",
) -> Path | None:
    """Ken Burns over the approved stills, muxed with voiceover when present.

    No video-generation model required — the ad is composed from the stills
    the judge approved, so every frame is provenance-covered.
    """
    ff = ffmpeg_bin()
    if not ff or not stills:
        return None

    tmp = Path(tempfile.mkdtemp(prefix="hallmark-vid-"))
    clips: list[Path] = []
    fps = 30
    frames = int(seconds_per_scene * fps)
    width, height = VIDEO_DIMS.get(fmt, VIDEO_DIMS["1:1"])

    for i, still in enumerate(stills):
        clip = tmp / f"clip{i}.mp4"
        # zoompan defaults to 1280x720 output unless s= is given, which would
        # break any downstream crop — always pin s= to the target size.
        vf = (
            f"scale={width*2}:{height*2}:force_original_aspect_ratio=increase,"
            f"crop={width*2}:{height*2},"
            f"zoompan=z='min(zoom+0.0012,1.15)':d={frames}"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps},"
            f"format=yuv420p"
        )
        cmd = [ff, "-y", "-loop", "1", "-i", str(still), "-vf", vf,
               "-t", str(seconds_per_scene), "-c:v", "libx264", "-preset", "veryfast",
               "-pix_fmt", "yuv420p", str(clip)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        if proc.returncode == 0:
            clips.append(clip)
        else:
            _last_ffmpeg_error.append(proc.stderr[-600:])

    if not clips:
        return None

    listing = tmp / "list.txt"
    listing.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8")
    silent = tmp / "silent.mp4"
    if subprocess.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                       "-c", "copy", str(silent)], capture_output=True, timeout=180).returncode != 0:
        return None

    tracks = [p for p in voice_tracks if p and Path(p).exists()]
    if not tracks:
        shutil.move(str(silent), str(out_path))
        return out_path

    voice = tmp / "voice.mp3"
    if len(tracks) == 1:
        shutil.copy(str(tracks[0]), str(voice))
    else:
        alist = tmp / "alist.txt"
        alist.write_text("".join(f"file '{Path(t).as_posix()}'\n" for t in tracks), encoding="utf-8")
        if subprocess.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(alist),
                           "-c", "copy", str(voice)], capture_output=True, timeout=180).returncode != 0:
            shutil.move(str(silent), str(out_path))
            return out_path

    ok = subprocess.run(
        [ff, "-y", "-i", str(silent), "-i", str(voice), "-c:v", "copy", "-c:a", "aac",
         "-shortest", str(out_path)], capture_output=True, timeout=240
    ).returncode == 0
    if not ok:
        shutil.move(str(silent), str(out_path))
    return out_path
