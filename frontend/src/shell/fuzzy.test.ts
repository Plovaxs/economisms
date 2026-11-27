import { describe, expect, it } from "vitest";

import { fuzzyScore, rank } from "./fuzzy";

describe("fuzzyScore", () => {
  it("matches a subsequence in order and rejects anything else", () => {
    expect(fuzzyScore("mkt", "Market paths")).not.toBeNull();
    expect(fuzzyScore("tkm", "Market paths")).toBeNull();
    expect(fuzzyScore("zzz", "Market paths")).toBeNull();
    expect(fuzzyScore("", "anything")).toBe(0);
  });

  it("prefers a prefix, a whole piece and word starts over scattered letters", () => {
    const prefix = fuzzyScore("mar", "Market paths") ?? 0;
    const scattered = fuzzyScore("mar", "Balance sheets: more arrays") ?? 0;
    expect(prefix).toBeGreaterThan(scattered);
    expect((fuzzyScore("hedge", "Hedge actions") ?? 0)).toBeGreaterThan(fuzzyScore("hedge", "Overview of hedged things") ?? 0);
  });

  it("is case-insensitive and ignores spaces in the query", () => {
    expect(fuzzyScore("PORT RISK", "Portfolio risk")).not.toBeNull();
  });
});

describe("rank", () => {
  const items = [
    { label: "Settings", keywords: "theme font accessibility" },
    { label: "Economy explorer" },
    { label: "Portfolio risk", keywords: "var shortfall" },
    { label: "Pricing diagnostics", keywords: "greeks" },
  ];

  it("returns the best match first, searches keywords, and drops non-matches", () => {
    expect(rank("port", items)[0].label).toBe("Portfolio risk");
    expect(rank("greeks", items).map((i) => i.label)).toEqual(["Pricing diagnostics"]);
    expect(rank("accessib", items)[0].label).toBe("Settings");
    expect(rank("qqq", items)).toEqual([]);
  });

  it("keeps the original order for an empty query and honours the limit", () => {
    expect(rank("", items).map((i) => i.label)).toEqual(items.map((i) => i.label));
    expect(rank("", items, 2)).toHaveLength(2);
  });
});
