import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import graphJson from "../atlas/graph.json";
import { cardFor, familyAngles, layoutWeb, type AtlasGraph } from "../atlas/web";
import { Atlas } from "./Atlas";

const GRAPH = graphJson as unknown as AtlasGraph;

describe("the atlas graph", () => {
  it("draws only models that exist, in distinct places, on three rings", () => {
    const placed = layoutWeb(GRAPH);
    expect(placed.length).toBeGreaterThan(40);
    expect(placed.every((p) => p.node.status !== "not_built")).toBe(true);
    expect(new Set(placed.map((p) => `${Math.round(p.x)},${Math.round(p.y)}`)).size).toBe(placed.length);
    expect(new Set(placed.map((p) => p.node.kind))).toEqual(new Set(["model", "baseline", "pipeline"]));
    expect(familyAngles(placed).length).toBeGreaterThan(5);
  });

  it("builds a model card from edges that exist: baselines, recorded verdicts, the finding", () => {
    const card = cardFor(GRAPH, "fno");
    expect(card?.node.label).toBe("Fourier Neural Operator");
    expect(card?.judgedAgainst.map((n) => n.id)).toContain("mlp_operator");
    expect(card?.tests.map((t) => t.label)).toEqual(["Z-O1", "Z-O2", "Z-O3", "Z-O4"]);
    expect(card?.tests.find((t) => t.label === "Z-O4")?.verdict).toBe("CONTRADICTED");
    expect(card?.findings).toEqual(["Finding 30"]);
    expect(cardFor(GRAPH, "no_such_model")).toBeNull();
  });

  it("is the graph the Python registry exports: every edge joins two known nodes", () => {
    const ids = new Set(GRAPH.nodes.map((n) => n.id));
    expect(GRAPH.edges.every((e) => ids.has(e.source) && ids.has(e.target))).toBe(true);
  });
});

describe("the atlas page", () => {
  it("states the real counts and selects a model by click and by keyboard", () => {
    render(
      <MemoryRouter>
        <Atlas />
      </MemoryRouter>,
    );
    expect(screen.getByText(/models were requested/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Fourier Neural Operator" })).toBeInTheDocument();
    const deeponet = screen.getByRole("button", { name: "DeepONet, model" });
    fireEvent.click(deeponet);
    expect(screen.getByRole("heading", { name: "DeepONet" })).toBeInTheDocument();
    expect(deeponet).toHaveAttribute("aria-pressed", "true");
    fireEvent.keyDown(deeponet, { key: "ArrowRight" });
    expect(screen.queryByRole("heading", { name: "DeepONet" })).not.toBeInTheDocument();
    expect(screen.getByText(/deliberately not built, and why/)).toBeInTheDocument();
  });
});

describe("the atlas controls", () => {
  it("falls back to the 2D web when the browser has no canvas, and says what the legend means", () => {
    render(
      <MemoryRouter>
        <Atlas />
      </MemoryRouter>,
    );
    expect(screen.getByRole("group", { name: "Model web" })).toBeInTheDocument(); // the SVG web
    expect(screen.getByText(/Circle: written in the zoo/)).toBeInTheDocument();
  });

  it("selects the model named in the URL", () => {
    render(
      <MemoryRouter initialEntries={["/atlas?model=deeponet"]}>
        <Atlas />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "DeepONet" })).toBeInTheDocument();
  });

  it("ignores an unknown model in the URL", () => {
    render(
      <MemoryRouter initialEntries={["/atlas?model=not-a-model"]}>
        <Atlas />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "Fourier Neural Operator" })).toBeInTheDocument();
  });

  it("lists the families as toggles, with All and None", () => {
    render(
      <MemoryRouter>
        <Atlas />
      </MemoryRouter>,
    );
    const chip = screen.getByRole("button", { name: "operators" });
    expect(chip).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(chip);
    expect(chip).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(chip).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "None" }));
    expect(chip).toHaveAttribute("aria-pressed", "false");
  });

  it("has view, label and line controls", () => {
    render(
      <MemoryRouter>
        <Atlas />
      </MemoryRouter>,
    );
    expect(screen.getByRole("radiogroup", { name: "View" })).toBeInTheDocument();
    expect(screen.getByRole("radiogroup", { name: "Labels (3D)" })).toBeInTheDocument();
    for (const name of ["Judged-against lines", "Model relations", "Pipeline flows"]) {
      expect(screen.getByRole("switch", { name })).toHaveAttribute("aria-checked", "true");
    }
  });
});

