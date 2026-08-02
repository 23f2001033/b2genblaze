# Hallmark — Project Plan

> **Governed AI creative. Provably compliant.**
> Generate campaign media across providers, auto-QA it against brand + policy rules,
> and stamp every approved asset with a tamper-evident provenance record that lives
> in Backblaze B2 under Object Lock.

**Hackathon:** Backblaze Generative Media Hackathon (Genblaze on B2)
**Deadline:** Aug 4 2026, 02:30 GMT+5:30 — *~30h from now*
**Working name:** Hallmark *(alt: Assay, Attest, Cachet)*

---

## 1. The wedge

All three official Backblaze sample apps are the same shape: **prompt → media → B2 studio**.
With 1,252 participants, most submissions will be a fourth one. We need a different axis.

**The hook: EU AI Act Article 50 became applicable on 2 August 2026 — today.**

It requires providers of AI systems generating synthetic audio, image, video, or text to
ensure outputs are *marked in a machine-readable format and detectable as AI-generated*,
and deployers to disclose deepfakes. Systems already on market get until 2 Dec 2026 for the
machine-readable marking specifically.

Genblaze's canonical, SHA-256-bound, **embeddable** manifest is almost literally the
artifact this regulation asks for. B2 Object Lock is the immutable evidence store. Nobody
else in this field is going to connect those two dots on the day the rule lands.

So: **Hallmark is a creative tool that happens to be governed.** The demo shows good-looking
ad creative *and* a public verification portal a judge can drop a file into.

### Why this scores on all four judging criteria

| Criterion | How Hallmark answers it |
|---|---|
| **Real-World Utility** | Marketing/agency teams publishing AI creative into the EU now carry a legal disclosure duty. This produces the evidence automatically, as a side effect of generating. Clear audience, acute and dated pain. |
| **Production Readiness** | Fallback chains on every step, retry+backoff, step cache, pipeline timeouts, SSE progress, preflight model validation, structured logging, health checks, and a **mock-provider demo mode** so judges get a full run even if credits run dry. |
| **B2 Storage & Data Orchestration** | Not a dumping ground. Content-addressable dedup, hierarchical run folders, **Object Lock (WORM) on the audit manifests**, lifecycle rules pruning rejected iterations, durable credential-free URLs served straight to the browser, and a Parquet ledger in-bucket driving the cost/audit dashboard. B2 *is* the system of record. |
| **Use of Genblaze** | Multi-step chained pipelines, `AgentLoop` evaluate→retry with `parent_run_id` lineage, `Pipeline.ingest()` for non-generative brand-kit provenance, `fallback_models`, `FFmpegCompositor` fan-in, `EmbedPolicy` prompt redaction, `Mp4Handler.embed/extract`, `Manifest.verify()`, `ParquetSink`, custom `SyncProvider`. Roughly 12 SDK surfaces, not one. |

---

## 2. What it does

1. **Set up a brand kit once** — upload logo + reference images + brand rules (palette, tone,
   banned claims). Ingested via `Pipeline.ingest()`, so even the *uploads* get hashed
   provenance. Content-addressable, so re-uploading the same logo dedupes.
2. **Describe a campaign** — one brief, pick formats (1:1 / 9:16 / 16:9).
3. **Hallmark generates** — LLM plans the campaign spec → keyframe images → optional video →
   voiceover → music bed → composed MP4.
4. **Hallmark judges its own output** — a vision model scores brand adherence and policy
   compliance. Failures auto-retry with the critique fed back into the prompt. Every
   iteration is chained via `parent_run_id`, so the *reasoning trail* is in the provenance.
5. **Hallmark stamps it** — the manifest is embedded inside the delivered MP4/PNG, and a copy
   is written to B2 under Object Lock retention. Proprietary prompts get redacted via
   `EmbedPolicy` while the hash chain stays intact.
6. **Anyone can verify** — public `/verify` page: drop a file, get provider, model, timestamp,
   full lineage, and a pass/fail integrity check. *This is the thing judges will actually play with.*
7. **Export the disclosure register** — CSV/JSON evidence pack: every asset, model, timestamp,
   hash, retention date. The artifact a compliance officer asks for.

---

## 3. Architecture

```
Browser — React SPA (Vite), served by FastAPI from the same origin
   │   SSE: /api/runs/{run_id}/events
   ▼
FastAPI  (single Docker container, ffmpeg baked in)
   ├─ POST /api/brandkits      Pipeline.ingest()  → B2 (CAS, sha256'd)
   ├─ POST /api/runs           start campaign     → SSE stream
   ├─ POST /api/verify         extract + verify uploaded media
   ├─ GET  /api/register       Art.50 disclosure register (CSV/JSON)
   ├─ GET  /api/library        browse runs + lineage from B2
   ├─ GET  /api/assets/sign    durable URL → key → short-lived presigned URL
   └─ GET  /healthz
   ▼
genblaze  (ALL SDK use confined to one module: app/pipelines.py)
   ▼
Backblaze B2
   brandkits/   CONTENT_ADDRESSABLE   deduped source material
   runs/        HIERARCHICAL          {tenant}/{date}/{run_id}/manifest.json + assets/
   attest/      OBJECT LOCK           immutable manifest copies (GOVERNANCE mode)
   ledger/      Parquet               run/step/asset tables → dashboard
```

### The pipeline

### Verified provider reality (probed 2026-08-02, this account)

Everything below was tested against the real keys, not read from docs. **The docs are badly
out of date about what a free NVIDIA account can reach.**

| Capability | Status | Model |
|---|---|---|
| LLM planner / text judge | ✅ works | Featherless `deepseek-ai/DeepSeek-V3.2` |
| Image generation | ✅ works, ~4–8s | NVIDIA `black-forest-labs/flux.1-dev` |
| Vision judge | ✅ works | NVIDIA `nemotron-nano-12b-v2-vl`, `meta/llama-3.2-90b-vision-instruct` |
| ffmpeg | ✅ installed locally | 8.1.1 |
| Gemini / Imagen | ❌ **invalid key** | needs regeneration |
| TTS + music | ❌ **all 404** | Riva, Fugatto, Magpie all dead on this account |
| Video generation | ❌ **all 404** | Cosmos 1.0 / 2.0 dead on this account |
| Other image models | ❌ 404 / hang | `flux.1-schnell` hangs; SDXL, SD3.5, `flux.2-dev` 404 |

**Featherless caveats:** `response_format=json_schema` returns `400 "model is busy"` and
GLM-4.7 returns empty strings. Use **DeepSeek-V3.2 with prompt-enforced JSON** plus a
fence-stripping parser — more robust than relying on structured-output support.

### Revised pipeline

| Stage | Genblaze surface | Model |
|---|---|---|
| A — plan | custom `ChatStep(SyncProvider)` wrapping `chat(base_url=…)` | Featherless DeepSeek-V3.2 |
| B — keyframes ×N | `.step(modality=IMAGE)` | NVIDIA `flux.1-dev` |
| C — judge | `AgentLoop` + `Evaluator`, retry on fail | NVIDIA `nemotron-nano-12b-v2-vl` |
| D — voiceover | `.step(modality=AUDIO)` | ElevenLabs *(pending key)* |
| E — format variants | `FFmpegTransform` resize/crop | 1:1, 9:16, 16:9 |
| F — compose video | `FFmpegCompositor`, `input_from=[…]` | Ken Burns over stills + VO |
| G — stamp | `Mp4Handler`/`PngHandler` embed + Object Lock | — |

> **No video model is needed to ship video.** Stage F composes an actual MP4 ad from the
> generated stills (pan/zoom) plus voiceover. Honest, fast, cheap, and fully provenance-covered
> — and it exercises `FFmpegCompositor`/`FFmpegTransform`, which most submissions won't touch.

> **GMI Cloud is out** — credits closed before we started.
>
> `fallback_models=[...]` retries *model slugs within one provider*. Cross-**provider**
> fallback is our own wrapper. Worth building — it's the difference between "used the SDK"
> and "orchestrated across providers."

Stages B(+C) run inside an **`AgentLoop`**: a vision judge scores the output, and on failure
the loop rewrites the prompt from `ctx.last_evaluation.feedback` and retries (max 3).

**Featherless earns its place**: `genblaze_openai.chat()` accepts `base_url`, so
`chat(model, base_url="https://api.featherless.ai/v1", api_key=FEATHERLESS_KEY,
response_format=CampaignSpec)` drives both the planner and the judge. Wrapping it in a
`SyncProvider` makes the LLM call a **first-class manifest'd Step** — the official sample
had to punt on this and filed it as SDK feedback. We fix it; that's a talking point.

---

## 4. Reliability plan (this is where "Production Readiness" is won)

- **Demo mode.** `MockProvider` / `MockVideoProvider` / `MockAudioProvider` ship in
  `genblaze_core`. A `DEMO_MODE=1` run produces real manifests, real B2 writes, real
  verification — with zero provider spend. **Judges can always evaluate the app.**
- **Pre-seeded showcase runs.** 3–4 completed campaigns generated ahead of time, stored in B2,
  loaded instantly on the landing page. The demo never opens on a 3-minute cold video call.
- **Fallback chains** via `fallback_models=[...]` on every generative step.
- **`StepCache`** so repeated prompts don't re-burn credits.
- **Video is opt-in.** Default path is image + audio (fast, cheap, reliable). Video is a toggle.
- `pipeline_timeout`, typed error codes, `LoggingTracer`, `/healthz`.

---

## 5. Phases (~24h of work, ~30h available)

| # | Phase | Est. | Gate / definition of done |
|---|---|---|---|
| 0 | **Accounts & spike** | 45m | `quickstart.py` writes a real asset + manifest to B2 and `verify()` returns True |
| 1 | Backend skeleton — FastAPI, config, B2 sink, run store, SSE | 3h | `POST /api/runs` streams fake events end-to-end |
| 2 | `app/pipelines.py` — the whole Genblaze layer | 5h | One brief → composed MP4 + manifest in B2, from CLI |
| 3 | AgentLoop judge + brand/policy rules | 3h | A deliberately off-brand prompt fails, retries, and passes |
| 4 | Verify portal + disclosure register | 2h | Upload a generated MP4 → full lineage + integrity PASS |
| 5 | React frontend | 5h | Brief → live progress → gallery → verify → register |
| 6 | Docker + Render deploy | 2h | Public URL, healthy, cold-start tested |
| 7 | Seed showcase runs, demo mode, README, `.env.example` | 2h | Fresh clone runs from README alone |
| 8 | Demo video + Devpost submission | 2h | Submitted with >2h to spare |

---

## 6. Step 0 — do these first, in this order

1. **Backblaze B2** — create the bucket with these exact settings:
   - Files in Bucket: **Private**. B2 charges $1 (or requires payment history) for *public*
     buckets as anti-hotlinking protection; private is free on the 10GB tier. This is also
     the correct design — see "Asset delivery" below.
   - Default Encryption: **Enable** (SSE-B2).
   - Object Lock: **Enable** — *irreversible after creation.* Enabling it does **not** lock
     anything by default; retention is applied per-object, and we apply it only to `attest/`
     manifests. Dev cleanup is unaffected.

   Then grab `B2_KEY_ID` / `B2_APP_KEY` and note the region (e.g. `us-east-005`) — a wrong
   region surfaces as a confusing 403, not a redirect.

   **Asset delivery on a private bucket.** Genblaze rejects `URLPolicy.PRESIGNED` at *sink*
   construction — manifests must never carry SigV4 URLs, since credentials decay before the
   manifest does and that breaks provenance. The intended split, confirmed in source:

   | Purpose | Call | Lifetime |
   |---|---|---|
   | Persisted in manifest | `backend.get_durable_url(key)` | forever, credential-free |
   | Manifest URL → key | `backend.key_for_url(url)` | — |
   | Browser delivery | `backend.get_url(key, expires_in=3600, policy=PRESIGNED)` | short-lived |

   So the app adds `GET /api/assets/sign?url=…` which inverts the durable URL to a key and
   mints a presigned URL on demand. **Assets are never world-readable.** For a compliance
   product this is the right posture, and it's a stronger "Production Readiness" answer than
   a public bucket would have been.
2. **NVIDIA** — `build.nvidia.com`, free, no credit card. `NVIDIA_API_KEY` (`nvapi-…`).
   One key covers image + video + TTS + music + vision chat. Load-bearing.
3. **Google AI Studio** — `aistudio.google.com/apikey`, free tier. `GEMINI_API_KEY`.
   **Required, not optional**, now that GMI is out — it is our only cross-provider fallback.
4. **Featherless** — confirmed Chat plan (DeepSeek / Kimi / GLM, 32K ctx, 4 concurrent,
   hackathon 100% off). Text-only → planner + text/policy judge. Vision judging goes to
   NVIDIA Nemotron VL, not Featherless.
5. `pip install "genblaze[all]"` and run `examples/quickstart.py` against your bucket.

---

## 7. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| No media key → totally blocked | — | NVIDIA free key is step 0.2. Non-negotiable. |
| **NVIDIA is now the sole media provider** (GMI credits closed) | **High** | Google AI Studio key as cross-provider fallback for image + vision judge. Video is opt-in and degrades to a still-image ad if Cosmos fails. Demo mode (`MockProvider`) is the final backstop. |
| Bucket created without Object Lock | Medium | Called out in step 0.1. Recreating is cheap *if caught early*. |
| Private bucket → assets not directly loadable | Resolved | `GET /api/assets/sign` mints presigned URLs at read time; manifests keep durable URLs. Better posture than public. |
| B2 free-tier egress limits during judging | Low | Assets are small (images + short clips); frontend caches signed URLs for their lifetime rather than re-signing per render. |
| Video gen slow (60–300s) / costly | High | Video opt-in, short durations, pre-seeded showcase runs, image-first default. |
| Render free tier: 512MB RAM + cold starts; ffmpeg compositing may OOM | Medium | Test early (phase 6, not phase 8). Upgrade to Starter ($7) if it OOMs — cheap insurance on a $7k prize. |
| Genblaze API drift vs docs | Low-Med | Repo cloned locally to scratchpad; read real source, not blog posts. Several docs already proved stale. |
| Scope creep eats the demo video | High | Phase 8 is fixed. If we're behind at hour 26, we ship what works and cut the register/dashboard. |

---

## 8. Open decisions

- **Name** — Hallmark vs Assay vs Cachet.
- **Featherless model slug** for planner + judge (does your plan include a vision-capable model?).
- **Tenant model** — single demo tenant vs. simple email-keyed tenants. Recommend single tenant
  with `tenant_id` plumbed through, so multi-tenancy is *visible in the architecture* without
  building auth.

---

## Appendix — verified facts

Confirmed by reading source / primary docs, not summaries:

- `genblaze_openai.chat()` accepts `base_url` and `response_format` → Featherless works. *(chat.py:122)*
- `ObjectLockConfig(retain_until, mode="GOVERNANCE"|"COMPLIANCE")` exported from `genblaze_core`;
  **B2 bucket must have Object Lock enabled at creation.** *(storage/base.py:29-53)*
- `MockProvider`, `MockVideoProvider`, `MockAudioProvider` are exported from `genblaze_core` → demo mode is real.
- `Pipeline.ingest(assets, source, source_metadata, sink, name)` exists for non-generative provenance.
- `AgentLoop(build_pipeline, evaluator, max_iterations)` auto-calls `from_result()` → `parent_run_id` chain.
- `KeyStrategy.HIERARCHICAL` / `.CONTENT_ADDRESSABLE`; `for_backblaze()` reads `B2_BUCKET`/`B2_REGION` too.
- `EmbedPolicy(prompt_visibility, embed_mode="full"|"pointer"|"none", include_params, include_seed)`.
- Handlers: `Mp4Handler`, `PngHandler`, `JpegHandler`, `WebpHandler`, `Mp3Handler`, `WavHandler`,
  `AacHandler`, `FlacHandler`, `SidecarHandler` + `get_handler(mime_type)`.
- Manifest `verify()` returns **False for URL-only assets** — assets must flow through
  `ObjectStorageSink` to be hash-covered. Our verify portal depends on this working correctly.
- GMI audio models are all flagged `suspected_dead` in the model matrix → **do not build the
  audio path on GMI.** NVIDIA Riva/Fugatto or ElevenLabs instead.
- `sora-2`, `veo3-fast`, `vidu-q1`, `kling-text2video-v2.1-master`, `minimax-hailuo-2.3-fast`
  also carry `suspected_dead` flags. Avoid as primaries.
- EU AI Act Art. 50 applies from 2 Aug 2026; machine-readable marking deadline extended to
  2 Dec 2026 for systems already on market (AI Omnibus, May 2026).
