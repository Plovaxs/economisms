// Pure logic of the atlas page: types, the ring layout and the model card. Kept out of the
// component file so the page file exports only a component.

export interface AtlasNode {
  id: string;
  label: string;
  kind: "model" | "baseline" | "not_built" | "dataset" | "hypothesis" | "finding" | "pipeline";
  family: string;
  status: string;
  source?: string;
  task?: string;
  reference?: string;
  benchmarked?: boolean;
}

export interface AtlasEdge {
  source: string;
  target: string;
  kind: string;
}

export interface AtlasGraph {
  nodes: AtlasNode[];
  edges: AtlasEdge[];
}

export const SIZE = 800;
export const CENTRE = SIZE / 2;
export const OUTER = 290;
export const DRAWN: AtlasNode["kind"][] = ["model", "baseline", "pipeline"];
export const EDGE_KINDS = ["baseline_for", "extends", "alternative_to", "uses", "feeds"];


export interface Placed {
  node: AtlasNode;
  x: number;
  y: number;
  angle: number;
}

/** Models on the outer ring grouped by family, baselines inside, pipelines in the middle. */
export function layoutWeb(graph: AtlasGraph): Placed[] {
  const drawn = graph.nodes.filter((n) => DRAWN.includes(n.kind) && n.status !== "not_built");
  const byKind = (kind: AtlasNode["kind"]) =>
    drawn
      .filter((n) => n.kind === kind)
      .sort((a, b) => a.family.localeCompare(b.family) || a.id.localeCompare(b.id));
  const rings: [AtlasNode["kind"], number, number][] = [
    ["model", OUTER, 0],
    ["baseline", OUTER * 0.58, 0.5],
    ["pipeline", OUTER * 0.16, 0],
  ];
  const placed: Placed[] = [];
  for (const [kind, radius, shift] of rings) {
    const ring = byKind(kind);
    ring.forEach((node, index) => {
      const angle =
        kind === "pipeline" && ring.length === 1
          ? -Math.PI / 2
          : -Math.PI / 2 + (2 * Math.PI * (index + shift)) / Math.max(ring.length, 1);
      placed.push({
        node,
        x: CENTRE + radius * Math.cos(angle),
        y: CENTRE + radius * Math.sin(angle),
        angle,
      });
    });
  }
  return placed;
}

export function familyAngles(placed: Placed[]): [string, number][] {
  const sums = new Map<string, number[]>();
  for (const p of placed) {
    if (p.node.kind !== "model") continue;
    sums.set(p.node.family, [...(sums.get(p.node.family) ?? []), p.angle]);
  }
  return [...sums.entries()].map(([family, angles]) => [
    family,
    angles.reduce((a, b) => a + b, 0) / angles.length,
  ]);
}

export interface Card {
  node: AtlasNode;
  judgedAgainst: AtlasNode[];
  tests: { label: string; verdict: string }[];
  findings: string[];
  linked: AtlasNode[];
}

export function cardFor(graph: AtlasGraph, id: string): Card | null {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const node = byId.get(id);
  if (!node) return null;
  const at = (ids: string[]) => ids.map((i) => byId.get(i)).filter((n): n is AtlasNode => !!n);
  const judgedAgainst = at(
    graph.edges.filter((e) => e.kind === "baseline_for" && e.target === id).map((e) => e.source),
  );
  const hypotheses = at(
    graph.edges.filter((e) => e.kind === "tested_by" && e.source === id).map((e) => e.target),
  );
  const findings = new Set(
    graph.edges
      .filter((e) => e.kind === "reported_in" && hypotheses.some((h) => h.id === e.source))
      .map((e) => byId.get(e.target)?.label ?? e.target),
  );
  const linked = at(
    graph.edges
      .filter(
        (e) =>
          ["extends", "alternative_to", "uses", "feeds"].includes(e.kind) &&
          (e.source === id || e.target === id),
      )
      .map((e) => (e.source === id ? e.target : e.source)),
  );
  return {
    node,
    judgedAgainst,
    tests: hypotheses.map((h) => ({ label: h.label, verdict: h.status })),
    findings: [...findings].sort(),
    linked,
  };
}

