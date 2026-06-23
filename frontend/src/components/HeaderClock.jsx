import { useEffect, useState } from "react";
import { api } from "../api.js";

// Live wall clock for the top bar (hour : minute : second). 12-hour (AM/PM) or
// 24-hour per the Settings "time_format" option; polled so changes show live.
export default function HeaderClock() {
  const [now, setNow] = useState(() => new Date());
  const [hour12, setHour12] = useState(true); // default AM/PM

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    let active = true;
    const loadFormat = () =>
      api
        .getSettings()
        .then((s) => active && setHour12(s.time_format !== "24h"))
        .catch(() => {});
    loadFormat();
    const t = setInterval(loadFormat, 15000);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, []);

  const time = now.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12,
  });

  return (
    <div className="topbar-clock" title={now.toLocaleDateString()}>
      {time}
    </div>
  );
}
