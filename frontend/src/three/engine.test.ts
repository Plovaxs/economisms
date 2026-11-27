import { describe, expect, it } from "vitest";

import graphJson from "../atlas/graph.json";
import type { AtlasGraph } from "../atlas/web";
import {
  AUTO_ROTATE_SPEED,
  DEFAULT_CAMERA,
  DEFAULT_ORBIT,
  DISTANCE_RANGE,
  PITCH_LIMIT,
  SHELLS,
  type Vec3,
  along,
  clampCamera,
  cross,
  depthAlpha,
  depthOrder,
  dot,
  dragOrbit,
  fibonacciSphere,
  layoutWeb3,
  length,
  normalise,
  pick,
  project,
  rotate,
  stepOrbit,
  tangentBasis,
  wrapAngle,
  zoomOrbit,
} from "./engine";
import { tiltFor } from "./tilt";

const GRAPH = graphJson as unknown as AtlasGraph;
const VIEW = { width: 800, height: 600 };

describe("vectors", () => {
  it("normalises, crosses and measures", () => {
    expect(length(normalise([3, 4, 0]))).toBeCloseTo(1, 12);
    expect(cross([1, 0, 0], [0, 1, 0])).toEqual([0, 0, 1]);
    expect(dot([1, 2, 3], [4, 5, 6])).toBe(32);
    expect(normalise([0, 0, 0])).toEqual([0, 0, 1]); // never NaN
  });

  it("builds an orthonormal tangent basis for any direction", () => {
    for (const n of [normalise([1, 2, 3]), [0, 1, 0] as Vec3, [0, -1, 0] as Vec3, [1, 0, 0] as Vec3]) {
      const [u, v] = tangentBasis(n);
      expect(Math.abs(dot(u, n))).toBeLessThan(1e-9);
      expect(Math.abs(dot(v, n))).toBeLessThan(1e-9);
      expect(Math.abs(dot(u, v))).toBeLessThan(1e-9);
      expect(length(u)).toBeCloseTo(1, 9);
    }
  });
});

describe("the Fibonacci sphere", () => {
  it("puts every point on the unit sphere, spread so that no two are close", () => {
    const pts = fibonacciSphere(24);
    expect(pts).toHaveLength(24);
    for (const p of pts) expect(length(p)).toBeCloseTo(1, 9);
    let nearest = Infinity;
    for (let i = 0; i < pts.length; i++)
      for (let j = i + 1; j < pts.length; j++) nearest = Math.min(nearest, length([pts[i][0] - pts[j][0], pts[i][1] - pts[j][1], pts[i][2] - pts[j][2]]));
    expect(nearest).toBeGreaterThan(0.3);
    expect(fibonacciSphere(0)).toEqual([]);
    expect(fibonacciSphere(1)).toHaveLength(1);
  });
});

describe("rotation and projection", () => {
  it("rotation preserves length and is the identity at zero angles", () => {
    const p: Vec3 = [0.3, -0.5, 0.8];
    expect(length(rotate(p, 1.1, -0.4))).toBeCloseTo(length(p), 12);
    expect(rotate(p, 0, 0)).toEqual(p);
    const q = rotate(p, 2 * Math.PI, 0);
    expect(q[0]).toBeCloseTo(p[0], 12);
    expect(q[2]).toBeCloseTo(p[2], 12);
  });

  it("projects the origin to the centre and moves a point right when it is to the right", () => {
    const cam = { yaw: 0, pitch: 0, distance: 3 };
    const origin = project([0, 0, 0], cam, VIEW);
    expect(origin.x).toBeCloseTo(400, 9);
    expect(origin.y).toBeCloseTo(300, 9);
    expect(project([0.5, 0, 0], cam, VIEW).x).toBeGreaterThan(400);
    expect(project([0, 0.5, 0], cam, VIEW).y).toBeLessThan(300); // up is up on screen
  });

  it("makes nearer points larger and farther points smaller", () => {
    const cam = { yaw: 0, pitch: 0, distance: 3 };
    const near = project([0, 0, 0.8], cam, VIEW);
    const far = project([0, 0, -0.8], cam, VIEW);
    expect(near.scale).toBeGreaterThan(far.scale);
    expect(near.depth).toBeLessThan(far.depth);
  });

  it("hides points at or behind the camera instead of dividing by zero", () => {
    const behind = project([0, 0, 5], { yaw: 0, pitch: 0, distance: 3 }, VIEW);
    expect(behind.visible).toBe(false);
    expect(Number.isFinite(behind.x) && Number.isFinite(behind.scale)).toBe(true);
  });

  it("sorts back to front and picks the nearest disc under the pointer", () => {
    const projected = [
      { x: 100, y: 100, scale: 1, depth: 5, visible: true },
      { x: 102, y: 100, scale: 1, depth: 2, visible: true },
      { x: 300, y: 300, scale: 1, depth: 9, visible: true },
      { x: 100, y: 100, scale: 1, depth: 1, visible: false },
    ];
    expect(depthOrder(projected)).toEqual([2, 0, 1, 3]);
    expect(pick(projected, [10, 10, 10, 10], 101, 100)).toBe(1); // overlapping: the nearer one
    expect(pick(projected, [10, 10, 10, 10], 600, 600)).toBe(-1);
    expect(pick(projected, [10, 10, 10, 10], 300, 305)).toBe(2);
  });
});

describe("the orbit camera", () => {
  it("keeps pitch and distance in range and wraps yaw", () => {
    const c = clampCamera({ yaw: 7, pitch: 9, distance: 100 });
    expect(c.pitch).toBe(PITCH_LIMIT);
    expect(c.distance).toBe(DISTANCE_RANGE[1]);
    expect(c.yaw).toBeGreaterThanOrEqual(-Math.PI);
    expect(c.yaw).toBeLessThanOrEqual(Math.PI);
    expect(clampCamera({ ...DEFAULT_CAMERA, distance: 0 }).distance).toBe(DISTANCE_RANGE[0]);
    expect(wrapAngle(3 * Math.PI)).toBeCloseTo(Math.PI, 9) ;
  });

  it("rotates with a drag and leaves a velocity that inertia then spends", () => {
    const dragged = dragOrbit(DEFAULT_ORBIT, 100, -40, 0.1);
    expect(dragged.yaw).toBeGreaterThan(DEFAULT_ORBIT.yaw);
    expect(dragged.pitch).toBeLessThan(DEFAULT_ORBIT.pitch);
    expect(dragged.yawVelocity).toBeGreaterThan(0);
    let o = dragged;
    for (let i = 0; i < 200; i++) o = stepOrbit(o, 1 / 60, { dragging: false, autoRotate: false });
    expect(o.yawVelocity).toBe(0); // it comes to rest
    expect(o.yaw).toBeGreaterThan(dragged.yaw); // having coasted a little
  });

  it("does not move while dragging, and auto-rotates only when still and allowed", () => {
    const held = stepOrbit({ ...DEFAULT_ORBIT, yawVelocity: 2 }, 0.5, { dragging: true, autoRotate: true });
    expect(held.yaw).toBeCloseTo(DEFAULT_ORBIT.yaw, 12);
    const spun = stepOrbit(DEFAULT_ORBIT, 1, { dragging: false, autoRotate: true });
    expect(spun.yaw - DEFAULT_ORBIT.yaw).toBeCloseTo(AUTO_ROTATE_SPEED, 9);
    const still = stepOrbit(DEFAULT_ORBIT, 1, { dragging: false, autoRotate: false });
    expect(still.yaw).toBeCloseTo(DEFAULT_ORBIT.yaw, 12);
    expect(stepOrbit(DEFAULT_ORBIT, 0, { dragging: false, autoRotate: true })).toBe(DEFAULT_ORBIT);
  });

  it("zooms within bounds", () => {
    expect(zoomOrbit(DEFAULT_ORBIT, 0.5).distance).toBeLessThan(DEFAULT_ORBIT.distance);
    expect(zoomOrbit(DEFAULT_ORBIT, 1e-6).distance).toBe(DISTANCE_RANGE[0]);
    expect(zoomOrbit(DEFAULT_ORBIT, 1e6).distance).toBe(DISTANCE_RANGE[1]);
  });
});

describe("the model-web layout", () => {
  const placed = layoutWeb3(GRAPH.nodes, GRAPH.edges);
  const byId = new Map(placed.map((p) => [p.id, p.position]));
  const kindOf = new Map(GRAPH.nodes.map((n) => [n.id, n.kind]));

  it("places every drawn node once, finitely, and never a model that was not built", () => {
    expect(placed.length).toBeGreaterThan(50);
    expect(new Set(placed.map((p) => p.id)).size).toBe(placed.length);
    for (const p of placed) expect(p.position.every(Number.isFinite)).toBe(true);
    expect(byId.has("ferminet")).toBe(false);
  });

  it("is deterministic", () => {
    expect(layoutWeb3(GRAPH.nodes, GRAPH.edges)).toEqual(placed);
  });

  it("keeps models on the outer shell, baselines inside, pipelines at the core", () => {
    for (const p of placed) {
      const r = length(p.position);
      const kind = kindOf.get(p.id);
      if (kind === "model") expect(r).toBeCloseTo(SHELLS.model, 6);
      if (kind === "baseline") expect(r).toBeCloseTo(SHELLS.baseline, 6);
      if (kind === "pipeline") expect(r).toBeLessThan(SHELLS.baseline);
    }
  });

  it("gives no two nodes the same place", () => {
    const pts = placed.map((p) => p.position);
    let nearest = Infinity;
    for (let i = 0; i < pts.length; i++)
      for (let j = i + 1; j < pts.length; j++)
        nearest = Math.min(nearest, length([pts[i][0] - pts[j][0], pts[i][1] - pts[j][1], pts[i][2] - pts[j][2]]));
    expect(nearest).toBeGreaterThan(0.02);
  });

  it("puts a baseline near the models it was judged against", () => {
    const targets = GRAPH.edges.filter((e) => e.kind === "baseline_for" && e.source === "mlp_operator").map((e) => byId.get(e.target)!);
    const base = byId.get("mlp_operator")!;
    const toTarget = targets.map((t) => dot(normalise(base), normalise(t)));
    expect(Math.max(...toTarget)).toBeGreaterThan(0.8);
  });
});

describe("small helpers", () => {
  it("moves a particle along an edge and wraps", () => {
    expect(along([0, 0, 0], [10, 0, 0], 0.25)).toEqual([2.5, 0, 0]);
    expect(along([0, 0, 0], [10, 0, 0], 1.25)[0]).toBeCloseTo(2.5, 12);
  });

  it("fades with depth between 1 and the floor", () => {
    expect(depthAlpha(1, 1, 5)).toBe(1);
    expect(depthAlpha(5, 1, 5, 0.3)).toBeCloseTo(0.3, 12);
    expect(depthAlpha(3, 3, 3)).toBe(1);
    expect(depthAlpha(-10, 1, 5)).toBe(1);
  });

  it("tilts a card toward the pointer by at most the maximum, flat at the centre", () => {
    expect(tiltFor(50, 50, 100, 100)).toEqual({ x: 0, y: 0 });
    const corner = tiltFor(100, 100, 100, 100, 6);
    expect(Math.abs(corner.x)).toBe(6);
    expect(Math.abs(corner.y)).toBe(6);
    expect(tiltFor(500, -500, 100, 100, 6).y).toBe(6); // clamped
    expect(tiltFor(10, 10, 0, 0)).toEqual({ x: 0, y: 0 });
  });
});
