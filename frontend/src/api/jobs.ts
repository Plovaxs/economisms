import { getJobsApi } from "./client";

// Mirrors prometheus.jobs.store's real status set exactly
// (src/prometheus/jobs/store.py: STATUSES/TERMINAL) -- never invented.
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "timed_out";

export const TERMINAL_STATUSES: readonly JobStatus[] = [
  "succeeded",
  "failed",
  "cancelled",
  "timed_out",
];

// Mirrors prometheus.jobs.__main__.job_response's exact field set.
export interface JobResponse {
  job_id: string;
  trace_id: string;
  kind: string;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  recipe_sha256: string;
  attempts: number;
  cancel_requested: boolean;
  timeout_seconds: number | null;
  resource_estimate: Record<string, unknown>;
  artifact_sha256: string | null;
  result_hash: string | null;
  error_code: string | null;
  diagnostic_id: string | null;
}

export interface ArtifactBundle {
  disclaimer: string;
  source_tag: string;
  run_manifest: Record<string, unknown>;
  model_cards: unknown[];
  gate_report: Record<string, unknown>;
  runtime: Record<string, unknown>;
  job_context: Record<string, unknown>;
  // Every other key is the kind-specific payload, e.g. bundle["inflationcast"].
  [key: string]: unknown;
}

// Sorts object keys at every depth so the canonical string doesn't
// depend on insertion order anywhere in a nested config.
function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value !== null && typeof value === "object") {
    const sorted: Record<string, unknown> = {};
    for (const key of Object.keys(value as Record<string, unknown>).sort()) {
      sorted[key] = canonicalize((value as Record<string, unknown>)[key]);
    }
    return sorted;
  }
  return value;
}

// Deterministic per (kind, config): submitting the identical request
// twice reuses the same key, so the backend's own IdempotencyConflict/
// reuse semantics (src/prometheus/jobs/store.py) actually apply here --
// a fresh random key on every call would defeat idempotency entirely.
async function idempotencyKeyFor(kind: string, config: Record<string, unknown>): Promise<string> {
  const canonical = JSON.stringify(canonicalize({ kind, config }));
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical));
  const hex = Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return `web-${hex.slice(0, 48)}`;
}

export async function submitJob(
  kind: string,
  config: Record<string, unknown>,
): Promise<JobResponse> {
  const key = await idempotencyKeyFor(kind, config);
  return getJobsApi<JobResponse>("/v1/jobs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": key,
    },
    body: JSON.stringify({ kind, config }),
  });
}

export function getJob(jobId: string): Promise<JobResponse> {
  return getJobsApi<JobResponse>(`/v1/jobs/${jobId}`);
}

export function getArtifact(jobId: string): Promise<ArtifactBundle> {
  return getJobsApi<ArtifactBundle>(`/v1/jobs/${jobId}/artifact`);
}

export function cancelJob(jobId: string): Promise<JobResponse> {
  return getJobsApi<JobResponse>(`/v1/jobs/${jobId}/cancel`, { method: "POST" });
}
