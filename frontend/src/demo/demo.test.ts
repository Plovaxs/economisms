import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/errors";
import { DEMO, loadRecording } from "./demo";
import recording from "../../demo-data/recording.json";

describe("the recording that the demo edition serves", () => {
  it("is off in an ordinary build, so the full app never reads it", async () => {
    expect(DEMO).toBe(false);
    await expect(loadRecording()).rejects.toBeInstanceOf(ApiError);
  });

  it("has a real recorded run for every lab, each one a succeeded job", () => {
    const kinds = ["qmacro", "recessionnet_kaggle", "inflationcast", "neural_sde", "pde_solver", "marl", "rl_hedge"];
    for (const kind of kinds) {
      const entry = (recording.jobs as Record<string, { job: { status: string }; artifact: Record<string, unknown> }>)[kind];
      expect(entry, kind).toBeDefined();
      expect(entry?.job.status).toBe("succeeded");
      expect(entry?.artifact[kind], `${kind} payload`).toBeDefined();
    }
  });

  it("carries the research-only disclaimer on every recorded artifact", () => {
    for (const entry of Object.values(recording.jobs as Record<string, { artifact: { disclaimer: string } }>)) {
      expect(entry.artifact.disclaimer).toMatch(/RESEARCH ONLY/);
    }
  });

  it("records every dashboard page the app asks for with its default settings", () => {
    const keys = Object.keys(recording.dashboard);
    for (const wanted of [
      "/market-paths?sigma=0.2&n_paths=2000",
      "/economy?n_steps=6&seed=0",
      "/pricing?strike=100&volatility=0.2",
      "/audit-trail",
      "/portfolio/alice",
      "/experiments",
      "/hedge-actions",
      "/validation-issues",
      "/portfolio-risk",
      "/model-usage?model_id=recessionnet&application=research",
    ]) {
      expect(keys).toContain(wanted);
    }
  });

  it("holds no secret and no local path", () => {
    const text = JSON.stringify(recording);
    expect(text).not.toMatch(/\/home\//);
    expect(text).not.toMatch(/Bearer /i);
  });
});

// The module reads the build mode once, when it loads, so these tests load a fresh copy in demo mode.
async function demoModule() {
  vi.stubEnv("MODE", "demo");
  vi.resetModules();
  return import("./demo");
}

describe("the demo edition's API layer", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("answers a dashboard page from the recording, with or without the format suffix", async () => {
    const demo = await demoModule();
    expect(demo.DEMO).toBe(true);
    const page = await demo.demoDashboard<{ disclaimer: string }>("/audit-trail?format=json");
    expect(page).toEqual((recording.dashboard as Record<string, unknown>)["/audit-trail"]);
    const priced = await demo.demoDashboard("/pricing?strike=100&volatility=0.2&format=json");
    expect(priced).toBeDefined();
  });

  it("refuses other settings instead of inventing numbers", async () => {
    const demo = await demoModule();
    await expect(demo.demoDashboard("/pricing?strike=105&volatility=0.2&format=json")).rejects.toMatchObject({
      status: 404,
      message: expect.stringContaining("recorded default settings") as string,
    });
  });

  it("runs a lab end to end: submit the default config, poll, fetch the artifact", async () => {
    const demo = await demoModule();
    const entry = (recording.jobs as Record<string, { config: Record<string, unknown> }>)["marl"];
    const job = await demo.demoJobs<{ job_id: string; status: string }>("/v1/jobs", {
      method: "POST",
      body: JSON.stringify({ kind: "marl", config: entry?.config }),
    });
    expect(job.status).toBe("succeeded");
    const polled = await demo.demoJobs<{ job_id: string }>(`/v1/jobs/${job.job_id}`);
    expect(polled.job_id).toBe(job.job_id);
    const artifact = await demo.demoJobs<{ marl: unknown }>(`/v1/jobs/${job.job_id}/artifact`);
    expect(artifact.marl).toBeDefined();
  });

  it("does not pretend a changed lab setting was run", async () => {
    const demo = await demoModule();
    const entry = (recording.jobs as Record<string, { config: Record<string, unknown> }>)["marl"];
    await expect(
      demo.demoJobs("/v1/jobs", {
        method: "POST",
        body: JSON.stringify({ kind: "marl", config: { ...entry?.config, seed: 99 } }),
      }),
    ).rejects.toMatchObject({ status: 422 });
  });

  it("does not know a job it never recorded", async () => {
    const demo = await demoModule();
    await expect(demo.demoJobs("/v1/jobs/someone-elses-job")).rejects.toMatchObject({ status: 404 });
  });
});
