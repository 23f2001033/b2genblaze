"""Provider reachability smoke test — spends a tiny amount of free credit.

Confirms every provider in the Hallmark pipeline actually answers with this
account's keys, before we build anything on top of them:

  1. Featherless  — planner + text/policy judge (OpenAI-compatible, base_url)
  2. Featherless  — structured JSON output (needed for CampaignSpec)
  3. NVIDIA NIM   — chat (Nemotron), the vision-judge fallback
  4. NVIDIA NIM   — image generation, the load-bearing media step
  5. Google       — Gemini chat, cross-provider judge fallback

Run:  .venv/Scripts/python.exe scripts/smoke_providers.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

FEATHERLESS_BASE = "https://api.featherless.ai/v1"
FEATHERLESS_MODELS = ["zai-org/GLM-4.7", "deepseek-ai/DeepSeek-V3.2", "moonshotai/Kimi-K2.5"]
NVIDIA_CHAT_MODEL = "nvidia/nemotron-4-340b-instruct"
NVIDIA_IMAGE_MODELS = ["black-forest-labs/flux.1-schnell", "stabilityai/stable-diffusion-xl"]
GEMINI_MODEL = "gemini-2.0-flash"

PASS, FAIL, SKIP = "[PASS]", "[FAIL]", "[SKIP]"
results: dict[str, bool] = {}


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {PASS if ok else FAIL} {label}{f' — {detail}' if detail else ''}")
    results[label] = ok
    return ok


def short(x: object, n: int = 90) -> str:
    s = str(x).replace("\n", " ").strip()
    return s[:n] + ("..." if len(s) > n else "")


def main() -> int:
    # --- 1 & 2. Featherless: planner + structured output ---
    print("\n1. Featherless — planner / policy judge")
    from genblaze_openai import chat

    key = os.environ.get("FEATHERLESS_API_KEY", "")
    working_model = None
    for model in FEATHERLESS_MODELS:
        try:
            resp = chat(
                model,
                prompt="Reply with exactly the word: ready",
                api_key=key,
                base_url=FEATHERLESS_BASE,
                max_tokens=16,
                timeout=90,
            )
            if check(f"chat via {model}", bool(resp.text), short(resp.text, 60)):
                working_model = model
                break
        except Exception as exc:  # noqa: BLE001
            check(f"chat via {model}", False, f"{type(exc).__name__}: {short(exc, 110)}")

    print("\n2. Featherless — structured JSON (CampaignSpec needs this)")
    if working_model:
        schema = {
            "type": "json_schema",
            "json_schema": {
                "name": "campaign",
                "schema": {
                    "type": "object",
                    "properties": {
                        "headline": {"type": "string"},
                        "image_prompt": {"type": "string"},
                    },
                    "required": ["headline", "image_prompt"],
                },
            },
        }
        try:
            resp = chat(
                working_model,
                prompt="Ad concept for a steel water bottle. Return JSON only.",
                api_key=key,
                base_url=FEATHERLESS_BASE,
                response_format=schema,
                max_tokens=300,
                timeout=120,
            )
            parsed = json.loads(resp.text)
            check("json_schema response_format", "headline" in parsed, short(parsed, 100))
        except Exception as exc:  # noqa: BLE001
            check("json_schema response_format", False, f"{type(exc).__name__}: {short(exc, 110)}")
            print("      -> will fall back to prompt-enforced JSON + manual parse")
    else:
        print(f"  {SKIP} no working Featherless model")

    # --- 3. NVIDIA chat ---
    print("\n3. NVIDIA NIM — chat (judge fallback)")
    try:
        from genblaze_nvidia import chat as nchat

        resp = nchat(NVIDIA_CHAT_MODEL, prompt="Reply with exactly: ready",
                     max_tokens=16, timeout=90)
        check(f"chat via {NVIDIA_CHAT_MODEL}", bool(resp.text), short(resp.text, 60))
    except Exception as exc:  # noqa: BLE001
        check(f"chat via {NVIDIA_CHAT_MODEL}", False, f"{type(exc).__name__}: {short(exc, 130)}")

    # --- 4. NVIDIA image generation (the load-bearing step) ---
    print("\n4. NVIDIA NIM — image generation (LOAD-BEARING)")
    from genblaze_core import Modality, Pipeline
    from genblaze_nvidia import NvidiaImageProvider

    for model in NVIDIA_IMAGE_MODELS:
        try:
            out = Path("output"); out.mkdir(exist_ok=True)
            result = (
                Pipeline("provider-smoke")
                .step(
                    NvidiaImageProvider(output_dir=str(out)),
                    model=model,
                    prompt="a matte steel water bottle on a clean studio background",
                    modality=Modality.IMAGE,
                )
                .run(timeout=180)
            )
            step = result.run.steps[0]
            assets = step.assets or []
            ok = bool(assets)
            check(f"image via {model}", ok,
                  short(assets[0].url, 80) if ok else f"status={step.status} err={short(step.error, 90)}")
            if ok:
                break
        except Exception as exc:  # noqa: BLE001
            check(f"image via {model}", False, f"{type(exc).__name__}: {short(exc, 130)}")

    # --- 5. Gemini ---
    print("\n5. Google Gemini — cross-provider fallback")
    try:
        from genblaze_google import chat as gchat

        resp = gchat(GEMINI_MODEL, prompt="Reply with exactly: ready",
                     max_tokens=16, timeout=90)
        check(f"chat via {GEMINI_MODEL}", bool(resp.text), short(resp.text, 60))
    except Exception as exc:  # noqa: BLE001
        check(f"chat via {GEMINI_MODEL}", False, f"{type(exc).__name__}: {short(exc, 130)}")

    print("\n" + "=" * 62)
    failed = [k for k, v in results.items() if not v]
    passed = [k for k, v in results.items() if v]
    print(f"{len(passed)} passed, {len(failed)} failed")
    for f in failed:
        print(f"  {FAIL} {f}")
    return 0 if any("image via" in k for k in passed) else 1


if __name__ == "__main__":
    sys.exit(main())
