import { useEffect, useState } from "react";
import { api } from "./api.js";
import Studio from "./views/Studio.jsx";
import Library from "./views/Library.jsx";
import Verify from "./views/Verify.jsx";
import Register from "./views/Register.jsx";

const TABS = [
  ["studio", "Studio"],
  ["library", "Library"],
  ["verify", "Verify"],
  ["register", "Register"],
];

export default function App() {
  const [tab, setTab] = useState("studio");
  const [health, setHealth] = useState(null);
  const [bump, setBump] = useState(0);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  const cap = health?.capabilities;

  return (
    <>
      <header className="top">
        <div className="top-inner">
          <div className="brand">
            <div className="mark">H</div>
            <div>
              Hallmark
              <br />
              <small>governed AI creative</small>
            </div>
          </div>
          <nav className="tabs">
            {TABS.map(([k, label]) => (
              <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
                {label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <div className="wrap">
        {tab === "studio" && (
          <section className="hero">
            <h1>
              AI creative that can <em>prove where it came from</em>.
            </h1>
            <p>
              Describe a campaign. Hallmark plans it, generates the imagery, judges its own output
              against your brand and policy rules, retries what fails, then stamps every approved
              asset with a verifiable provenance record — stored immutably on Backblaze B2.
            </p>
            <div className="reg-note">
              <span>⚖️</span>
              <div>
                <b>EU AI Act Article 50 became applicable on 2 August 2026.</b> AI-generated image,
                audio and video must be marked in a machine-readable format and be detectable as
                AI-generated. Hallmark produces that evidence as a side effect of generating.
              </div>
            </div>
            {cap && (
              <div className="row" style={{ marginTop: 18 }}>
                <span className={`pill ${cap.storage_b2 ? "ok" : "no"}`}>B2 {cap.bucket || "—"}</span>
                <span className={`pill ${cap.planner_featherless ? "ok" : "no"}`}>Featherless planner</span>
                <span className={`pill ${cap.image_nvidia ? "ok" : "no"}`}>NVIDIA imagery</span>
                <span className={`pill ${cap.vision_judge ? "ok" : "no"}`}>Vision judge</span>
                <span className={`pill ${cap.tts_elevenlabs ? "ok" : ""}`}>
                  {cap.tts_elevenlabs ? "Voiceover" : "Voiceover off"}
                </span>
                {cap.demo_mode && <span className="pill gold">demo mode</span>}
              </div>
            )}
          </section>
        )}

        {tab !== "studio" && <div style={{ height: 28 }} />}

        {tab === "studio" && <Studio onDone={() => setBump((b) => b + 1)} />}
        {tab === "library" && <Library key={bump} />}
        {tab === "verify" && <Verify />}
        {tab === "register" && <Register key={bump} />}
      </div>
    </>
  );
}
