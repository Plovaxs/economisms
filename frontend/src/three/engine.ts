// A small 3-D engine for the model web, with no dependency: vectors, an orbit camera with inertia, a
// perspective projection, depth sorting, hit testing and a deterministic spherical layout. It is pure
// (no DOM, no canvas), so every piece is unit-tested; the canvas component only draws what it returns.

export type Vec3 = readonly [number, number, number];

export const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

export const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const scale = (a: Vec3, k: number): Vec3 => [a[0] * k, a[1] * k, a[2] * k];
export const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const cross = (a: Vec3, b: Vec3): Vec3 => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
export const length = (a: Vec3): number => Math.hypot(a[0], a[1], a[2]);
export const normalise = (a: Vec3): Vec3 => {
  const n = length(a);
  return n === 0 ? [0, 0, 1] : [a[0] / n, a[1] / n, a[2] / n];
};

/** `count` points spread evenly over the unit sphere (the Fibonacci lattice). */
export function fibonacciSphere(count: number): Vec3[] {
  if (count <= 0) return [];
  if (count === 1) return [[0, 1, 0]];
  const points: Vec3[] = [];
  for (let i = 0; i < count; i++) {
    const y = 1 - (2 * i) / (count - 1);
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = GOLDEN_ANGLE * i;
    points.push([Math.cos(theta) * r, y, Math.sin(theta) * r]);
  }
  return points;
}

/** Two unit vectors perpendicular to `n` and to each other. */
export function tangentBasis(n: Vec3): [Vec3, Vec3] {
  const helper: Vec3 = Math.abs(n[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0];
  const u = normalise(cross(n, helper));
  const v = normalise(cross(n, u));
  return [u, v];
}

// ----- the camera ---------------------------------------------------------------------------

export interface Camera {
  yaw: number;
  pitch: number;
  /** distance from the origin; smaller is closer */
  distance: number;
}

export const DEFAULT_CAMERA: Camera = { yaw: 0.6, pitch: 0.35, distance: 3.1 };
export const PITCH_LIMIT = 1.45;
export const DISTANCE_RANGE: readonly [number, number] = [1.6, 7];

export function clampCamera(c: Camera): Camera {
  return {
    yaw: wrapAngle(c.yaw),
    pitch: Math.max(-PITCH_LIMIT, Math.min(PITCH_LIMIT, c.pitch)),
    distance: Math.max(DISTANCE_RANGE[0], Math.min(DISTANCE_RANGE[1], c.distance)),
  };
}

export function wrapAngle(a: number): number {
  const twoPi = 2 * Math.PI;
  const r = ((a % twoPi) + twoPi) % twoPi;
  return r > Math.PI ? r - twoPi : r;
}

/** Rotate a world point into camera space: yaw about the vertical axis, then pitch about the horizontal. */
export function rotate(p: Vec3, yaw: number, pitch: number): Vec3 {
  const cy = Math.cos(yaw);
  const sy = Math.sin(yaw);
  const x1 = p[0] * cy + p[2] * sy;
  const z1 = -p[0] * sy + p[2] * cy;
  const cp = Math.cos(pitch);
  const sp = Math.sin(pitch);
  const y2 = p[1] * cp - z1 * sp;
  const z2 = p[1] * sp + z1 * cp;
  return [x1, y2, z2];
}

export interface Projected {
  x: number;
  y: number;
  /** pixels per world unit at this depth: use it to size things so near ones are larger */
  scale: number;
  /** camera-space distance along the view axis: larger is farther */
  depth: number;
  visible: boolean;
}

export interface Viewport {
  width: number;
  height: number;
}

/** Perspective projection of a world point; the camera looks at the origin from `distance`. */
export function project(p: Vec3, camera: Camera, view: Viewport): Projected {
  const [x, y, z] = rotate(p, camera.yaw, camera.pitch);
  const depth = camera.distance - z;
  const near = 0.15;
  if (depth <= near) return { x: view.width / 2, y: view.height / 2, scale: 0, depth, visible: false };
  // 0.40: the outer shell (radius 1) fills about 40% of the smaller side at the default distance, which
  // leaves room for labels all around it
  const focal = Math.min(view.width, view.height) * 0.4 * camera.distance;
  const k = focal / depth;
  return { x: view.width / 2 + x * k, y: view.height / 2 - y * k, scale: k, depth, visible: true };
}

/** Indices of `items` ordered back to front, for the painter's algorithm. */
export function depthOrder(projected: readonly Projected[]): number[] {
  return projected
    .map((p, i) => [i, p.depth] as const)
    .sort((a, b) => b[1] - a[1])
    .map(([i]) => i);
}

/** The nearest visible item whose disc (radius in pixels) contains the pointer, or -1. */
export function pick(projected: readonly Projected[], radii: readonly number[], px: number, py: number): number {
  let best = -1;
  let bestDepth = Infinity;
  projected.forEach((p, i) => {
    if (!p.visible) return;
    if (Math.hypot(px - p.x, py - p.y) <= radii[i] && p.depth < bestDepth) {
      best = i;
      bestDepth = p.depth;
    }
  });
  return best;
}

// ----- inertia and auto-rotation --------------------------------------------------------------

export interface Orbit extends Camera {
  yawVelocity: number;
  pitchVelocity: number;
}

export const DEFAULT_ORBIT: Orbit = { ...DEFAULT_CAMERA, yawVelocity: 0, pitchVelocity: 0 };
export const AUTO_ROTATE_SPEED = 0.18; // radians per second
const DAMPING = 3.2; // per second

/** Advance the orbit by `dt` seconds. Velocity decays exponentially; auto-rotation gently takes over
 * when the camera is nearly still and nobody is dragging. */
export function stepOrbit(o: Orbit, dt: number, opts: { dragging: boolean; autoRotate: boolean }): Orbit {
  if (dt <= 0) return o;
  const decay = Math.exp(-DAMPING * dt);
  let yawVelocity = opts.dragging ? 0 : o.yawVelocity * decay;
  let pitchVelocity = opts.dragging ? 0 : o.pitchVelocity * decay;
  if (Math.abs(yawVelocity) < 1e-3) yawVelocity = 0;
  if (Math.abs(pitchVelocity) < 1e-3) pitchVelocity = 0;
  const drift = opts.autoRotate && !opts.dragging && yawVelocity === 0 && pitchVelocity === 0 ? AUTO_ROTATE_SPEED : 0;
  const next = clampCamera({
    yaw: o.yaw + (yawVelocity + drift) * dt,
    pitch: o.pitch + pitchVelocity * dt,
    distance: o.distance,
  });
  return { ...next, yawVelocity, pitchVelocity };
}

/** A pointer drag of (dx, dy) pixels rotates the camera; the velocity it leaves is what inertia keeps. */
export function dragOrbit(o: Orbit, dx: number, dy: number, dt: number): Orbit {
  const sensitivity = 0.0065;
  const next = clampCamera({ yaw: o.yaw + dx * sensitivity, pitch: o.pitch + dy * sensitivity, distance: o.distance });
  const v = dt > 0 ? { yaw: (dx * sensitivity) / dt, pitch: (dy * sensitivity) / dt } : { yaw: 0, pitch: 0 };
  const cap = 6;
  return {
    ...next,
    yawVelocity: Math.max(-cap, Math.min(cap, v.yaw)),
    pitchVelocity: Math.max(-cap, Math.min(cap, v.pitch)),
  };
}

export function zoomOrbit(o: Orbit, factor: number): Orbit {
  const next = clampCamera({ yaw: o.yaw, pitch: o.pitch, distance: o.distance * factor });
  return { ...o, distance: next.distance };
}

// ----- the layout of the model web -----------------------------------------------------------

export interface LayoutNode {
  id: string;
  kind: string;
  family: string;
  status: string;
}

export interface LayoutEdge {
  source: string;
  target: string;
  kind: string;
}

export interface Placed3 {
  id: string;
  position: Vec3;
}

export const SHELLS = { model: 1, baseline: 0.52, pipeline: 0.13 } as const;

/**
 * Families sit on the outer shell, spread by a Fibonacci lattice and each family is a tight cluster
 * (a golden-angle spiral on the tangent plane); baselines go on an inner shell in the average direction
 * of the models they were judged against, so their dotted lines are short; pipelines sit at the core.
 */
export function layoutWeb3(nodes: readonly LayoutNode[], edges: readonly LayoutEdge[]): Placed3[] {
  const drawn = nodes.filter((n) => ["model", "baseline", "pipeline"].includes(n.kind) && n.status !== "not_built");
  const models = drawn.filter((n) => n.kind === "model");
  const families = [...new Set(models.map((n) => n.family))].sort();
  const anchors = fibonacciSphere(families.length);
  const out = new Map<string, Vec3>();

  families.forEach((family, fi) => {
    const anchor = anchors[fi];
    const [u, v] = tangentBasis(anchor);
    const members = models.filter((n) => n.family === family).sort((a, b) => a.id.localeCompare(b.id));
    members.forEach((node, k) => {
      const radius = k === 0 ? 0 : 0.1 + 0.09 * Math.sqrt(k);
      const angle = GOLDEN_ANGLE * k;
      const offset = add(scale(u, Math.cos(angle) * radius), scale(v, Math.sin(angle) * radius));
      out.set(node.id, scale(normalise(add(anchor, offset)), SHELLS.model));
    });
  });

  const baselines = drawn.filter((n) => n.kind === "baseline").sort((a, b) => a.id.localeCompare(b.id));
  const fallback = fibonacciSphere(Math.max(baselines.length, 2));
  baselines.forEach((node, i) => {
    const targets = edges.filter((e) => e.kind === "baseline_for" && e.source === node.id).map((e) => out.get(e.target));
    const known = targets.filter((t): t is Vec3 => t !== undefined);
    const direction = known.length ? normalise(known.reduce<Vec3>((s, t) => add(s, normalise(t)), [0, 0, 0])) : fallback[i];
    // a small spread so baselines that share a direction do not sit on top of each other
    const [u, v] = tangentBasis(direction);
    const jitter = add(scale(u, 0.09 * Math.cos(GOLDEN_ANGLE * i)), scale(v, 0.09 * Math.sin(GOLDEN_ANGLE * i)));
    out.set(node.id, scale(normalise(add(direction, jitter)), SHELLS.baseline));
  });

  // Baselines that were judged against the same models want the same spot: push them apart (a few
  // rounds of pairwise repulsion on the shell) while keeping each near the direction it wanted.
  const inner: Vec3[] = baselines.map((n) => out.get(n.id) ?? ([0, 0, 0] as Vec3));
  const relaxed = relaxOnSphere(inner, SHELLS.baseline, 0.2, 60);
  baselines.forEach((n, i) => out.set(n.id, relaxed[i]));

  const pipelines = drawn.filter((n) => n.kind === "pipeline").sort((a, b) => a.id.localeCompare(b.id));
  pipelines.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / Math.max(pipelines.length, 1);
    out.set(node.id, [Math.cos(angle) * SHELLS.pipeline, 0, Math.sin(angle) * SHELLS.pipeline]);
  });

  return drawn.map((n) => ({ id: n.id, position: out.get(n.id) ?? [0, 0, 0] }));
}

/** Push points on a sphere of `radius` apart until none is closer than `minimum` (or `rounds` pass). */
export function relaxOnSphere(points: readonly Vec3[], radius: number, minimum: number, rounds: number): Vec3[] {
  let current = points.map((p) => scale(normalise(p), radius));
  for (let round = 0; round < rounds; round++) {
    const push: Vec3[] = current.map(() => [0, 0, 0]);
    let moved = false;
    for (let i = 0; i < current.length; i++) {
      for (let j = i + 1; j < current.length; j++) {
        const d = add(current[i], scale(current[j], -1));
        const dist = length(d);
        if (dist >= minimum) continue;
        moved = true;
        // coincident points are separated along an index-dependent direction so the result is deterministic
        const dir = dist < 1e-9 ? normalise([Math.cos(i * 2.4 + j), Math.sin(i * 1.7 + j), Math.cos(j * 3.1)]) : scale(d, 1 / dist);
        const amount = (minimum - dist) * 0.5;
        push[i] = add(push[i], scale(dir, amount));
        push[j] = add(push[j], scale(dir, -amount));
      }
    }
    if (!moved) break;
    current = current.map((p, i) => scale(normalise(add(p, push[i])), radius));
  }
  return current;
}

/** Where a particle is on its way along a line, for a flow animation: t in [0, 1) repeating. */
export function along(a: Vec3, b: Vec3, t: number): Vec3 {
  const f = t - Math.floor(t);
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

/** A depth-based opacity: 1 for the nearest content, `floor` for the farthest. */
export function depthAlpha(depth: number, near: number, far: number, floor = 0.25): number {
  if (far <= near) return 1;
  const t = Math.max(0, Math.min(1, (depth - near) / (far - near)));
  return 1 - (1 - floor) * t;
}
