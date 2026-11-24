import { useEffect, useState } from "react";

import { DEMO, type Recording, loadRecording } from "./demo";

// Shown on every page of the demo edition, never on the full app. It says what the numbers are.
export function DemoBanner() {
  const [meta, setMeta] = useState<Recording["meta"] | null>(null);
  useEffect(() => {
    if (!DEMO) return;
    loadRecording()
      .then((recording) => setMeta(recording.meta))
      .catch(() => setMeta(null));
  }, []);
  if (!DEMO) return null;
  return (
    <div
      role="note"
      className="mb-6 rounded-xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-200"
    >
      <strong className="font-semibold">DEMO.</strong> No backend runs here. Every number is a real
      response recorded from the Python backend
      {meta ? ` (${meta.recorded_at}, commit ${meta.git})` : ""}, shown with each page&apos;s default
      settings; the data is simulated or public. Research only: not financial advice and not a
      trading system. To run your own jobs, use the desktop app.
    </div>
  );
}
