import { type FormEvent, type ReactNode, useState } from "react";

import { getToken, setToken } from "../api/client";
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

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed) return;
    setToken(trimmed);
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
