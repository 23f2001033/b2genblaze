import { useEffect, useState } from "react";
import { signedUrl } from "../api.js";

export default function Asset({ asset, showCap = true }) {
  const [src, setSrc] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    signedUrl(asset.durable_url).then((u) => {
      if (alive) u ? setSrc(u) : setFailed(true);
    });
    return () => {
      alive = false;
    };
  }, [asset.durable_url]);

  return (
    <div className="card">
      <div className="media" style={asset.fmt === "9:16" ? { aspectRatio: "9/16" } : undefined}>
        {failed ? (
          <span className="muted" style={{ fontSize: 12 }}>unavailable</span>
        ) : !src ? (
          <span className="spin" />
        ) : asset.kind === "video" ? (
          <video src={src} controls playsInline preload="metadata" />
        ) : (
          <img src={src} alt={asset.label || "generated creative"} loading="lazy" />
        )}
      </div>
      {showCap && (
        <div className="cap">
          <span title={asset.label} style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {asset.label || asset.kind}
          </span>
          <span className="pill">{asset.fmt || asset.kind}</span>
        </div>
      )}
    </div>
  );
}
