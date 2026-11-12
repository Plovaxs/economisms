import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../api/client";
import {
  type ArtifactBundle,
  type JobResponse,
  TERMINAL_STATUSES,
  getArtifact,
  getJob,
  submitJob,
} from "../api/jobs";

export type LabState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "polling"; job: JobResponse }
  | { phase: "done"; job: JobResponse; artifact: ArtifactBundle }
  | { phase: "error"; message: string; job?: JobResponse };

const POLL_INTERVAL_MS = 1000;

export function useJobPolling(kind: string) {
  const [state, setState] = useState<LabState>({ phase: "idle" });
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const poll = useCallback(async (jobId: string) => {
    try {
      const job = await getJob(jobId);
      if (!TERMINAL_STATUSES.includes(job.status)) {
        setState({ phase: "polling", job });
        timerRef.current = setTimeout(() => void poll(jobId), POLL_INTERVAL_MS);
        return;
      }
      if (job.status !== "succeeded") {
        setState({
          phase: "error",
          message: job.error_code ?? `job ended with status ${job.status}`,
          job,
        });
        return;
      }
      const artifact = await getArtifact(jobId);
      setState({ phase: "done", job, artifact });
    } catch (error) {
      setState({
        phase: "error",
        message: error instanceof ApiError ? error.message : String(error),
      });
    }
  }, []);

  const submit = useCallback(
    async (config: Record<string, unknown>) => {
      setState({ phase: "submitting" });
      try {
        const job = await submitJob(kind, config);
        setState({ phase: "polling", job });
        void poll(job.job_id);
      } catch (error) {
        setState({
          phase: "error",
          message: error instanceof ApiError ? error.message : String(error),
        });
      }
    },
    [kind, poll],
  );

  const reset = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setState({ phase: "idle" });
  }, []);

  return { state, submit, reset };
}
