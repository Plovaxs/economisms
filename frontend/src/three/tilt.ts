/** Lean angles (degrees) for a card when the pointer is at (x, y) inside a width x height box:
 * zero at the centre, at most `max` at the edges, tilting toward the pointer. */
export function tiltFor(x: number, y: number, width: number, height: number, max = 6): { x: number; y: number } {
  if (width <= 0 || height <= 0) return { x: 0, y: 0 };
  const nx = Math.max(-1, Math.min(1, (x / width) * 2 - 1));
  const ny = Math.max(-1, Math.min(1, (y / height) * 2 - 1));
  // pointer low on the card tips the top toward the viewer (negative X rotation), and so on
  return { x: round(-ny * max), y: round(nx * max) };
}

function round(v: number): number {
  return Math.round(v * 100) / 100 + 0; // + 0 normalises -0
}
