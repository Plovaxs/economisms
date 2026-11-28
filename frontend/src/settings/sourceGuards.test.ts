import { describe, expect, it } from "vitest";

// The theme tests compute contrast for the colours a theme defines. These guards keep the markup from
// quietly undoing that arithmetic: a translucent text element is a different, unchecked colour.
const sources = import.meta.glob("../**/*.tsx", { query: "?raw", import: "default", eager: true }) as Record<
  string,
  string
>;

describe("component markup", () => {
  it("finds the components it is meant to guard", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(20);
  });

  it("never dims text with an opacity utility (it would defeat the computed contrast)", () => {
    const offenders: string[] = [];
    for (const [file, text] of Object.entries(sources)) {
      if (/\.test\.tsx$/.test(file)) continue;
      text.split("\n").forEach((line, index) => {
        // `disabled:opacity-40` and `hover:opacity-90` are states, `before:`/`after:` are decoration
        const plain = line.match(/(?<![:\w-])opacity-\d+/);
        if (plain) offenders.push(`${file}:${index + 1}  ${line.trim().slice(0, 90)}`);
      });
    }
    expect(offenders).toEqual([]);
  });

  it("tints a selected or active surface with the accent at 10% at most", () => {
    // The theme tests compute text contrast on the accent at 10% over a card. A stronger tint under
    // text would be a surface nobody measured. (The switch track at 60% carries no text.)
    const offenders: string[] = [];
    for (const [file, text] of Object.entries(sources)) {
      if (/\.test\.tsx$/.test(file)) continue;
      text.split("\n").forEach((line, index) => {
        for (const m of line.matchAll(/(?<![\w:-])bg-accent-[abc]\/(\d+)/g)) {
          if (Number(m[1]) > 10 && m[1] !== "60") offenders.push(`${file}:${index + 1}  ${m[0]}`);
        }
      });
    }
    expect(offenders).toEqual([]);
  });

  it("never sets text in an accent colour (accents are tested as 3:1 marks, not as 4.5:1 text)", () => {
    const offenders: string[] = [];
    for (const [file, text] of Object.entries(sources)) {
      if (/\.test\.tsx$/.test(file)) continue;
      text.split("\n").forEach((line, index) => {
        // on an icon (sized with h-N w-N) the colour is a mark, which only needs 3:1; on words 4.5:1
        if (/(?<![\w:-])text-accent-[abc]/.test(line) && !/\bh-\d+ w-\d+/.test(line)) offenders.push(`${file}:${index + 1}`);
      });
    }
    expect(offenders).toEqual([]);
  });
});
