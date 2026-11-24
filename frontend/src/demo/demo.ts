// DEMO EDITION: the static build (`vite build --mode demo`) that is hosted without a backend.
//
// Nothing here is made up. `demo-data/recording.json` is real responses recorded from the real
// local Python backend (tools/record_demo.py), each page with its default settings. In the demo the
// API layer answers from that recording instead of the network. Anything that was not recorded
// (other parameters, other owners) is refused with an honest message instead of being invented.
import { ApiError } from "../api/errors";

export const DEMO: boolean = import.meta.env.MODE === "demo";

interface RecordedJob {
  job: Record<string, unknown>;
  config: Record<string, unknown>;
  artifact: Record<string, unknown>;
}

export interface Recording {
  dashboard: Record<string, unknown>;
  jobs: Record<string, RecordedJob>;
  meta: { recorded_at: string; git: string; note: string };
}

let cached: Promise<Recording> | null = null;

// A dynamic import of a JSON file under `demo-data/`: Vite splits it into its own chunk, and because
// the branch is on a build-time constant, a normal (non-demo) build contains neither the chunk nor
// a way to reach it.
export function loadRecording(): Promise<Recording> {
  if (!DEMO) return Promise.reject(new ApiError(404, "no demo recording in this build"));
  cached ??= import("../../demo-data/recording.json").then(
    (module) => module.default as unknown as Recording,
  );
  return cached;
}

const ONLY_DEFAULTS =
  "Demo edition: only the recorded default settings are available here. " +
  "Run the desktop app or the full web stack locally to use other values.";

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

export async function demoDashboard<T>(path: string): Promise<T> {
  const recording = await loadRecording();
  // The client appends `format=json`; the recording is keyed without it.
  const key = path.replace(/[?&]format=json$/, "");
  if (!(key in recording.dashboard)) throw new ApiError(404, ONLY_DEFAULTS);
  return recording.dashboard[key] as T;
}

const JOB_PREFIX = "demo-";

export async function demoJobs<T>(path: string, init?: RequestInit): Promise<T> {
  const recording = await loadRecording();
  const method = (init?.method ?? "GET").toUpperCase();
  if (method === "POST" && path === "/v1/jobs") {
    const body = JSON.parse(String(init?.body ?? "{}")) as { kind?: string; config?: unknown };
    const recorded = body.kind ? recording.jobs[body.kind] : undefined;
    if (!recorded) throw new ApiError(404, "Demo edition: this lab has no recorded run.");
    if (canonical(body.config) !== canonical(recorded.config)) throw new ApiError(422, ONLY_DEFAULTS);
    return { ...recorded.job, job_id: `${JOB_PREFIX}${body.kind}` } as T;
  }
  const match = /^\/v1\/jobs\/([^/]+)(\/artifact)?$/.exec(path);
  if (method === "GET" && match?.[1]?.startsWith(JOB_PREFIX)) {
    const recorded = recording.jobs[match[1].slice(JOB_PREFIX.length)];
    if (recorded) {
      return (match[2] ? recorded.artifact : { ...recorded.job, job_id: match[1] }) as T;
    }
  }
  throw new ApiError(404, "Demo edition: nothing is recorded for this request.");
}
