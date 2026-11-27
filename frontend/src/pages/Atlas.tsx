import { useMemo, useState } from "react";

import graphJson from "../atlas/graph.json";
import {
  CENTRE,
  EDGE_KINDS,
  OUTER,
  SIZE,
  cardFor,
  familyAngles,
  layoutWeb,
  type AtlasGraph,
  type AtlasNode,
} from "../atlas/web";
import { GlassCard } from "../components/GlassCard";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";

// The model zoo as a web. `../atlas/graph.json` is generated from the Python registry
// (`econosim modelzoo graph`) and a Python test fails if it goes stale, so every edge drawn here is
// a fact about the code and the recorded studies: the page reads a file, it does not call an API,
// and it works the same in the demo edition.

function Shape({ node, selected }: { node: AtlasNode; selected: boolean }) {
  const stroke = selected ? "stroke-cyan-300" : "stroke-slate-300";
  const width = selected ? 3 : 1.5;
  if (node.kind === "baseline") {
    return (
      <polygon
        points="0,-9 9,0 0,9 -9,0"
        className={`fill-slate-800 ${stroke}`}
        strokeWidth={width}
      />
    );
  }
  if (node.kind === "pipeline") {
    return <circle r={13} className={`fill-none ${stroke}`} strokeWidth={width} />;
  }
  if (node.status === "existing") {
    return <rect x={-8} y={-8} width={16} height={16} className={`fill-slate-800 ${stroke}`} strokeWidth={width} />;
  }
  return <circle r={8} className={`fill-violet-500 ${stroke}`} strokeWidth={width} />;
}

const GRAPH = graphJson as unknown as AtlasGraph;
const VERDICT_TONE = { SUPPORTED: "good", CONTRADICTED: "bad", INCONCLUSIVE: "pending" } as const;

export function Atlas() {
  const placed = useMemo(() => layoutWeb(GRAPH), []);
  const positions = useMemo(() => new Map(placed.map((p) => [p.node.id, p])), [placed]);
  const edges = useMemo(
    () => GRAPH.edges.filter((e) => EDGE_KINDS.includes(e.kind) && positions.has(e.source) && positions.has(e.target)),
    [positions],
  );
  const [selected, setSelected] = useState<string>("fno");
  const [hover, setHover] = useState<string | null>(null);
  const card = cardFor(GRAPH, selected);
  const notBuilt = GRAPH.nodes.filter((n) => n.kind === "not_built");
  const models = GRAPH.nodes.filter((n) => n.kind === "model" || n.kind === "not_built");
  const count = (status: string) => models.filter((n) => n.status === status).length;
  const verdicts = GRAPH.nodes.filter((n) => n.kind === "hypothesis");
  const verdictCount = (v: string) => verdicts.filter((n) => n.status === v).length;
  const neighbours = new Set(
    edges.filter((e) => e.source === selected || e.target === selected).flatMap((e) => [e.source, e.target]),
  );

  function move(step: number) {
    const ids = placed.map((p) => p.node.id);
    const index = ids.indexOf(selected);
    setSelected(ids[(index + step + ids.length) % ids.length]);
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Atlas"
        description="The model zoo as a web. Every line is an edge of a graph checked against the code and the recorded studies."
      />
      <p className="text-sm text-slate-300">
        {models.length} models were requested: {count("implemented")} written in the zoo,{" "}
        {count("existing")} already in this repository, {count("not_built")} deliberately not built.{" "}
        {verdicts.length} hypotheses recorded: {verdictCount("SUPPORTED")} supported,{" "}
        {verdictCount("INCONCLUSIVE")} inconclusive, {verdictCount("CONTRADICTED")} contradicted.
      </p>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <GlassCard className="p-3">
          <svg
            viewBox={`0 0 ${SIZE} ${SIZE}`}
            role="group"
            aria-label="Model web"
            className="h-auto w-full"
            onKeyDown={(e) => {
              if (e.key === "ArrowRight" || e.key === "ArrowDown") {
                e.preventDefault();
                move(1);
              } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
                e.preventDefault();
                move(-1);
              }
            }}
          >
            {edges.map((e) => {
              const a = positions.get(e.source);
              const b = positions.get(e.target);
              if (!a || !b) return null;
              const touches = e.source === selected || e.target === selected;
              return (
                <line
                  key={`${e.source}-${e.target}-${e.kind}`}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  className={touches ? "stroke-cyan-300" : "stroke-slate-500/40"}
                  strokeWidth={e.kind === "feeds" ? 3 : touches ? 2 : 1}
                  strokeDasharray={e.kind === "baseline_for" ? "2 4" : e.kind === "alternative_to" ? "6 4" : undefined}
                />
              );
            })}
            {familyAngles(placed).map(([family, angle]) => (
              <text
                key={family}
                x={CENTRE + (OUTER + 38) * Math.cos(angle)}
                y={CENTRE + (OUTER + 38) * Math.sin(angle)}
                textAnchor="middle"
                dominantBaseline="middle"
                className="fill-slate-500 text-[13px] font-semibold"
              >
                {family}
              </text>
            ))}
            {placed.map((p) => {
              const on = p.node.id === selected;
              const showLabel = on || hover === p.node.id || neighbours.has(p.node.id);
              return (
                <g
                  key={p.node.id}
                  transform={`translate(${p.x} ${p.y})`}
                  tabIndex={0}
                  role="button"
                  aria-pressed={on}
                  aria-label={`${p.node.label}, ${p.node.kind}`}
                  className="cursor-pointer outline-none focus-visible:[&>*]:stroke-cyan-200"
                  onClick={() => setSelected(p.node.id)}
                  onFocus={() => setHover(p.node.id)}
                  onBlur={() => setHover(null)}
                  onMouseEnter={() => setHover(p.node.id)}
                  onMouseLeave={() => setHover(null)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setSelected(p.node.id);
                    }
                  }}
                >
                  <Shape node={p.node} selected={on} />
                  {showLabel && (
                    <text
                      x={p.x >= CENTRE ? 14 : -14}
                      textAnchor={p.x >= CENTRE ? "start" : "end"}
                      dominantBaseline="middle"
                      className="pointer-events-none fill-slate-100 text-[13px]"
                      paintOrder="stroke"
                      stroke="#0b0d12"
                      strokeWidth={4}
                    >
                      {p.node.label}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
          <p className="px-2 pb-1 text-xs text-slate-400">
            Circle: written in the zoo. Square: already in the repository. Diamond: baseline. Ring:
            pipeline. Dotted: judged against. Heavy line: feeds. Arrow keys move between models.
          </p>
        </GlassCard>
        <div className="flex flex-col gap-4">
          {card && (
            <GlassCard className="p-5">
              <h2 className="text-lg font-semibold text-slate-50">{card.node.label}</h2>
              <p className="text-xs uppercase tracking-wider text-slate-500">
                {card.node.kind} · {card.node.family} · {card.node.status.replace("_", " ")}
              </p>
              {card.node.reference && <p className="mt-2 text-sm text-slate-400">{card.node.reference}</p>}
              {card.node.task && <p className="mt-2 text-sm text-slate-300">{card.node.task}</p>}
              {card.judgedAgainst.length > 0 && (
                <p className="mt-3 text-sm text-slate-300">
                  <span className="text-slate-500">Judged against: </span>
                  {card.judgedAgainst.map((n) => n.label).join(", ")}
                </p>
              )}
              {card.tests.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {card.tests.map((t) => (
                    <StatusBadge
                      key={t.label}
                      label={`${t.label} ${t.verdict.toLowerCase()}`}
                      tone={VERDICT_TONE[t.verdict as keyof typeof VERDICT_TONE] ?? "neutral"}
                    />
                  ))}
                </div>
              )}
              {card.findings.length > 0 && (
                <p className="mt-3 text-sm text-slate-400">Reported in {card.findings.join(", ")}.</p>
              )}
              {card.linked.length > 0 && (
                <p className="mt-3 text-sm text-slate-400">
                  Linked to: {card.linked.map((n) => n.label).join(", ")}.
                </p>
              )}
            </GlassCard>
          )}
          <GlassCard className="p-5">
            <details>
              <summary className="cursor-pointer text-sm font-medium text-slate-200">
                {notBuilt.length} models deliberately not built, and why
              </summary>
              <ul className="mt-3 flex max-h-72 flex-col gap-2 overflow-y-auto pr-1 text-sm">
                {notBuilt.map((n) => (
                  <li key={n.id} className="text-slate-300">
                    <span className="font-medium text-slate-100">{n.label}</span>
                    <span className="text-slate-500"> — {n.task}</span>
                  </li>
                ))}
              </ul>
            </details>
          </GlassCard>
        </div>
      </div>
    </div>
  );
}
