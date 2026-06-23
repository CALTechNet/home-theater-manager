import { useEffect, useState } from "react";

// Live wall clock for the top bar (hour : minute : second), 24-hour.
export default function HeaderClock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const time = now.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });

  return (
    <div className="topbar-clock" title={now.toLocaleDateString()}>
      {time}
    </div>
  );
}
