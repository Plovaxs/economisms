import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setToken } from "../api/client";
import { useJobPolling } from "./useJobPolling";

const JOB_ID = "11111111-1111-1111-1111-111111111111";

function jobResponse(status: string, overrides: Record<string, unknown> = {}) {
  return {
    job_id: JOB_ID,
    trace_id: "t1",
    kind: "inflationcast",
    status,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    recipe_sha256: "a".repeat(64),
    attempts: 0,
    cancel_requested: false,
    timeout_seconds: 300,
    resource_estimate: {},
    artifact_sha256: status === "succeeded" ? "b".repeat(64) : null,
    result_hash: status === "succeeded" ? "c".repeat(64) : null,
    error_code: status === "failed" ? "training_failed" : null,
    diagnostic_id: null,
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("useJobPolling", () => {
  beforeEach(() => {
    setToken("test-token");
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("reaches done and exposes the real artifact once the job succeeds", async () => {
    const artifact = {
      disclaimer: "x",
      source_tag: "x",
      run_manifest: {},
      model_cards: [],
      gate_report: {},
      runtime: {},
      job_context: {},
      inflationcast: { best_point_challenger: "naive_persistence" },
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(jobResponse("queued"), 202)) // submit
      .mockResolvedValueOnce(jsonResponse(jobResponse("running"))) // submit's own eager first poll
      .mockResolvedValueOnce(jsonResponse(jobResponse("succeeded"))) // scheduled poll
      .mockResolvedValueOnce(jsonResponse(artifact)); // artifact fetch

    const { result } = renderHook(() => useJobPolling("inflationcast"));

    // submit() itself performs the first poll eagerly (not via the
    // timer), so by the time it resolves we're already on "running".
    await act(async () => {
      await result.current.submit({ seed: 0 });
    });
    expect(result.current.state.phase).toBe("polling");

    // The one scheduled timer-based poll takes us from "running" to
    // the terminal "succeeded" status, which immediately triggers the
    // artifact fetch -- so a single advance reaches "done".
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    await waitFor(() => expect(result.current.state.phase).toBe("done"));
    if (result.current.state.phase !== "done") throw new Error("unreachable");
    expect(result.current.state.artifact.inflationcast).toEqual({
      best_point_challenger: "naive_persistence",
    });
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("renders a real error state, not a silent hang, when the job fails", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(jobResponse("queued"), 202))
      .mockResolvedValueOnce(jsonResponse(jobResponse("failed")));

    const { result } = renderHook(() => useJobPolling("rl_hedge"));

    await act(async () => {
      await result.current.submit({ seed: 0 });
    });

    await waitFor(() => expect(result.current.state.phase).toBe("error"));
    if (result.current.state.phase !== "error") throw new Error("unreachable");
    expect(result.current.state.message).toBe("training_failed");
  });
});
