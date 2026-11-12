import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setToken } from "./client";
import { submitJob } from "./jobs";

const REAL_JOB_RESPONSE = {
  job_id: "11111111-1111-1111-1111-111111111111",
  trace_id: "t1",
  kind: "inflationcast",
  status: "queued",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  recipe_sha256: "a".repeat(64),
  attempts: 0,
  cancel_requested: false,
  timeout_seconds: 300,
  resource_estimate: {},
  artifact_sha256: null,
  result_hash: null,
  error_code: null,
  diagnostic_id: null,
};

// client.ts wraps init.headers in a real Headers instance before
// calling fetch, so the mock receives a Headers object, not a plain
// record -- .get(...) is required, bracket access silently returns
// undefined on both sides and would make an equality assertion pass
// for the wrong reason.
function idempotencyKeyOf(call: Parameters<typeof fetch>): string | null {
  return new Headers(call[1]?.headers).get("Idempotency-Key");
}

describe("submitJob idempotency key", () => {
  beforeEach(() => {
    setToken("test-token");
    // A fresh Response per call -- a Response body stream can only be
    // read once, so reusing one mocked instance across calls (e.g. via
    // mockResolvedValue) breaks the second read with "Body has already
    // been read".
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify(REAL_JOB_RESPONSE), {
          status: 202,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sends the identical Idempotency-Key for two calls with the identical config", async () => {
    await submitJob("inflationcast", { seed: 0, max_epochs: 150 });
    await submitJob("inflationcast", { seed: 0, max_epochs: 150 });

    const calls = vi.mocked(fetch).mock.calls;
    expect(calls).toHaveLength(2);
    const keyOne = idempotencyKeyOf(calls[0]);
    const keyTwo = idempotencyKeyOf(calls[1]);
    expect(keyOne).not.toBeNull();
    expect(keyOne).toBe(keyTwo);
  });

  it("sends a DIFFERENT Idempotency-Key when the config actually differs", async () => {
    await submitJob("inflationcast", { seed: 0, max_epochs: 150 });
    await submitJob("inflationcast", { seed: 1, max_epochs: 150 });

    const calls = vi.mocked(fetch).mock.calls;
    const keyOne = idempotencyKeyOf(calls[0]);
    const keyTwo = idempotencyKeyOf(calls[1]);
    expect(keyOne).not.toBeNull();
    expect(keyOne).not.toBe(keyTwo);
  });

  it("is insensitive to key insertion order within the config", async () => {
    await submitJob("inflationcast", { seed: 0, max_epochs: 150 });
    await submitJob("inflationcast", { max_epochs: 150, seed: 0 });

    const calls = vi.mocked(fetch).mock.calls;
    const keyOne = idempotencyKeyOf(calls[0]);
    const keyTwo = idempotencyKeyOf(calls[1]);
    expect(keyOne).not.toBeNull();
    expect(keyOne).toBe(keyTwo);
  });
});
