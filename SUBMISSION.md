# Devpost submission pack — Hallmark

Copy/paste material for the submission form, plus a shot-by-shot demo script.

---

## Tagline

Governed AI creative: generate ad campaigns that can prove where they came from.

## Links

- **Live app:** https://hallmark-64ts.onrender.com
- **Repo:** https://github.com/23f2001033/b2genblaze

## Built with (25 tags)

```
genblaze, backblaze-b2, nvidia-nim, featherless-ai, elevenlabs, deepseek,
flux, python, fastapi, react, docker, ffmpeg, vite, boto3, s3, uvicorn,
pillow, javascript, server-sent-events, render, object-lock, provenance,
eu-ai-act, generative-ai, sha-256
```

The two that matter most for judging are `genblaze` and `backblaze-b2` — the
sponsor technologies scored directly by the criteria.

---

## Inspiration

**EU AI Act Article 50 became applicable on 2 August 2026 — the day we started building.**
It requires AI-generated image, audio and video to be marked in a machine-readable format
and detectable as AI-generated.

Every AI creative tool we looked at hands you a file and, at best, a prompt history.
Neither survives a compliance review. Meanwhile Genblaze already emits a canonical,
SHA-256-bound manifest that can be embedded directly into an MP4 or PNG, and Backblaze B2
has Object Lock. Those two things are almost exactly what the regulation asks for — nobody
had connected them. That gap is Hallmark.

## What it does

You write a one-line brief and a brand kit (tone, visual rules, banned claims, required
disclosure). Hallmark then:

1. **Plans** the campaign into structured scenes with an LLM.
2. **Generates** keyframes per scene and per format.
3. **Judges** its own output — a vision model scores brand adherence, a text model checks
   copy for banned claims. Failures are **retried with the critique fed back into the
   prompt**, and each attempt is linked by `parent_run_id`, so the reasoning trail is part
   of the provenance.
4. **Discloses** — burns the required AI-disclosure onto the creative.
5. **Composes** an MP4 ad from the approved stills with ElevenLabs voiceover.
6. **Attests** — embeds the manifest *inside* each delivered file and writes an immutable
   copy to B2 under Object Lock.
7. **Verifies** — anyone can drop a file into the public `/verify` page and read its full
   lineage offline. No lookup, no need to trust our website.
8. **Exports** the Article 50 disclosure register as CSV.

## How we built it

FastAPI + React in one Docker container, with all Genblaze usage deliberately confined to a
single `pipelines.py` so the orchestration boundary is inspectable. B2 is the system of
record — run records live in the bucket as JSON, so the Library and Register survive
restarts with **no database at all**.

The judge loop is Genblaze's `AgentLoop` with a `CallableEvaluator`; the planner is a custom
`SyncProvider` that wraps `chat(base_url=…)` so the LLM call becomes a real manifest'd Step
rather than an untracked side call.

## Challenges we ran into

- **The free NVIDIA NIM catalog is much smaller than the docs suggest.** We probed it
  directly: only `flux.1-dev` was reachable. Cosmos video, Riva TTS, Fugatto, SDXL and
  SD3.5 all returned 404, and `flux.1-schnell` hung indefinitely. So there is no video
  model in this stack — the ad is composed from generated stills with ffmpeg instead.
  Honest, fast, and every frame is still provenance-covered.
- **Genblaze rejects presigned URLs in manifests** (they decay before the manifest does).
  On a private bucket that means durable URLs aren't browser-loadable, so the app mints
  short-lived signed URLs at read time. This turned out to be the better architecture.
- **`ObjectStorageSink` never forwards `allowed_roots` to `AssetTransfer`**, so `file://`
  assets can only be read from temp roots. All provider scratch moved under `TMPDIR`.
- **`FFmpegTransform` declares only VIDEO/AUDIO modalities**, so the image disclosure
  overlay uses Pillow while the video path stays a real pipeline step.
- **`zoompan` silently defaults to 1280x720**, which broke the Ken Burns crop until we
  pinned `s=`.
- **Hugging Face Spaces now requires PRO for Docker Spaces**, so we moved the deploy to Render.

## Accomplishments we're proud of

The verify portal. Drop a file in and it reads its own provenance out of the bytes — no
database lookup, no trust in our server. And the governance is real, not decorative: the
copy judge caught a genuine borderline claim during testing and rejected it.

## What we learned

Provenance is only worth anything if it is a *side effect* of the normal workflow. The
moment it becomes a separate step someone has to remember, it stops happening.

## What's next

Ed25519 manifest signing (Genblaze trust mode 2) to prove *who* generated an asset, not
just that it is unmodified; C2PA interop; and B2 Event Notifications to trigger
verification automatically on upload.

---

## Providers and models used

| Purpose | Provider | Model |
|---|---|---|
| Campaign planning | Featherless AI | `deepseek-ai/DeepSeek-V3.2` |
| Copy / policy judge | Featherless AI | `deepseek-ai/DeepSeek-V3.2` |
| Image generation | NVIDIA NIM | `black-forest-labs/flux.1-dev` |
| Vision brand judge | NVIDIA NIM | `nvidia/nemotron-nano-12b-v2-vl` |
| Vision judge fallback | Google | `gemini-2.5-flash` |
| Voiceover | ElevenLabs | `eleven_flash_v2_5` |
| Storage | Backblaze B2 | S3-compatible, `us-east-005` |

## How we use Genblaze

Twelve distinct SDK surfaces, not one `.step()` call:
`Pipeline` / `.step()` / `.metadata()`; `AgentLoop` + `CallableEvaluator` +
`EvaluationResult`; `parent_run_id` lineage; a custom `SyncProvider` that makes the planner
LLM a manifest'd Step; `Pipeline.ingest()` for non-generative delivery provenance;
`ObjectStorageSink` + `KeyStrategy.HIERARCHICAL`; `ObjectLockConfig`; `FFmpegTransform`;
`Mp4Handler` / `PngHandler` embed + extract; `Manifest.verify()`; `Modality` / `StepType` /
`PromptVisibility`; and `MockProvider`-style stubs for a zero-spend demo mode.

Cross-**provider** failover (NVIDIA → Google) is implemented in our own layer, because
Genblaze's `fallback_models=` only retries slugs within a single provider.

## How we use Backblaze B2

B2 is the system of record, not a file dump. Run records are JSON objects in the bucket, so
the Library and Register need no database. Attestation manifests and stamped deliverables
are written with `GOVERNANCE`-mode Object Lock, so the audit trail cannot be silently
rewritten. The bucket is private: manifests carry durable credential-free URLs while
delivery uses short-lived presigned URLs, so assets are never world-readable. Assets are
laid out hierarchically per `{tenant}/{date}/{run_id}/`, with per-part SHA-256 verified
server-side on upload.

---

## Demo video script (~3 min)

Record at 1920x1080. Have the app open and one run already in the Library.

| Time | Shot | Say |
|---|---|---|
| 0:00–0:20 | Hero page, scroll to the Article 50 banner | "On 2 August 2026 — three days ago — EU AI Act Article 50 became applicable. AI-generated media must now be marked machine-readably and be detectable as AI-generated. Hallmark makes that evidence a side effect of generating." |
| 0:20–0:40 | Studio: brief + brand kit; point at Banned claims | "This is the brand kit. Tone, visual rules, and banned claims. This isn't decoration — it's the governance input the judges enforce." |
| 0:40–1:15 | Click Generate; let the event stream run | "One brief becomes a plan, then keyframes. A vision model scores each image against the brand rules and a text model checks the copy. Anything that fails is retried with the critique fed back into the prompt — and every attempt is linked in the provenance chain." |
| 1:15–1:35 | Results appear; zoom on the burned-in disclosure | "Approved creative, with the disclosure burned on — that's the human-readable half of Article 50." |
| 1:35–1:50 | Play the composed MP4 with voiceover | "The ad is composed from the approved stills with an ElevenLabs voiceover — so every frame is provenance-covered." |
| 1:50–2:20 | **Verify tab — drag the MP4 in** | "Here's the part that matters. I'm dropping that file into the public verifier. The manifest is *inside* the file — provider, model, run ID, hash. Verified, offline. No database lookup, no trusting my website." |
| 2:20–2:35 | Drop an unrelated JPG → "No manifest found" | "And a file we didn't produce is correctly rejected." |
| 2:35–2:50 | Library, then Register + Download CSV | "Every run is indexed in B2 — there's no database. And this is the Article 50 disclosure register: every asset, its model, hash, and Object Lock retention date." |
| 2:50–3:00 | B2 console showing the locked object | "All of it retained immutably on Backblaze B2 under Object Lock." |

**Do not skip the verify shot.** It is the single most convincing 30 seconds in the demo.
