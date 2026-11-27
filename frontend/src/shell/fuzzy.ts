// A small fuzzy matcher for the command palette: every query character must appear in order
// (a subsequence match), with a bonus for matches at word starts, for consecutive characters and for
// a prefix, and a small penalty for a long target. No match scores null.

export function fuzzyScore(query: string, text: string): number | null {
  const q = query.trim().toLowerCase();
  if (q === "") return 0;
  const t = text.toLowerCase();
  let score = 0;
  let from = 0;
  let previous = -2;
  for (const ch of q) {
    if (ch === " ") {
      previous = -2;
      continue;
    }
    const index = t.indexOf(ch, from);
    if (index === -1) return null;
    score += 1;
    if (index === previous + 1) score += 2; // consecutive
    if (index === 0 || /[\s\-:/]/.test(t[index - 1] ?? "")) score += 3; // word start
    previous = index;
    from = index + 1;
  }
  if (t.startsWith(q)) score += 6;
  if (t.includes(q)) score += 4; // the query appears as one piece
  return score - t.length * 0.02;
}

export interface Searchable {
  label: string;
  keywords?: string;
}

/** Items matching the query, best first; an empty query keeps the original order. */
export function rank<T extends Searchable>(query: string, items: readonly T[], limit = 40): T[] {
  if (query.trim() === "") return items.slice(0, limit);
  const scored: [T, number][] = [];
  for (const item of items) {
    const direct = fuzzyScore(query, item.label);
    const viaKeywords = item.keywords ? fuzzyScore(query, item.keywords) : null;
    const best = Math.max(direct ?? -Infinity, viaKeywords === null ? -Infinity : viaKeywords - 3);
    if (best > -Infinity) scored.push([item, best]);
  }
  return scored.sort((a, b) => b[1] - a[1]).slice(0, limit).map(([i]) => i);
}
