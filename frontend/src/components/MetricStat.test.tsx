import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MetricStat } from "./MetricStat";
import { StatusBadge } from "./StatusBadge";

describe("MetricStat", () => {
  it("renders the real label and value passed in, not a placeholder", () => {
    render(<MetricStat label="GRU observed coverage" value="10.7%" />);
    expect(screen.getByText("GRU observed coverage")).toBeInTheDocument();
    expect(screen.getByText("10.7%")).toBeInTheDocument();
  });
});

describe("StatusBadge", () => {
  it("renders the exact status label passed in", () => {
    render(<StatusBadge label="classical better" tone="bad" />);
    expect(screen.getByText("classical better")).toBeInTheDocument();
  });
});
