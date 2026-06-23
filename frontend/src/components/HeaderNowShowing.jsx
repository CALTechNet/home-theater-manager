import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

// Compact "Now Showing" indicator for the top bar: shows the currently playing
// show from any tab. Polls playback state and degrades quietly to "Idle" when
// nothing is playing or the playback service is unavailable.
export default function HeaderNowShowing() {
  const [state, setState] = useState(null);
  const [title, setTitle] = useState(null);

  const poll = useCallback(async () => {
    try {
      const s = await api.playbackState();
      setState(s);
      if (s && s.showing_id) {
        try {
          const showing = await api.getShowing(s.showing_id);
          setTitle(showing?.title || `#${s.showing_id}`);
        } catch {
          setTitle(`#${s.showing_id}`);
        }
      } else {
        setTitle(null);
      }
    } catch {
      setState(null);
      setTitle(null);
    }
  }, []);

  useEffect(() => {
    poll();
    const t = setInterval(poll, 3000);
    return () => clearInterval(t);
  }, [poll]);

  const live = state?.state === "playing" || state?.state === "paused";

  if (!live) {
    return (
      <div className="topbar-now idle" title="No show is playing">
        <span className="dot" />
        <span className="label">Idle</span>
      </div>
    );
  }

  return (
    <div className="topbar-now" title={title ? `Now showing: ${title}` : "Now showing"}>
      <span className="dot live" />
      <span className="label">Now Showing</span>
      <span className="now-title">{title || "—"}</span>
    </div>
  );
}
