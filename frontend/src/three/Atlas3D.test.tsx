import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import graphJson from "../atlas/graph.json";
import type { AtlasGraph } from "../atlas/web";
import { Atlas3D, type Filters } from "./Atlas3D";
import { DEFAULT_ORBIT, layoutWeb3, project } from "./engine";

const GRAPH = graphJson as unknown as AtlasGraph;
const COLOURS = { bg: "#111111", surface: "#222222", ink: "#ffffff", muted: "#999999", a: "#8b5cf6", b: "#d946ef", c: "#22d3ee" };
const FILTERS: Filters = { baselines: true, relations: true, feeds: true };

// A recording 2-D context: every method is a spy and every property assignable.
function recordingContext() {
  const calls: Record<string, number> = {};
  const target: Record<string, unknown> = {};
  const ctx = new Proxy(target, {
    get(t, prop: string) {
      if (prop in t) return t[prop];
      if (prop === "measureText") return (text: string) => ({ width: text.length * 6 });
      return (...args: unknown[]) => {
        calls[prop] = (calls[prop] ?? 0) + 1;
        void args;
      };
    },
    set(t, prop: string, value) {
      t[prop] = value;
      return true;
    },
  });
  return { ctx: ctx as unknown as CanvasRenderingContext2D, calls };
}

// jsdom (as configured here) has no PointerEvent, so Testing Library would send a bare Event with no
// coordinates and no pointer id: a "click at x, y" would silently be a click at nowhere. A MouseEvent
// that also carries `pointerId` is all the component reads.
class PointerEventShim extends MouseEvent {
  readonly pointerId: number;
  constructor(type: string, init: MouseEventInit & { pointerId?: number } = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 1;
  }
}

const original = HTMLCanvasElement.prototype.getContext;
let raf: FrameRequestCallback[] = [];

beforeEach(() => {
  vi.stubGlobal("PointerEvent", PointerEventShim);
  raf = [];
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
    raf.push(cb);
    return raf.length;
  });
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  HTMLCanvasElement.prototype.getContext = original;
  vi.restoreAllMocks();
});

function renderView(overrides: Partial<React.ComponentProps<typeof Atlas3D>> = {}) {
  const onSelect = vi.fn();
  const onAutoRotate = vi.fn();
  const result = render(
    <Atlas3D
      graph={GRAPH}
      selected="fno"
      onSelect={onSelect}
      colours={COLOURS}
      autoRotate
      onAutoRotate={onAutoRotate}
      labels="selected"
      quality="auto"
      reducedMotion={false}
      filters={FILTERS}
      hiddenFamilies={new Set()}
      {...overrides}
    />,
  );
  return { ...result, onSelect, onAutoRotate };
}

function tick(ms = 16) {
  act(() => {
    const frames = raf;
    raf = [];
    frames.forEach((cb) => cb(performance.now() + ms));
  });
}

describe("Atlas3D without a canvas", () => {
  it("says so and tells the page to fall back to the 2D web", () => {
    const onUnsupported = vi.fn();
    renderView({ onUnsupported });
    expect(screen.getByRole("alert")).toHaveTextContent(/cannot draw the 3D view/);
    expect(onUnsupported).toHaveBeenCalled();
  });
});

describe("Atlas3D with a canvas", () => {
  it("draws the graph: nodes, edges and labels", () => {
    const { ctx, calls } = recordingContext();
    HTMLCanvasElement.prototype.getContext = (() => ctx) as unknown as HTMLCanvasElement["getContext"];
    renderView();
    tick();
    expect(calls.clearRect).toBeGreaterThan(0);
    expect(calls.arc).toBeGreaterThan(20); // circles for the models
    expect(calls.lineTo).toBeGreaterThan(20); // edges, guides and diamonds
    expect(calls.fillText).toBeGreaterThan(0); // at least the selected model's name
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("is a named, focusable group with a toolbar and a live announcement of the selection", () => {
    const { ctx } = recordingContext();
    HTMLCanvasElement.prototype.getContext = (() => ctx) as unknown as HTMLCanvasElement["getContext"];
    renderView();
    const view = screen.getByRole("group", { name: /Interactive 3D model web/ });
    expect(view).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("toolbar", { name: "3D view controls" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Fourier Neural Operator, model");
  });

  it("chooses the next and previous model with the bracket keys", () => {
    const { ctx } = recordingContext();
    HTMLCanvasElement.prototype.getContext = (() => ctx) as unknown as HTMLCanvasElement["getContext"];
    const { onSelect } = renderView();
    const view = screen.getByTestId("atlas-3d");
    fireEvent.keyDown(view, { key: "]" });
    fireEvent.keyDown(view, { key: "[" });
    expect(onSelect).toHaveBeenCalledTimes(2);
    const [next, previous] = onSelect.mock.calls.map((c) => c[0]);
    expect(next).not.toBe("fno");
    expect(previous).not.toBe("fno");
    expect(next).not.toBe(previous);
  });

  it("skips hidden families when stepping", () => {
    const { ctx } = recordingContext();
    HTMLCanvasElement.prototype.getContext = (() => ctx) as unknown as HTMLCanvasElement["getContext"];
    const operators = new Set(GRAPH.nodes.filter((n) => n.family === "operators" && n.kind === "model").map((n) => n.id));
    const { onSelect } = renderView({ hiddenFamilies: new Set(["operators"]) });
    const view = screen.getByTestId("atlas-3d");
    for (let i = 0; i < 40; i++) fireEvent.keyDown(view, { key: "]" });
    for (const [id] of onSelect.mock.calls) expect(operators.has(id)).toBe(false);
  });

  it("zooms, rotates and resets from the keyboard and the buttons without error", () => {
    const { ctx, calls } = recordingContext();
    HTMLCanvasElement.prototype.getContext = (() => ctx) as unknown as HTMLCanvasElement["getContext"];
    renderView();
    const view = screen.getByTestId("atlas-3d");
    for (const key of ["+", "-", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "0"]) fireEvent.keyDown(view, { key });
    for (const name of ["Zoom in", "Zoom out", "Reset the view"]) fireEvent.click(screen.getByRole("button", { name }));
    fireEvent.doubleClick(view);
    fireEvent.wheel(view, { deltaY: 120 });
    tick();
    tick();
    expect(calls.clearRect).toBeGreaterThan(1);
  });

  it("toggles auto-rotation, and disables it when motion is reduced", () => {
    const { ctx } = recordingContext();
    HTMLCanvasElement.prototype.getContext = (() => ctx) as unknown as HTMLCanvasElement["getContext"];
    const first = renderView();
    const button = screen.getByRole("button", { name: "Auto-rotate" });
    expect(button).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(button);
    expect(first.onAutoRotate).toHaveBeenCalledWith(false);
    first.unmount();
    renderView({ reducedMotion: true });
    expect(screen.getByRole("button", { name: "Auto-rotate" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Auto-rotate" })).toHaveAttribute("aria-pressed", "false");
  });

  it("draws no flowing particles when motion is reduced", () => {
    const moving = recordingContext();
    HTMLCanvasElement.prototype.getContext = (() => moving.ctx) as unknown as HTMLCanvasElement["getContext"];
    const a = renderView();
    tick();
    const withParticles = moving.calls.arc;
    a.unmount();
    const still = recordingContext();
    HTMLCanvasElement.prototype.getContext = (() => still.ctx) as unknown as HTMLCanvasElement["getContext"];
    renderView({ reducedMotion: true });
    tick();
    expect(still.calls.arc).toBeLessThan(withParticles);
  });

  it("selects the model under the pointer on a click and not on a drag", () => {
    const { ctx } = recordingContext();
    HTMLCanvasElement.prototype.getContext = (() => ctx) as unknown as HTMLCanvasElement["getContext"];
    const { onSelect } = renderView();
    tick(); // draws once, so there is something to hit-test against
    const view = screen.getByTestId("atlas-3d");
    // a click on empty space selects nothing
    fireEvent.pointerDown(view, { pointerId: 1, clientX: 5, clientY: 5 });
    fireEvent.pointerUp(view, { pointerId: 1, clientX: 5, clientY: 5 });
    expect(onSelect).not.toHaveBeenCalled();
    // a drag rotates (and never selects)
    fireEvent.pointerDown(view, { pointerId: 2, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(view, { pointerId: 2, clientX: 160, clientY: 120 });
    fireEvent.pointerUp(view, { pointerId: 2, clientX: 160, clientY: 120 });
    expect(onSelect).not.toHaveBeenCalled();
  });

  // jsdom has no layout, so the canvas is the 240 x 240 minimum the component falls back to, and with
  // auto-rotation off the camera stays at its default: the screen position of every model is known.
  function nearestModel() {
    const kinds = new Map(GRAPH.nodes.map((n) => [n.id, n]));
    const placed = layoutWeb3(GRAPH.nodes, GRAPH.edges)
      .filter((p) => kinds.get(p.id)?.kind === "model")
      .map((p) => ({ id: p.id, family: kinds.get(p.id)?.family as string, q: project(p.position, DEFAULT_ORBIT, { width: 240, height: 240 }) }))
      .sort((a, b) => a.q.depth - b.q.depth);
    return placed[0];
  }

  it("selects the model drawn under the pointer when it is clicked", () => {
    const { ctx } = recordingContext();
    HTMLCanvasElement.prototype.getContext = (() => ctx) as unknown as HTMLCanvasElement["getContext"];
    const target = nearestModel();
    const { onSelect } = renderView({ autoRotate: false, selected: "none-selected" });
    tick();
    const view = screen.getByTestId("atlas-3d");
    fireEvent.pointerDown(view, { pointerId: 1, clientX: target.q.x, clientY: target.q.y });
    fireEvent.pointerUp(view, { pointerId: 1, clientX: target.q.x, clientY: target.q.y });
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(target.id);
  });

  it("does not select when the press was a drag, even one that ends on a model", () => {
    const { ctx } = recordingContext();
    HTMLCanvasElement.prototype.getContext = (() => ctx) as unknown as HTMLCanvasElement["getContext"];
    const target = nearestModel();
    const { onSelect } = renderView({ autoRotate: false, selected: "none-selected" });
    tick();
    const view = screen.getByTestId("atlas-3d");
    const at = { clientX: target.q.x, clientY: target.q.y };
    fireEvent.pointerDown(view, { pointerId: 1, ...at });
    // away and back: the pointer travels 40 px (past the click tolerance) and is released on the model
    fireEvent.pointerMove(view, { pointerId: 1, clientX: target.q.x + 20, clientY: target.q.y });
    fireEvent.pointerMove(view, { pointerId: 1, ...at });
    fireEvent.pointerUp(view, { pointerId: 1, ...at });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("does not select a model whose family is hidden", () => {
    const { ctx } = recordingContext();
    HTMLCanvasElement.prototype.getContext = (() => ctx) as unknown as HTMLCanvasElement["getContext"];
    const target = nearestModel();
    const { onSelect } = renderView({ autoRotate: false, selected: "none-selected", hiddenFamilies: new Set([target.family]) });
    tick();
    const view = screen.getByTestId("atlas-3d");
    fireEvent.pointerDown(view, { pointerId: 1, clientX: target.q.x, clientY: target.q.y });
    fireEvent.pointerUp(view, { pointerId: 1, clientX: target.q.x, clientY: target.q.y });
    expect(onSelect).not.toHaveBeenCalledWith(target.id);
  });
});
