import { type FormEvent, type ReactNode, useEffect, useState } from "react";

import { getToken, setToken, UNAUTHORIZED_EVENT } from "../api/client";
import { GlassCard } from "../components/GlassCard";

interface TokenGateProps {
  children: ReactNode;
}

// The same bearer-token model prometheus.service.auth.CredentialStore
// already uses (no new auth backend invented): paste in a token
// provisioned via `python -m prometheus.dashboard init-auth` /
// `python -m prometheus.jobs.__main__ ...` on the Python side, stored
// in sessionStorage, attached to every API call from here on.
export function TokenGate({ children }: TokenGateProps) {
  const [hasToken, setHasToken] = useState(() => Boolean(getToken()));
  const [draft, setDraft] = useState("");
  const [expired, setExpired] = useState(false);

  // A token that was valid when pasted stops working the moment either
  // backend process restarts (it provisions a fresh one) -- client.ts
  // detects that via a 401 and clears it; re-prompt here instead of
  // leaving every page showing a raw error body.
  useEffect(() => {
    function handleUnauthorized(): void {
      setExpired(true);
      setHasToken(false);
    }
    window.addEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
  }, []);

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed) return;
    setToken(trimmed);
    setExpired(false);
    setHasToken(true);
  }

  if (hasToken) {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <GlassCard className="w-full max-w-md p-8">
        <h1 className="bg-accent-gradient bg-clip-text text-2xl font-semibold text-transparent">
          ECONOSIM
        </h1>
        {expired && (
          <p className="mt-3 rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-sm text-amber-300">
            Your token stopped working -- probably because a backend process
            restarted and issued a new one. Paste the current token (see its
            terminal output, or <code className="rounded bg-white/10 px-1">cat /tmp/econosim-web/token</code>).
          </p>
        )}
        <p className="mt-2 text-sm text-slate-400">
          Paste a bearer token provisioned on the Python backend (e.g. via{" "}
          <code className="rounded bg-white/10 px-1">python -m prometheus.dashboard init-auth</code>
          ).
        </p>
        <form onSubmit={handleSubmit} className="mt-6 flex flex-col gap-3">
          <input
            type="password"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Bearer token"
            autoFocus
            className="rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-accent-violet focus:outline-none"
          />
          <button
            type="submit"
            className="rounded-xl bg-accent-gradient px-4 py-2.5 text-sm font-medium text-slate-950 transition-opacity hover:opacity-90"
          >
            Continue
          </button>
        </form>
      </GlassCard>
    </div>
  );
}
