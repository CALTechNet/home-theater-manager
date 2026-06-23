import { useState } from "react";
import Schedule from "./tabs/Schedule.jsx";
import Media from "./tabs/Media.jsx";
import NowShowing from "./tabs/NowShowing.jsx";
import Ticketing from "./tabs/Ticketing.jsx";
import Settings from "./tabs/Settings.jsx";
import HeaderClock from "./components/HeaderClock.jsx";

const TABS = [
  ["schedule", "Schedule"],
  ["media", "Media"],
  ["now", "Now Showing"],
  ["ticketing", "Ticketing"],
  ["settings", "Settings"],
];

export default function App() {
  const [tab, setTab] = useState("schedule");
  // Lets Schedule -> "print tickets" jump to the Ticketing tab for a showing.
  const [ticketShowingId, setTicketShowingId] = useState(null);

  const goTicketing = (showingId) => {
    setTicketShowingId(showingId);
    setTab("ticketing");
  };

  return (
    <>
      <header className="topbar">
        <h1>🎬 Home Theater Manager</h1>
        <nav className="tabs">
          {TABS.map(([key, label]) => (
            <button
              key={key}
              className={tab === key ? "active" : ""}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </nav>
        <div className="topbar-right">
          <HeaderClock />
        </div>
      </header>
      <main className={tab === "media" ? "main-wide" : undefined}>
        {tab === "schedule" && <Schedule onPrintTickets={goTicketing} />}
        {tab === "media" && <Media />}
        {tab === "now" && <NowShowing />}
        {tab === "ticketing" && <Ticketing initialShowingId={ticketShowingId} />}
        {tab === "settings" && <Settings />}
      </main>
    </>
  );
}
