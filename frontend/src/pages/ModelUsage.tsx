import { useState } from "react";

import { ApiError, getDashboardApi } from "../api/client";
import { GlassCard } from "../components/GlassCard";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";

interface ModelUsageResult {
  authorized: boolean;
  authorized_applications: string[];
}

export function ModelUsage() {
  const [modelId, setModelId] = useState("recessionnet");
  const [application, setApplication] = useState("research");
  const [result, setResult] = useState<ModelUsageResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function check(): Promise<void> {
    setError(null);
    setResult(null);
    try {
      const data = await getDashboardApi<ModelUsageResult>(
        `/model-usage?model_id=${encodeURIComponent(modelId)}&application=${encodeURIComponent(application)}`,
      );
      setResult(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Model usage"
        description="Check whether a model is authorized for a given application."
      />
      <GlassCard className="p-6">
        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-slate-400">Model ID</span>
            <input
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
              className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-slate-100 focus:border-accent-violet focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-slate-400">Application</span>
            <input
              value={application}
              onChange={(e) => setApplication(e.target.value)}
              className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-slate-100 focus:border-accent-violet focus:outline-none"
            />
          </label>
          <button
            onClick={() => void check()}
            className="rounded-xl bg-accent-gradient px-5 py-2.5 text-sm font-medium text-slate-950 hover:opacity-90"
          >
            Check
          </button>
        </div>
        {result && (
          <div className="mt-4 flex flex-col gap-2">
            <StatusBadge label={result.authorized ? "authorized" : "not authorized"} tone={result.authorized ? "good" : "bad"} />
            <p className="text-sm text-slate-400">
              Authorized applications: {result.authorized_applications.join(", ")}
            </p>
          </div>
        )}
        {error && (
          <p className="mt-4 rounded-xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
            {error}
          </p>
        )}
      </GlassCard>
    </div>
  );
}
