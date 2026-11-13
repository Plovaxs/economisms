import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, UNAUTHORIZED_EVENT, getDashboardApi, getJobsApi, getToken, setToken } from "./client";

describe("API error handling", () => {
  beforeEach(() => {
    setToken("test-token");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("unwraps the dashboard's flat {error: string} body into a clean message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: "valid bearer credentials are required" }), {
        status: 401,
        headers: { "content-type": "application/json" },
      }),
    );
    await expect(getDashboardApi("/economy")).rejects.toMatchObject({
      message: "valid bearer credentials are required",
    } satisfies Partial<ApiError>);
  });

  it("unwraps the job API's nested {error: {code, message}} body into a clean message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: "invalid_recipe", message: "request failed typed semantic validation" } }),
        { status: 422, headers: { "content-type": "application/json" } },
      ),
    );
    await expect(getJobsApi("/v1/jobs")).rejects.toMatchObject({
      message: "request failed typed semantic validation",
    } satisfies Partial<ApiError>);
  });

  it("clears the stored token and broadcasts UNAUTHORIZED_EVENT on a 401", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: "valid bearer credentials are required" }), {
        status: 401,
        headers: { "content-type": "application/json" },
      }),
    );
    const handler = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, handler);
    try {
      await expect(getDashboardApi("/economy")).rejects.toBeInstanceOf(ApiError);
      expect(getToken()).toBeNull();
      expect(handler).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener(UNAUTHORIZED_EVENT, handler);
    }
  });

  it("does not clear the token or broadcast on a non-401 error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "not_found", message: "job was not found" } }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    );
    const handler = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, handler);
    try {
      await expect(getJobsApi("/v1/jobs/x")).rejects.toBeInstanceOf(ApiError);
      expect(getToken()).toBe("test-token");
      expect(handler).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener(UNAUTHORIZED_EVENT, handler);
    }
  });
});
