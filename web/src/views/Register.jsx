import { useEffect, useState } from "react";
import { api, fmtTime, shortHash } from "../api.js";

export default function Register() {
  const [data, setData] = useState(null);

  useEffect(() => {
    api.register().then(setData).catch(() => setData({ rows: [], total_assets: 0 }));
  }, []);

  if (!data)
    return <div className="panel"><div className="empty"><span className="spin" /> Building register…</div></div>;

  return (
    <div className="stack">
      <div className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <h2 className="sec" style={{ marginBottom: 6 }}>AI disclosure register</h2>
            <p className="muted" style={{ margin: 0, fontSize: 13.5, maxWidth: 620 }}>
              {data.regulation || "EU AI Act Article 50"} — one row per delivered asset, with the
              model, manifest hash, verification state, and Object Lock retention date. This is the
              evidence pack a compliance officer asks for.
            </p>
          </div>
          <a href="/api/register.csv" download>
            <button className="ghost">Download CSV</button>
          </a>
        </div>
        <div className="row" style={{ marginTop: 14 }}>
          <span className="pill">{data.total_assets} asset(s)</span>
          <span className="pill ok">{data.verified_assets} verified</span>
          <span className="pill">generated {fmtTime(data.generated_at)}</span>
        </div>
      </div>

      <div className="panel">
        {data.rows?.length ? (
          <div className="scroll-x">
            <table className="reg">
              <thead>
                <tr>
                  <th>Created</th><th>Brand</th><th>Campaign</th><th>Asset</th>
                  <th>Format</th><th>Manifest hash</th><th>Verified</th><th>Retained until</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.asset_id}>
                    <td className="muted" style={{ whiteSpace: "nowrap" }}>{fmtTime(r.created_at)}</td>
                    <td>{r.brand}</td>
                    <td>{r.campaign}</td>
                    <td>{r.asset_kind}</td>
                    <td>{r.format || "—"}</td>
                    <td className="hash">{shortHash(r.manifest_hash, 16)}</td>
                    <td>
                      <span className={`pill ${r.verified === "true" ? "ok" : "no"}`}>
                        {r.verified === "true" ? "yes" : "no"}
                      </span>
                    </td>
                    <td className="muted" style={{ whiteSpace: "nowrap" }}>
                      {r.retain_until ? String(r.retain_until).slice(0, 10) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty">No delivered assets yet.</div>
        )}
      </div>
    </div>
  );
}
