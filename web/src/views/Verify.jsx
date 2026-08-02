import { useRef, useState } from "react";
import { api, fmtTime } from "../api.js";

export default function Verify() {
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [name, setName] = useState("");
  const [over, setOver] = useState(false);
  const input = useRef(null);

  async function handle(file) {
    if (!file) return;
    setName(file.name);
    setBusy(true);
    setRes(null);
    try {
      setRes(await api.verify(file));
    } catch (err) {
      setRes({ found_manifest: false, message: String(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="panel">
        <h2 className="sec">Verify provenance</h2>
        <p className="muted" style={{ marginTop: 0, fontSize: 14 }}>
          Drop any file Hallmark produced. The provenance manifest travels <em>inside</em> the
          file, so it can be checked offline — no lookup, no trust in this website required.
        </p>
        <div
          className={`drop ${over ? "over" : ""}`}
          onClick={() => input.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); handle(e.dataTransfer.files?.[0]); }}
        >
          <strong>{busy ? "Checking…" : "Drop a PNG or MP4 here"}</strong>
          <span>{name || "or click to choose a file"}</span>
          <input
            ref={input} type="file" hidden accept="image/png,image/jpeg,video/mp4"
            onChange={(e) => handle(e.target.files?.[0])}
          />
        </div>
      </div>

      {res && (
        <div className="panel">
          <div className="row" style={{ marginBottom: 16 }}>
            {res.found_manifest ? (
              <span className={`pill ${res.verified ? "ok" : "no"}`}>
                {res.verified ? "✓ Verified" : "✗ Integrity check failed"}
              </span>
            ) : (
              <span className="pill no">No manifest found</span>
            )}
            {res.source !== "none" && res.found_manifest && <span className="pill">{res.source}</span>}
          </div>

          <p className="muted" style={{ marginTop: 0 }}>{res.message}</p>

          {res.found_manifest && (
            <dl className="kv" style={{ marginTop: 18 }}>
              <dt>Manifest hash</dt><dd className="hash">{res.canonical_hash || "—"}</dd>
              <dt>Run ID</dt><dd className="hash">{res.run_id || "—"}</dd>
              {res.parent_run_id && (<><dt>Parent run</dt><dd className="hash">{res.parent_run_id}</dd></>)}
              <dt>Pipeline</dt><dd>{res.pipeline || "—"}</dd>
              <dt>Created</dt><dd>{fmtTime(res.created_at)}</dd>
              <dt>Providers</dt><dd>{res.providers?.join(", ") || "—"}</dd>
              <dt>Models</dt><dd>{res.models?.join(", ") || "—"}</dd>
              {res.disclosure && (<><dt>Disclosure</dt><dd>{res.disclosure}</dd></>)}
              <dt>File sha256</dt><dd className="hash">{res.file_sha256 || "—"}</dd>
            </dl>
          )}
        </div>
      )}

      <div className="panel">
        <h2 className="sec">Why this matters</h2>
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>
          Since <b style={{ color: "var(--gold)" }}>2 August 2026</b>, EU AI Act Article 50 requires
          AI-generated audio, image, and video to be marked in a machine-readable format and
          detectable as AI-generated. Hallmark satisfies both halves: a visible disclosure burned
          onto the creative, and a SHA-256-bound provenance manifest embedded in the file itself —
          with an immutable copy retained under Object Lock on Backblaze B2.
        </p>
      </div>
    </div>
  );
}
