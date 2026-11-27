import { describe, expect, it, vi } from "vitest";

import { DEFAULT_SETTINGS } from "../settings/settings";
import { THEMES } from "../settings/themes";
import { rank } from "./fuzzy";
import { NAV_ITEMS, WORKSPACES, titleOf, workspaceOf } from "./nav";
import { SHORTCUTS, buildCommands } from "./commands";

function context(overrides = {}) {
  return {
    navigate: vi.fn(),
    settings: { ...DEFAULT_SETTINGS },
    update: vi.fn(),
    reset: vi.fn(),
    openShortcuts: vi.fn(),
    ...overrides,
  };
}

describe("navigation data", () => {
  it("assigns every route to a workspace and every workspace has a home", () => {
    for (const item of NAV_ITEMS) expect(workspaceOf(item.to)).toBe(item.group);
    expect(workspaceOf("/lab/something-new")).toBe("labs");
    expect(workspaceOf("/nowhere")).toBe("overview");
    expect(WORKSPACES.map((w) => w.key)).toEqual(["1", "2", "3", "4", "5"]);
    for (const w of WORKSPACES) expect(NAV_ITEMS.some((i) => i.to === w.home)).toBe(true);
    expect(titleOf("/pricing")).toBe("Pricing diagnostics");
  });

  it("has unique paths", () => {
    expect(new Set(NAV_ITEMS.map((i) => i.to)).size).toBe(NAV_ITEMS.length);
  });
});

describe("the command list", () => {
  it("has a unique id for every command", () => {
    const ids = buildCommands(context()).map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("offers every theme and every route", () => {
    const ids = new Set(buildCommands(context()).map((c) => c.id));
    for (const t of THEMES) expect(ids.has(`theme:${t.id}`)).toBe(true);
    for (const i of NAV_ITEMS) expect(ids.has(`go:${i.to}`)).toBe(true);
    expect(ids.has("theme:system")).toBe(true);
    expect([...ids].filter((i) => i.startsWith("model:")).length).toBeGreaterThan(40);
  });

  it("runs the command it names", () => {
    const ctx = context();
    const commands = buildCommands(ctx);
    const by = (id: string) => commands.find((c) => c.id === id)!;
    by("go:/pricing").run();
    expect(ctx.navigate).toHaveBeenCalledWith("/pricing");
    by("theme:nord").run();
    expect(ctx.update).toHaveBeenCalledWith({ theme: "nord" });
    by("a11y:motion").run();
    expect(ctx.update).toHaveBeenCalledWith({ motion: "reduced" });
    by("model:fno").run();
    expect(ctx.navigate).toHaveBeenCalledWith("/atlas?model=fno");
    by("help:shortcuts").run();
    expect(ctx.openShortcuts).toHaveBeenCalled();
    by("help:reset").run();
    expect(ctx.reset).toHaveBeenCalled();
  });

  it("states the current state in toggle labels, so the command says what it will do", () => {
    const on = buildCommands(context({ settings: { ...DEFAULT_SETTINGS, motion: "reduced", cvdSafeCharts: true } }));
    expect(on.find((c) => c.id === "a11y:motion")?.label).toBe("Allow motion");
    expect(on.find((c) => c.id === "a11y:cvd")?.label).toContain("theme palette");
    const off = buildCommands(context());
    expect(off.find((c) => c.id === "a11y:motion")?.label).toBe("Reduce motion");
  });

  it("steps the text size within the offered scales and no further", () => {
    const top = buildCommands(context({ settings: { ...DEFAULT_SETTINGS, fontScale: 1.5 } }));
    expect(top.find((c) => c.id === "a11y:bigger")?.hint).toBe("150%");
    const bottom = buildCommands(context({ settings: { ...DEFAULT_SETTINGS, fontScale: 0.85 } }));
    expect(bottom.find((c) => c.id === "a11y:smaller")?.hint).toBe("85%");
  });

  it("is findable by what a person would type", () => {
    const commands = buildCommands(context());
    expect(rank("colour blind", commands.map((c) => ({ ...c, keywords: c.keywords }))).some((c) => c.id === "a11y:cvd")).toBe(true);
    expect(rank("tokyo", commands)[0].id).toBe("theme:tokyo-night");
    expect(rank("fourier", commands)[0].id).toBe("model:fno");
  });
});

describe("shortcuts list", () => {
  it("documents the global keys", () => {
    const keys = SHORTCUTS.map((s) => s.keys).join(" ");
    expect(keys).toContain("Ctrl K");
    expect(keys).toContain("Alt 1");
    expect(SHORTCUTS.length).toBeGreaterThanOrEqual(8);
  });
});
