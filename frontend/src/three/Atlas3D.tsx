import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import type { AtlasGraph, AtlasNode } from "../atlas/web";
import {
  DEFAULT_ORBIT,
  type Orbit,
  type Projected,
  type Vec3,
  along,
  depthAlpha,
  depthOrder,
  dragOrbit,
  layoutWeb3,
  pick,
  project,
  scale as scaleVec,
  stepOrbit,
  zoomOrbit,
} from "./engine";

// The 3-D model web: a canvas that draws the registry's graph on spheres (families as clusters on the
// outer shell, baselines inside, pipelines at the core). Drag to orbit (with inertia), wheel or pinch to
// zoom, click to select, keyboard for everything. It draws only what `engine.ts` computes. With motion
// reduced it never animates by itself; with no canvas it says so and the 2-D web takes over.

export interface Colours {
  bg: string;
  surface: string;
  ink: string;
  muted: string;
  a: string;
  b: string;
  c: string;
}

export interface Filters {
  baselines: boolean;
  relations: boolean;
  feeds: boolean;
}

interface Props {
  graph: AtlasGraph;
  selected: string;
  onSelect: (id: string) => void;
  colours: Colours;
  autoRotate: boolean;
  onAutoRotate: (on: boolean) => void;
  labels: "selected" | "all" | "none";
  quality: "auto" | "low";
  reducedMotion: boolean;
  filters: Filters;
  hiddenFamilies: ReadonlySet<string>;
  onUnsupported?: () => void;
}

const RELATION_KINDS = new Set(["extends", "alternative_to", "uses"]);

function edgeVisible(kind: string, f: Filters): boolean {
  if (kind === "baseline_for") return f.baselines;
  if (kind === "feeds") return f.feeds;
  return RELATION_KINDS.has(kind) && f.relations;
}

export function Atlas3D({
  graph,
  selected,
  onSelect,
  colours,
  autoRotate,
  onAutoRotate,
  labels,
  quality,
  reducedMotion,
  filters,
  hiddenFamilies,
  onUnsupported,
}: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [supported, setSupported] = useState(true);
  const [announcement, setAnnouncement] = useState("");

  const layout = useMemo(() => layoutWeb3(graph.nodes, graph.edges), [graph]);
  const nodes = useMemo(() => {
    const byId = new Map(graph.nodes.map((n) => [n.id, n]));
    return layout.map((p) => ({ ...(byId.get(p.id) as AtlasNode), position: p.position as Vec3 }));
  }, [graph, layout]);
  const index = useMemo(() => new Map(nodes.map((n, i) => [n.id, i])), [nodes]);
  const visible = useMemo(() => nodes.map((n) => n.kind !== "model" || !hiddenFamilies.has(n.family)), [nodes, hiddenFamilies]);
  const edges = useMemo(
    () =>
      graph.edges.filter(
        (e) =>
          (e.kind === "baseline_for" || e.kind === "feeds" || RELATION_KINDS.has(e.kind)) &&
          index.has(e.source) &&
          index.has(e.target),
      ),
    [graph, index],
  );
  const families = useMemo(() => {
    const out = new Map<string, Vec3[]>();
    for (const n of nodes) if (n.kind === "model") out.set(n.family, [...(out.get(n.family) ?? []), n.position]);
    return [...out.entries()].map(([family, pts]) => {
      const sum = pts.reduce<Vec3>((s, p) => [s[0] + p[0], s[1] + p[1], s[2] + p[2]], [0, 0, 0]);
      return { family, position: scaleVec(sum, 1.2 / pts.length) as Vec3 };
    });
  }, [nodes]);

  // everything the animation loop reads lives in refs, so a re-render never restarts it
  const orbit = useRef<Orbit>({ ...DEFAULT_ORBIT });
  const dragging = useRef(false);
  const hover = useRef(-1);
  const dirty = useRef(true);
  const size = useRef({ width: 600, height: 480, dpr: 1 });
  const props = useRef({ selected, colours, autoRotate, labels, quality, reducedMotion, filters, visible });
  props.current = { selected, colours, autoRotate, labels, quality, reducedMotion, filters, visible };
  const frame = useRef<{ projected: Projected[]; radii: number[] }>({ projected: [], radii: [] });

  const draw = useCallback(
    (time: number) => {
      const el = canvas.current;
      const ctx = el?.getContext("2d");
      if (!el || !ctx) return;
      const { width, height, dpr } = size.current;
      const p = props.current;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      const camera = orbit.current;
      const view = { width, height };
      const projected = nodes.map((n) => project(n.position, camera, view));
      const radii = projected.map((q, i) => (nodes[i].kind === "pipeline" ? 0.034 : 0.026) * q.scale + 5);
      frame.current = { projected, radii };
      const near = camera.distance - 1.1;
      const far = camera.distance + 1.1;
      const selectedIndex = index.get(p.selected) ?? -1;
      const neighbours = new Set<number>();
      edges.forEach((e) => {
        const a = index.get(e.source) as number;
        const b = index.get(e.target) as number;
        if (a === selectedIndex) neighbours.add(b);
        if (b === selectedIndex) neighbours.add(a);
      });

      // orientation guides: three great circles of the outer shell
      ctx.lineWidth = 1;
      ctx.setLineDash([]);
      for (const axis of [0, 1, 2]) {
        ctx.beginPath();
        for (let k = 0; k <= 72; k++) {
          const t = (k / 72) * Math.PI * 2;
          const c = Math.cos(t);
          const s = Math.sin(t);
          const pt: Vec3 = axis === 0 ? [0, c, s] : axis === 1 ? [c, 0, s] : [c, s, 0];
          const q = project(pt, camera, view);
          if (k === 0) ctx.moveTo(q.x, q.y);
          else ctx.lineTo(q.x, q.y);
        }
        ctx.globalAlpha = 0.1;
        ctx.strokeStyle = p.colours.muted;
        ctx.stroke();
      }

      // edges
      for (const e of edges) {
        if (!edgeVisible(e.kind, p.filters)) continue;
        const ia = index.get(e.source) as number;
        const ib = index.get(e.target) as number;
        if (!p.visible[ia] || !p.visible[ib]) continue;
        const qa = projected[ia];
        const qb = projected[ib];
        if (!qa.visible || !qb.visible) continue;
        const touches = ia === selectedIndex || ib === selectedIndex;
        const fade = depthAlpha((qa.depth + qb.depth) / 2, near, far, 0.3);
        ctx.globalAlpha = touches ? 0.95 : 0.28 * fade;
        ctx.strokeStyle = touches ? p.colours.c : e.kind === "feeds" ? p.colours.a : p.colours.muted;
        ctx.lineWidth = e.kind === "feeds" ? 2.6 : touches ? 2 : 1;
        ctx.setLineDash(e.kind === "baseline_for" ? [2, 5] : e.kind === "alternative_to" ? [7, 5] : []);
        ctx.beginPath();
        ctx.moveTo(qa.x, qa.y);
        ctx.lineTo(qb.x, qb.y);
        ctx.stroke();
        if (e.kind === "feeds" && !p.reducedMotion) {
          ctx.setLineDash([]);
          ctx.fillStyle = p.colours.c;
          for (let k = 0; k < 3; k++) {
            const w = along(nodes[ia].position, nodes[ib].position, time * 0.00035 + k / 3);
            const q = project(w, camera, view);
            ctx.globalAlpha = 0.9;
            ctx.beginPath();
            ctx.arc(q.x, q.y, 2.6, 0, Math.PI * 2);
            ctx.fill();
          }
        }
      }
      ctx.setLineDash([]);

      // nodes, far to near
      const labelQueue: { i: number; strong: boolean }[] = [];
      for (const i of depthOrder(projected)) {
        const q = projected[i];
        const n = nodes[i];
        if (!q.visible || !p.visible[i]) continue;
        const r = radii[i] - 5;
        const isSel = i === selectedIndex;
        ctx.globalAlpha = isSel ? 1 : depthAlpha(q.depth, near, far, 0.32);
        ctx.lineWidth = isSel ? 3 : 1.5;
        ctx.strokeStyle = isSel ? p.colours.c : p.colours.ink;
        ctx.fillStyle = n.kind === "model" && n.status === "implemented" ? p.colours.a : p.colours.surface;
        if (isSel && p.quality !== "low") {
          ctx.shadowColor = p.colours.c;
          ctx.shadowBlur = 18;
        }
        ctx.beginPath();
        if (n.kind === "baseline") {
          ctx.moveTo(q.x, q.y - r * 1.2);
          ctx.lineTo(q.x + r * 1.2, q.y);
          ctx.lineTo(q.x, q.y + r * 1.2);
          ctx.lineTo(q.x - r * 1.2, q.y);
          ctx.closePath();
        } else if (n.kind === "pipeline") {
          ctx.arc(q.x, q.y, r * 1.35, 0, Math.PI * 2);
          ctx.fillStyle = "rgba(0,0,0,0)";
        } else if (n.status === "existing") {
          ctx.rect(q.x - r, q.y - r, r * 2, r * 2);
        } else {
          ctx.arc(q.x, q.y, r, 0, Math.PI * 2);
        }
        ctx.fill();
        ctx.stroke();
        ctx.shadowBlur = 0;
        const hovered = i === hover.current;
        if (isSel || hovered || neighbours.has(i)) labelQueue.push({ i, strong: true });
        else if (p.labels === "all" && q.depth < camera.distance) labelQueue.push({ i, strong: false });
      }

      // labels (with a halo so they read over lines), family names at the cluster centres
      ctx.font = "12px Inter, system-ui, sans-serif";
      ctx.textBaseline = "middle";
      const drawLabel = (text: string, x: number, y: number, alpha: number, colour: string) => {
        ctx.globalAlpha = alpha;
        ctx.lineWidth = 4;
        ctx.strokeStyle = p.colours.bg;
        ctx.strokeText(text, x, y);
        ctx.fillStyle = colour;
        ctx.fillText(text, x, y);
      };
      if (p.labels !== "none") {
        ctx.textAlign = "center";
        ctx.font = "600 11px Inter, system-ui, sans-serif";
        for (const f of families) {
          const q = project(f.position, camera, view);
          if (q.visible) drawLabel(f.family.toUpperCase(), q.x, q.y, 0.55 * depthAlpha(q.depth, near, far, 0.35), p.colours.muted);
        }
      }
      ctx.font = "12px Inter, system-ui, sans-serif";
      ctx.textAlign = "left";
      for (const { i, strong } of labelQueue) {
        const q = projected[i];
        const text = nodes[i].label;
        const textWidth = ctx.measureText(text).width;
        // keep the label inside the canvas: flip it to the other side of the node near the right edge
        const right = q.x + radii[i] + 4;
        const x = right + textWidth > width - 6 ? q.x - radii[i] - 4 - textWidth : right;
        drawLabel(text, Math.max(6, x), q.y, strong ? 1 : 0.7 * depthAlpha(q.depth, near, far, 0.3), strong ? p.colours.ink : p.colours.muted);
      }
      ctx.globalAlpha = 1;
    },
    [nodes, edges, index, families],
  );

  // canvas size, device pixel ratio and the animation loop
  useEffect(() => {
    const el = canvas.current;
    const host = wrap.current;
    if (!el || !host) return;
    let context: CanvasRenderingContext2D | null = null;
    try {
      context = el.getContext("2d");
    } catch {
      context = null;
    }
    if (!context) {
      setSupported(false);
      onUnsupported?.();
      return;
    }
    const resize = () => {
      const rect = host.getBoundingClientRect();
      const cap = props.current.quality === "low" ? 1 : 2;
      const dpr = Math.min(typeof window.devicePixelRatio === "number" ? window.devicePixelRatio : 1, cap);
      const width = Math.max(rect.width, 240);
      const height = Math.max(rect.height, 240);
      size.current = { width, height, dpr };
      el.width = Math.round(width * dpr);
      el.height = Math.round(height * dpr);
      dirty.current = true;
    };
    resize();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
    observer?.observe(host);
    window.addEventListener("resize", resize);

    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      raf = window.requestAnimationFrame(loop);
      if (document.hidden) {
        last = now;
        return;
      }
      const dt = Math.min((now - last) / 1000, 0.1);
      last = now;
      const p = props.current;
      const rotating = p.autoRotate && !p.reducedMotion;
      const moving = Math.abs(orbit.current.yawVelocity) > 0 || Math.abs(orbit.current.pitchVelocity) > 0;
      if (rotating || moving || dragging.current) {
        orbit.current = stepOrbit(orbit.current, dt, { dragging: dragging.current, autoRotate: rotating });
        dirty.current = true;
      }
      const flowing = !p.reducedMotion && p.filters.feeds;
      if (dirty.current || flowing) {
        draw(now);
        dirty.current = false;
      }
    };
    raf = window.requestAnimationFrame(loop);
    return () => {
      window.cancelAnimationFrame(raf);
      observer?.disconnect();
      window.removeEventListener("resize", resize);
    };
  }, [draw, onUnsupported]);

  useEffect(() => {
    dirty.current = true;
  }, [selected, colours, labels, filters, hiddenFamilies, quality, reducedMotion]);

  useEffect(() => {
    const n = nodes[index.get(selected) ?? -1];
    setAnnouncement(n ? `${n.label}, ${n.kind}` : "");
  }, [selected, nodes, index]);

  // wheel zoom needs a non-passive listener to stop the page from scrolling
  useEffect(() => {
    const host = wrap.current;
    if (!host) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      orbit.current = zoomOrbit(orbit.current, Math.exp(e.deltaY * 0.0012));
      dirty.current = true;
    };
    host.addEventListener("wheel", onWheel, { passive: false });
    return () => host.removeEventListener("wheel", onWheel);
  }, []);

  // pointers: one drags (and clicks), two pinch
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const gesture = useRef({ moved: 0, time: 0, pinch: 0 });

  const local = (e: { clientX: number; clientY: number }) => {
    const rect = wrap.current?.getBoundingClientRect();
    return { x: e.clientX - (rect?.left ?? 0), y: e.clientY - (rect?.top ?? 0) };
  };

  const hit = (x: number, y: number): number => {
    const { projected, radii } = frame.current;
    const i = pick(projected, radii, x, y);
    return i >= 0 && props.current.visible[i] ? i : -1;
  };

  const step = (delta: number) => {
    const order = nodes.map((_, i) => i).filter((i) => props.current.visible[i]);
    if (order.length === 0) return;
    const at = order.indexOf(index.get(props.current.selected) ?? -1);
    onSelect(nodes[order[(at + delta + order.length) % order.length]].id);
  };

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    const o = orbit.current;
    const nudge = (yaw: number, pitch: number) => {
      orbit.current = { ...o, yawVelocity: yaw, pitchVelocity: pitch };
      dirty.current = true;
    };
    switch (e.key) {
      case "ArrowLeft": e.preventDefault(); nudge(-1.4, 0); break;
      case "ArrowRight": e.preventDefault(); nudge(1.4, 0); break;
      case "ArrowUp": e.preventDefault(); nudge(0, -1.1); break;
      case "ArrowDown": e.preventDefault(); nudge(0, 1.1); break;
      case "+":
      case "=": e.preventDefault(); orbit.current = zoomOrbit(o, 0.85); dirty.current = true; break;
      case "-":
      case "_": e.preventDefault(); orbit.current = zoomOrbit(o, 1.18); dirty.current = true; break;
      case "0": e.preventDefault(); orbit.current = { ...DEFAULT_ORBIT }; dirty.current = true; break;
      case "]": e.preventDefault(); step(1); break;
      case "[": e.preventDefault(); step(-1); break;
      default: break;
    }
  };

  return (
    <div className="relative">
      <div
        ref={wrap}
        tabIndex={0}
        role="group"
        aria-label="Interactive 3D model web. Drag to rotate, scroll or pinch to zoom, arrow keys rotate, plus and minus zoom, zero resets the view, and the left and right bracket keys choose the previous or next model."
        data-testid="atlas-3d"
        className="relative h-[520px] w-full cursor-grab touch-none select-none overflow-hidden rounded-xl active:cursor-grabbing"
        onKeyDown={onKeyDown}
        onPointerDown={(e) => {
          wrap.current?.setPointerCapture?.(e.pointerId);
          pointers.current.set(e.pointerId, local(e));
          gesture.current = { moved: 0, time: performance.now(), pinch: 0 };
          dragging.current = pointers.current.size === 1;
        }}
        onPointerMove={(e) => {
          const point = local(e);
          const before = pointers.current.get(e.pointerId);
          if (!before) {
            const h = hit(point.x, point.y);
            if (h !== hover.current) {
              hover.current = h;
              dirty.current = true;
            }
            return;
          }
          pointers.current.set(e.pointerId, point);
          const now = performance.now();
          if (pointers.current.size === 2) {
            const [a, b] = [...pointers.current.values()];
            const d = Math.hypot(a.x - b.x, a.y - b.y);
            if (gesture.current.pinch > 0 && d > 0) orbit.current = zoomOrbit(orbit.current, gesture.current.pinch / d);
            gesture.current.pinch = d;
            dirty.current = true;
            return;
          }
          const dx = point.x - before.x;
          const dy = point.y - before.y;
          gesture.current.moved += Math.abs(dx) + Math.abs(dy);
          orbit.current = dragOrbit(orbit.current, dx, dy, Math.max((now - gesture.current.time) / 1000, 0.008));
          gesture.current.time = now;
          dirty.current = true;
        }}
        onPointerUp={(e) => {
          const point = local(e);
          pointers.current.delete(e.pointerId);
          wrap.current?.releasePointerCapture?.(e.pointerId);
          dragging.current = false;
          if (pointers.current.size === 0 && gesture.current.moved < 6) {
            const h = hit(point.x, point.y);
            if (h >= 0) onSelect(nodes[h].id);
          }
        }}
        onPointerCancel={(e) => {
          pointers.current.delete(e.pointerId);
          dragging.current = false;
        }}
        onPointerLeave={() => {
          if (hover.current !== -1) {
            hover.current = -1;
            dirty.current = true;
          }
        }}
        onDoubleClick={() => {
          orbit.current = { ...DEFAULT_ORBIT };
          dirty.current = true;
        }}
      >
        <canvas ref={canvas} className="h-full w-full" aria-hidden="true" />
        {!supported && (
          <p role="alert" className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-slate-300">
            This browser cannot draw the 3D view. The 2D web shows the same graph.
          </p>
        )}
      </div>
      <div role="toolbar" aria-label="3D view controls" className="absolute right-3 top-3 flex flex-col gap-1.5">
        {[
          { label: "Zoom in", text: "+", run: () => (orbit.current = zoomOrbit(orbit.current, 0.8)) },
          { label: "Zoom out", text: "−", run: () => (orbit.current = zoomOrbit(orbit.current, 1.25)) },
          { label: "Reset the view", text: "⟲", run: () => (orbit.current = { ...DEFAULT_ORBIT }) },
        ].map((b) => (
          <button
            key={b.label}
            type="button"
            aria-label={b.label}
            title={b.label}
            onClick={() => {
              b.run();
              dirty.current = true;
            }}
            className="h-9 w-9 rounded-lg border border-white/15 bg-base-elevated/80 text-lg leading-none text-slate-100 hover:bg-white/15"
          >
            {b.text}
          </button>
        ))}
        <button
          type="button"
          aria-label="Auto-rotate"
          aria-pressed={autoRotate && !reducedMotion}
          disabled={reducedMotion}
          title={reducedMotion ? "Motion is reduced in the settings" : "Auto-rotate"}
          onClick={() => onAutoRotate(!autoRotate)}
          className={`h-9 w-9 rounded-lg border text-base leading-none disabled:opacity-40 ${
            autoRotate && !reducedMotion ? "border-accent-c bg-accent-c/25 text-slate-50" : "border-white/15 bg-base-elevated/80 text-slate-100 hover:bg-white/15"
          }`}
        >
          ↻
        </button>
      </div>
      <div role="status" aria-live="polite" className="sr-only-live">
        {announcement}
      </div>
    </div>
  );
}
