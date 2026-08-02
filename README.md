---
title: Hallmark
emoji: ⚖️
colorFrom: yellow
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Governed AI creative with verifiable provenance on Backblaze B2
---

# Hallmark — governed AI creative

### ▶ Live app: **https://hallmark-64ts.onrender.com**

> Free instance — it sleeps after ~15 min idle, so the first request may take ~50s to wake.
> Nothing is lost when it sleeps: all state lives in Backblaze B2.
> Try the **Verify** tab first — drop in any PNG or MP4 from the Library.

**Generate AI ad creative that can prove where it came from.**

Hallmark plans a campaign, generates the imagery, judges its own output against your brand
and policy rules, retries what fails, then stamps every approved asset with a SHA-256-bound
provenance manifest — embedded *inside* the file and retained immutably on Backblaze B2
under Object Lock.

Built for the **Backblaze Generative Media Hackathon** with [Genblaze](https://github.com/backblaze-labs/genblaze) + Backblaze B2.

---

## Why this exists

**EU AI Act Article 50 became applicable on 2 August 2026.** Providers of AI systems that
generate synthetic image, audio, or video must ensure outputs are *marked in a machine-readable
format and detectable as AI-generated*; deployers must disclose. Marketing teams shipping
AI creative into the EU now carry a documentation duty they mostly cannot evidence.

Most AI creative tools give you a file and a prompt history. Neither survives a compliance
review. Hallmark produces the evidence **as a side effect of generating**, satisfying both
halves of Article 50:

| Article 50 requirement | How Hallmark satisfies it |
|---|---|
| Machine-readable marking | Genblaze provenance manifest embedded in the PNG/MP4 itself |
| Detectable as AI-generated | Visible disclosure burned onto the delivered creative |
| Records available to authorities | Object-Locked (WORM) manifest in B2 + exportable disclosure register |

---

## What it does

1. **Brand kit is the governance input** — tone, visual rules, banned claims, required disclosure.
2. **Plan** — an LLM turns a one-line brief into a structured campaign spec.
3. **Generate** — keyframes per scene and per format.
4. **Judge** — a vision model scores brand adherence; a text model checks copy for banned
   claims. Failures are **retried with the critique fed back into the prompt**, and every
   iteration is linked by `parent_run_id`, so the reasoning trail is part of the provenance.
5. **Disclose** — the required AI-disclosure is burned onto the creative.
6. **Compose** — an MP4 ad is assembled from the approved stills (Ken Burns + optional voiceover).
7. **Attest** — the manifest is embedded into each delivered file and an immutable copy is
   written to B2 under Object Lock.
8. **Verify** — anyone can drop a file into `/verify` and read its full lineage offline.
9. **Register** — export the Article 50 disclosure register as CSV.

---

## Architecture

```
Browser (React SPA, served same-origin by FastAPI)
   │  SSE /api/runs/{id}/events   ← live pipeline progress
   ▼
FastAPI  (single container, ffmpeg baked in)
   │
   ├── app/pipelines.py   ← ALL Genblaze usage is confined here
   ├── app/campaign.py    ← flow control, parallelism, degradation
   └── app/store.py       ← B2 as the system of record (no database)
   ▼
Backblaze B2  (private bucket, Object Lock enabled)
   hallmark/runs/…   HIERARCHICAL   per-run manifests + assets
   attest/…          OBJECT LOCK    immutable stamped deliverables
   index/…                          run records → library + register
```

### Pipeline stages

| Stage | Genblaze surface | Provider / model |
|---|---|---|
| Plan | custom `SyncProvider` wrapping `chat(base_url=…)` | Featherless `deepseek-ai/DeepSeek-V3.2` |
| Keyframes | `Pipeline.step(modality=IMAGE)` inside `AgentLoop` | NVIDIA NIM `black-forest-labs/flux.1-dev` |
| Vision judge | `AgentLoop` + `CallableEvaluator` | NVIDIA NIM `nvidia/nemotron-nano-12b-v2-vl` |
| Copy judge | `chat()` + rule-based fallback | Featherless `deepseek-ai/DeepSeek-V3.2` |
| Voiceover *(optional)* | `Pipeline.step(modality=AUDIO)` | ElevenLabs `eleven_flash_v2_5` |
| Disclosure (video) | `FFmpegTransform` `overlay_text` | ffmpeg |
| Attestation | `Pipeline.ingest()` + `Mp4Handler`/`PngHandler` embed | — |

---

## How this uses Genblaze

Not one `.step()` call — twelve distinct SDK surfaces:

- **`Pipeline` / `.step()` / `.metadata()`** — multi-stage generation with per-step metadata.
- **`AgentLoop` + `CallableEvaluator` + `EvaluationResult`** — generate → evaluate → retry, with
  the judge's feedback rewritten into the next prompt.
- **`parent_run_id` lineage** — every retry links to its predecessor; the chain is surfaced in the UI.
- **Custom `SyncProvider`** — Genblaze ships `chat()` as a bare function outside the Pipeline
  machinery, so LLM calls normally leave no provenance. `FeatherlessChatStep` wraps it into a
  real Step whose output is a hash-bound artifact. *(The official Backblaze sample hit this same
  gap and filed it as SDK feedback — this closes it.)*
- **`Pipeline.ingest()`** — non-generative provenance for the delivery event.
- **`ObjectStorageSink` + `KeyStrategy.HIERARCHICAL`** — durable, credential-free asset URLs.
- **`ObjectLockConfig`** — WORM retention on attestation manifests.
- **`FFmpegTransform`** — disclosure overlay as a pipeline step.
- **`Mp4Handler` / `PngHandler`** — manifest embedding and extraction.
- **`Manifest.verify()`** — integrity checking, powering the public verify portal.
- **`Modality` / `StepType` / `PromptVisibility`** — correct provenance semantics per step.
- **`MockProvider`** — demo mode that produces real manifests with zero provider spend.

## How this uses Backblaze B2

B2 is the **system of record**, not a file dump. There is no database.

- **Run index** — every run is a JSON object in the bucket; the Library and Register read from
  B2, so state survives restarts and redeploys.
- **Object Lock (WORM)** — attestation manifests and stamped deliverables are written with
  `GOVERNANCE` retention, so the audit trail cannot be silently rewritten.
- **Private bucket + presigned reads** — Genblaze *rejects* SigV4 URLs in manifests (they decay
  before the manifest does, breaking provenance), so manifests carry durable credential-free
  URLs and the app mints short-lived presigned URLs at read time. **Assets are never
  world-readable** — the right posture for a compliance product.
- **Hierarchical layout** — `{tenant}/{date}/{run_id}/` keeps every artifact of a run together.
- **Server-side SHA-256** — per-part checksums verify transfer integrity on upload.

> In a larger deployment you would split a private originals bucket from a CDN-fronted delivery
> bucket. One bucket keeps the demo legible.

---

## Providers and models

| Purpose | Provider | Model |
|---|---|---|
| Campaign planning | Featherless AI | `deepseek-ai/DeepSeek-V3.2` |
| Copy / policy judge | Featherless AI | `deepseek-ai/DeepSeek-V3.2` |
| Image generation | NVIDIA NIM | `black-forest-labs/flux.1-dev` |
| Vision brand judge | NVIDIA NIM | `nvidia/nemotron-nano-12b-v2-vl` |
| Voiceover *(optional)* | ElevenLabs | `eleven_flash_v2_5` |
| Storage | Backblaze B2 | S3-compatible, `us-east-005` |

---

## Run it locally

```bash
git clone <this repo> && cd hallmark
cp .env.example .env      # fill in your keys

python -m venv .venv
.venv/Scripts/python -m pip install -r services/api/requirements.txt   # Windows
# source .venv/bin/activate && pip install -r services/api/requirements.txt

cd web && npm install && npm run build && cd ..

cd services/api
../../.venv/Scripts/python -m uvicorn app.main:app --port 8099
```

Open <http://localhost:8099>. `ffmpeg` must be on PATH for video composition.

### Verify your wiring first

```bash
.venv/Scripts/python scripts/smoke_b2.py         # B2 + Object Lock + provenance (no provider spend)
.venv/Scripts/python scripts/smoke_providers.py  # provider reachability
.venv/Scripts/python scripts/test_campaign.py    # full campaign end to end
```

`smoke_b2.py` checks credentials, region, asset transfer, manifest verification, the
presigned read path, and that Object Lock retention actually applies — before you spend
a cent on generation.

> **Your B2 bucket must be created with Object Lock enabled.** It cannot be turned on
> afterwards, and the attestation layer depends on it.

---

## Deploy

The repo ships a `render.yaml` blueprint and a self-contained `Dockerfile`
(ffmpeg + fonts included, SPA built in a Node stage, served same-origin by FastAPI).

**Render** — *New → Blueprint* → point at this repo. The blueprint sets the tuning
variables and prompts for the seven secrets. `LOW_RESOURCE=1` halves the composed
video's dimensions and switches ffmpeg to `ultrafast`, because free instances get
~0.1 vCPU where a 1080p x264 encode is not viable.

Any Docker host works — the image honours `$PORT` and needs no volumes; B2 holds all state.

> Hugging Face Spaces was the original target, but Docker Spaces now require a PRO
> subscription (only static Spaces are free), so the blueprint targets Render instead.

## Production notes

- **Degrades instead of failing.** A vision-judge outage accepts the image rather than burning
  retries; a copy-judge outage falls back to deterministic banned-claim matching; a failed
  video composition still ships the stills. The run reports what degraded.
- **Demo mode.** `DEMO_MODE=1` swaps in Genblaze's `MockProvider`, producing real manifests and
  real B2 writes with zero provider spend — so the app stays evaluable if credits run out.
- **Parallelism.** The copy judge runs concurrently with image generation; it gates nothing upstream.
- **Self-reporting.** `/healthz` returns a live capability matrix, and the UI renders it, so a
  missing key is visible rather than a mystery failure.

## Known limits

- The free NVIDIA NIM catalog is small: at build time only `flux.1-dev` was reachable
  (Cosmos video, Riva TTS, Fugatto, SDXL and SD3.5 all returned 404 on a free account).
  **Video is therefore composed from generated stills rather than a video model** — honest,
  fast, and fully provenance-covered, but not text-to-video.
- Featherless `response_format=json_schema` returns `400 "model is busy"` intermittently, so
  the planner enforces JSON in the prompt and parses defensively instead.
- Manifest embedding survives copying and uploading, but re-encoding or some social platforms
  strip metadata. The Object-Locked B2 copy is the durable record; the embedded copy is the
  convenient one.
- Provenance is Genblaze **trust mode 1 (integrity)**: it proves the manifest and bytes have not
  changed, not *who* produced them. Signing (mode 2) is an SDK roadmap item.

## License

MIT
