import { useEffect, useState } from "react";
import { api, fmtTime, shortHash } from "../api.js";
import Asset from "../components/Asset.jsx";

export default function Library() {
  const [runs, setRuns] = useState(null);
  const [open, setOpen] = useState(null);

  useEffect(() => {
    api.listRuns().then(setRuns).catch(() => setRuns([]));
  }, []);

  if (runs === null)
    return <div className="panel"><div className="empty"><span className="spin" /> Loading from B2…</div></div>;

  if (runs.length === 0)
    return (
      <div className="panel">
        <div className="empty">
          No runs yet. Generate one in the Studio — every run is indexed in your B2 bucket,
          so this list survives restarts with no database.
        </div>
      </div>
    );

  return (
    <div className="stack">
      <p className="muted" style={{ margin: 0, fontSize: 13.5 }}>
        {runs.length} run(s), read straight from Backblaze B2. B2 is the system of record —
        there is no separate database.
      </p>
      {runs.map((r) => (
        <div key={r.run_id} className="panel">
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: 16 }}>{r.campaign_title || "Untitled"}</div>
              <div className="muted" style={{ fontSize: 13 }}>
                {r.brand_name} · {fmtTime(r.created_at)} · {r.assets.length} asset(s)
              </div>
            </div>
            <div className="row">
              <span className={`pill ${r.verified ? "ok" : "no"}`}>{r.verified ? "✓ verified" : r.status}</span>
              {r.retain_until && <span className="pill gold">locked → {String(r.retain_until).slice(0, 10)}</span>}
              <button className="ghost" onClick={() => setOpen(open === r.run_id ? null : r.run_id)}>
                {open === r.run_id ? "Hide" : "Details"}
              </button>
            </div>
          </div>

          <div className="gal">
            {r.assets.map((a) => <Asset key={a.asset_id} asset={a} />)}
          </div>

          {open === r.run_id && (
            <dl className="kv" style={{ marginTop: 18 }}>
              <dt>Run ID</dt><dd className="hash">{r.run_id}</dd>
              <dt>Manifest hash</dt><dd className="hash">{r.canonical_hash}</dd>
              <dt>Manifest URI</dt><dd className="hash">{r.manifest_uri}</dd>
              <dt>Attest prefix</dt><dd className="hash">{r.attest_uri}</dd>
              <dt>Judge iterations</dt><dd>{r.iterations}</dd>
              <dt>Lineage</dt>
              <dd className="hash">{r.lineage?.map((x) => shortHash(x, 8)).join(" → ") || "—"}</dd>
              {r.verdict && (
                <>
                  <dt>Brand issues</dt><dd>{r.verdict.brand_issues?.join("; ") || "none"}</dd>
                  <dt>Policy issues</dt><dd>{r.verdict.policy_issues?.join("; ") || "none"}</dd>
                </>
              )}
            </dl>
          )}
        </div>
      ))}
    </div>
  );
}
