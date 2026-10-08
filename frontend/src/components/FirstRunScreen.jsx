import { useState } from "react";

function Door({ title, marker, markerColor, markerBg, children, action }) {
  return (
    <div className="panel" style={{ flex: "1 1 260px", minWidth: 240, display: "flex", flexDirection: "column" }}>
      <h2 style={{ fontSize: 16 }}>{title}</h2>
      <span className="badge" style={{ background: markerBg, color: markerColor, alignSelf: "flex-start", marginBottom: 8 }}>
        {marker}
      </span>
      <p style={{ fontSize: 13, color: "#c7ccd4", flex: 1 }}>{children}</p>
      {action}
    </div>
  );
}

export default function FirstRunScreen({ status, onChooseRecordedDay, onChooseSafeMode, onChooseLiveAgent, onSkip }) {
  const keyConfigured = !!status?.key_configured;
  const [showKeyHelp, setShowKeyHelp] = useState(false);

  return (
    <div className="panel">
      <h2>An AI agent that runs a renewable plant, with every decision checked</h2>
      <p style={{ fontSize: 14, color: "#c7ccd4" }}>
        Every 15 minutes it decides what to do with the batteries, the grid connection and any
        surplus generation. A separate evaluator then checks that decision against safety
        rules it never sees. Pick a way in.
      </p>

      <div className="row" style={{ flexWrap: "wrap", gap: 12, marginTop: 12 }}>
        <Door
          title="Watch a recorded run"
          marker="No key needed"
          markerColor="#8fb4ff"
          markerBg="#1f2b45"
          action={<button onClick={onChooseRecordedDay}>Open the recorded day</button>}
        >
          A full day — 96 fifteen-minute intervals — already run against the live model and
          recorded. Loads in seconds, with every decision and verdict intact.
        </Door>

        <Door
          title="Run it in safe mode"
          marker="No key needed"
          markerColor="#8fb4ff"
          markerBg="#1f2b45"
          action={<button onClick={onChooseSafeMode}>Build a scenario in Safe mode</button>}
        >
          The deterministic fallback controller decides instead of the model, and the
          evaluator checks it live. Build your own scenario and get a real verdict.
        </Door>

        <Door
          title="Run the live agent"
          marker="Your own key"
          markerColor="#f5a666"
          markerBg="#3a2a1f"
          action={
            keyConfigured ? (
              <button onClick={onChooseLiveAgent}>Go to the live agent</button>
            ) : (
              <>
                <button onClick={() => setShowKeyHelp((v) => !v)}>How do I add a key?</button>
                {showKeyHelp && (
                  <p style={{ fontSize: 12, color: "#9aa4b2", marginTop: 8 }}>
                    No key is configured on this machine. Add <code>GEMINI_API_KEY</code> to{" "}
                    <code>backend/.env</code> (a free key, no credit card, from{" "}
                    <code>aistudio.google.com</code>), then restart the app. The key stays on
                    your machine and is sent nowhere but Google — it is never read by, or
                    entered into, this browser.
                  </p>
                )}
              </>
            )
          }
        >
          {keyConfigured ? (
            <>A Gemini key is configured on this machine. Watch the model decide in real time.</>
          ) : (
            <>Run the live agent — needs your own Gemini key in <code>backend/.env</code>. The key
              stays on your machine and is sent nowhere but Google.</>
          )}
        </Door>
      </div>

      <p style={{ fontSize: 13, color: "#9aa4b2", marginTop: 12 }}>
        Nothing here needs an API key. A key only adds live model runs — everything else,
        including the evaluator and all the example days, runs on your machine.
      </p>
      <p style={{ fontSize: 13 }}>
        <button onClick={onSkip} style={{ font: "inherit", color: "#8fb4ff", background: "none", border: "none", cursor: "pointer", padding: 0 }}>
          Skip to the full controls
        </button>
      </p>
    </div>
  );
}
