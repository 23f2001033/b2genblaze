import { useRef, useState } from "react";
import { api, shortHash } from "../api.js";
import Asset from "../components/Asset.jsx";

const FORMATS = ["1:1", "9:16", "16:9"];
const STAGES = [
  ["plan", "Plan"],
  ["scene", "Keyframes"],
  ["judge", "Judge"],
  ["video", "Compose"],
  ["attest", "Attest"],
];

const PRESET = {
  brief: "Launch a matte steel insulated water bottle for weekend hikers.",
  name: "Northwind",
  tone: "calm, precise, outdoorsy",
  rules: "natural daylight, no visible text or logos, matte surfaces",
  banned: "guaranteed, unbreakable, lasts forever",
  disclosure: "Contains AI-generated imagery.",
};

export default function Studio({ onDone }) {
  const [f, setF] = useState(PRESET);
  const [formats, setFormats] = useState(["1:1"]);
  const [scenes, setScenes] = useState(2);
  const [video, setVideo] = useState(true);

  const [running, setRunning] = useState(false);
  const [events, setEvents] = useState([]);
  const [stage, setStage] = useState(null);
  const [doneStages, setDoneStages] = useState([]);
  const [result, setResult] = useState(null);
  const t0 = useRef(0);

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  function toggleFormat(x) {
    setFormats((cur) => (cur.includes(x) ? cur.filter((c) => c !== x) : [...cur, x]));
  }

  function push(name, data, kind = "") {
    const t = ((Date.now() - t0.current) / 1000).toFixed(1);
    setEvents((cur) => [...cur, { t, name, data, kind }]);
  }

  async function start() {
    if (running || formats.length === 0) return;
    setRunning(true);
    setEvents([]);
    setResult(null);
    setStage(null);
    setDoneStages([]);
    t0.current = Date.now();

    const payload = {
      brief: f.brief,
      brand: {
        name: f.name,
        tone: f.tone,
        palette: [],
        visual_rules: f.rules.split(",").map((s) => s.trim()).filter(Boolean),
        banned_claims: f.banned.split(",").map((s) => s.trim()).filter(Boolean),
        required_disclosure: f.disclosure,
      },
      scene_count: Number(scenes),
      formats,
      make_video: video,
      tenant_id: "demo",
    };

    let stream_id;
    try {
      ({ stream_id } = await api.startRun(payload));
    } catch (err) {
      push("error", String(err), "err");
      setRunning(false);
      return;
    }

    const es = new EventSource(`/api/runs/${stream_id}/events`);
    const mark = (key) => {
      setStage(key);
      setDoneStages((cur) => {
        const i = STAGES.findIndex(([k]) => k === key);
        return STAGES.slice(0, Math.max(0, i)).map(([k]) => k);
      });
    };

    const on = (name, fn) =>
      es.addEventListener(name, (e) => {
        let d = {};
        try { d = JSON.parse(e.data); } catch { /* keepalive */ }
        fn(d);
      });

    on("run.started", (d) => push("run.started", `run ${d.run_id}`));
    on("plan.started", (d) => { mark("plan"); push("plan.started", d.model); });
    on("plan.completed", (d) => push("plan.completed", `“${d.title}” — ${d.scenes?.length || 0} scene(s)`, "ok"));
    on("scene.started", (d) => { mark("scene"); push("scene.started", `#${d.scene} ${d.fmt} — ${d.headline || ""}`); });
    on("scene.retry", (d) => push("scene.retry", `#${d.scene}: ${d.note}`, "err"));
    on("scene.judged", (d) => { mark("judge"); push("scene.judged", `#${d.scene} score ${d.score}${d.issues?.length ? ` — ${d.issues.join("; ")}` : ""}`, d.passed ? "ok" : "err"); });
    on("scene.completed", (d) => push("scene.completed", `#${d.scene} ${d.fmt} after ${d.iterations} iter`, "ok"));
    on("scene.failed", (d) => push("scene.failed", `#${d.scene}`, "err"));
    on("copy.judged", (d) => push("copy.judged", d.issues?.length ? d.issues.join("; ") : `clean (score ${d.score})`, d.passed ? "ok" : "err"));
    on("voice.started", () => push("voice.started", "narration"));
    on("voice.completed", (d) => push("voice.completed", `${d.tracks} track(s)`, "ok"));
    on("video.started", (d) => { mark("video"); push("video.started", `${d.stills} still(s)`); });
    on("video.completed", (d) => push("video.completed", d.file || "ok", "ok"));
    on("video.failed", (d) => push("video.failed", String(d.error || "").slice(0, 120), "err"));
    on("attest.started", (d) => { mark("attest"); push("attest.started", `${d.files} file(s)`); });
    on("attest.completed", (d) => push("attest.completed", `hash ${shortHash(d.hash)} · locked until ${String(d.retain_until).slice(0, 10)}`, "ok"));
    on("attest.warn", (d) => push("attest.warn", `${d.file}: ${d.error}`, "err"));
    on("run.completed", (d) => push("run.completed", `${d.assets} asset(s) attested`, "ok"));
    on("run.failed", (d) => push("run.failed", String(d.error || "").slice(0, 200), "err"));

    on("done", (d) => {
      setDoneStages(STAGES.map(([k]) => k));
      setStage(null);
      setResult(d.run || null);
      setRunning(false);
      es.close();
      if (d.run) onDone?.();
    });

    es.onerror = () => {
      if (!result) push("stream.error", "connection lost", "err");
      setRunning(false);
      es.close();
    };
  }

  return (
    <div className="grid2">
      {/* ---------------- inputs ---------------- */}
      <div className="panel">
        <h2 className="sec">Campaign brief</h2>
        <label className="f">
          <span>What are we advertising?</span>
          <textarea value={f.brief} onChange={set("brief")} />
        </label>

        <h2 className="sec" style={{ marginTop: 22 }}>Brand kit — the governance input</h2>
        <label className="f"><span>Brand name</span><input type="text" value={f.name} onChange={set("name")} /></label>
        <label className="f"><span>Tone</span><input type="text" value={f.tone} onChange={set("tone")} /></label>
        <label className="f"><span>Visual rules (comma separated)</span><input type="text" value={f.rules} onChange={set("rules")} /></label>
        <label className="f"><span>Banned claims — copy is rejected if these appear</span><input type="text" value={f.banned} onChange={set("banned")} /></label>
        <label className="f"><span>Required AI disclosure</span><input type="text" value={f.disclosure} onChange={set("disclosure")} /></label>

        <label className="f">
          <span>Formats</span>
          <div className="chips">
            {FORMATS.map((x) => (
              <div key={x} className={`chip ${formats.includes(x) ? "on" : ""}`} onClick={() => toggleFormat(x)}>{x}</div>
            ))}
          </div>
        </label>

        <div className="row" style={{ marginBottom: 16 }}>
          <label className="f" style={{ marginBottom: 0, flex: 1 }}>
            <span>Scenes</span>
            <select value={scenes} onChange={(e) => setScenes(e.target.value)}>
              {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label className="f" style={{ marginBottom: 0, flex: 1 }}>
            <span>Compose video</span>
            <select value={video ? "yes" : "no"} onChange={(e) => setVideo(e.target.value === "yes")}>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
          </label>
        </div>

        <button className="go" onClick={start} disabled={running || formats.length === 0}>
          {running ? <><span className="spin" /> &nbsp;Generating…</> : "Generate governed creative"}
        </button>
        <p className="muted" style={{ fontSize: 12.5, marginBottom: 0, marginTop: 10 }}>
          Takes ~90s: plan → generate → judge → retry → disclose → compose → attest.
        </p>
      </div>

      {/* ---------------- live + results ---------------- */}
      <div className="stack">
        <div className="panel">
          <h2 className="sec">Pipeline</h2>
          <div className="stages">
            {STAGES.map(([k, label]) => (
              <div key={k} className={`stage ${stage === k ? "active" : ""} ${doneStages.includes(k) ? "done" : ""}`}>
                {label}
              </div>
            ))}
          </div>
          <div className="stream">
            {events.length === 0 && <div className="empty" style={{ padding: 28 }}>No run yet.</div>}
            {events.map((e, i) => (
              <div key={i} className={`ev ${e.kind}`}>
                <span className="t">{e.t}s</span>
                <span className="n">{e.name}</span>
                <span className="d">{typeof e.data === "string" ? e.data : JSON.stringify(e.data)}</span>
              </div>
            ))}
          </div>
        </div>

        {result && result.status === "succeeded" && (
          <div className="panel">
            <h2 className="sec">Attested creative</h2>
            <div className="row" style={{ marginBottom: 14 }}>
              <span className={`pill ${result.verified ? "ok" : "no"}`}>
                {result.verified ? "✓ manifest verified" : "unverified"}
              </span>
              <span className="pill gold">Object Lock → {String(result.retain_until).slice(0, 10)}</span>
              <span className="pill">{result.iterations} judge iteration(s)</span>
              <span className="pill">{result.lineage?.length || 0} linked runs</span>
            </div>
            <div className="hash" style={{ marginBottom: 14 }}>sha256 {result.canonical_hash}</div>
            <div className="gal">
              {result.assets.map((a) => <Asset key={a.asset_id} asset={a} />)}
            </div>
          </div>
        )}

        {result && result.status === "failed" && (
          <div className="panel">
            <h2 className="sec">Run failed</h2>
            <p className="muted" style={{ margin: 0 }}>{result.error}</p>
          </div>
        )}
      </div>
    </div>
  );
}
