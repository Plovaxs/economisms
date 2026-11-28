// The in-page half of tools/audit_web_pages.py: runs inside the page (WebDriver "execute script")
// and returns what it measured. Plain JavaScript, no dependency.
//
// What it measures, for the page as it is rendered right now:
//   * text contrast, per text node, from the browser's own computed colours: the text colour (with
//     the element's opacity) over the background colours of the element and every ancestor,
//     composited from the page background down. WCAG 2.x: 4.5:1, or 3:1 for large text.
//   * every control (button, link, field, radio, switch...) has an accessible name;
//   * duplicate ids, skipped heading levels, the number of <h1>, the landmark regions.
//
// What it does NOT measure (and says so in `skipped`): text over a gradient or an image (it cannot
// composite those), visually hidden text (`sr-only`), disabled controls, and anything that is not
// on screen at the moment it runs (a closed dialog, another tab, a hover or focus state).
const out = { contrast: [], names: [], ids: [], headings: [], landmarks: {}, h1: 0, checked: 0, skipped: 0 };

const parse = (css) => {
  const m = css.match(/rgba?\(([^)]+)\)/);
  if (!m) return null;
  const p = m[1].split(",").map(parseFloat);
  return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
};
const over = (top, bottom) => {
  const a = top.a + bottom.a * (1 - top.a);
  if (a === 0) return { r: 0, g: 0, b: 0, a: 0 };
  const mixc = (t, b) => (t * top.a + b * bottom.a * (1 - top.a)) / a;
  return { r: mixc(top.r, bottom.r), g: mixc(top.g, bottom.g), b: mixc(top.b, bottom.b), a };
};
const linear = (c) => {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
};
const luminance = (c) => 0.2126 * linear(c.r) + 0.7152 * linear(c.g) + 0.0722 * linear(c.b);
const ratio = (a, b) => {
  const x = luminance(a);
  const y = luminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
};

// The page background is the theme's --c-base (the stylesheet paints it on <body>).
const rootStyle = getComputedStyle(document.documentElement);
const baseTriplet = rootStyle.getPropertyValue("--c-base").trim().split(/\s+/).join(",");
const pageBackground = parse(baseTriplet ? `rgb(${baseTriplet})` : "rgb(0,0,0)") || { r: 0, g: 0, b: 0, a: 1 };

function backgroundOf(el) {
  const chain = [];
  for (let e = el; e; e = e.parentElement) chain.push(e);
  let base = pageBackground;
  let gradient = false;
  for (let i = chain.length - 1; i >= 0; i--) {
    const style = getComputedStyle(chain[i]);
    const bg = parse(style.backgroundColor);
    const isRoot = chain[i].tagName === "BODY" || chain[i].tagName === "HTML";
    if (style.backgroundImage && style.backgroundImage !== "none" && !isRoot) gradient = true;
    if (bg && bg.a > 0) base = over(bg, base);
  }
  return { color: base, gradient };
}

const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
const seen = new Set();
while (walker.nextNode()) {
  const node = walker.currentNode;
  const text = node.textContent.trim();
  const el = node.parentElement;
  if (!text || !el || seen.has(el)) continue;
  seen.add(el);
  const style = getComputedStyle(el);
  const box = el.getBoundingClientRect();
  if (style.visibility === "hidden" || style.display === "none" || parseFloat(style.opacity) === 0) continue;
  if (box.width === 0 || box.height === 0) continue;
  if (el.closest("[disabled],[aria-hidden=true],script,style")) continue;
  if (String(el.className).split(" ").includes("sr-only")) continue;
  if (style.webkitTextFillColor === "rgba(0, 0, 0, 0)" || style.color === "rgba(0, 0, 0, 0)") {
    out.skipped++; // gradient-clipped text
    continue;
  }
  const fg = parse(style.color);
  if (!fg) continue;
  const { color: bg, gradient } = backgroundOf(el);
  if (gradient) {
    out.skipped++;
    continue;
  }
  const ink = over({ ...fg, a: fg.a * parseFloat(style.opacity) }, bg);
  const size = parseFloat(style.fontSize);
  const bold = parseInt(style.fontWeight, 10) >= 700;
  const large = size >= 24 || (size >= 18.66 && bold);
  const need = large ? 3 : 4.5;
  const got = ratio(ink, bg);
  out.checked++;
  if (got < need) {
    out.contrast.push({ text: text.slice(0, 40), ratio: Math.round(got * 100) / 100, need, tag: el.tagName, cls: String(el.className).slice(0, 60) });
  }
}

const controls = "button,a[href],[role=button],[role=radio],[role=switch],[role=option],input,select,textarea";
for (const el of document.querySelectorAll(controls)) {
  const box = el.getBoundingClientRect();
  if (box.width === 0 && box.height === 0) continue;
  const labelledby = el.getAttribute("aria-labelledby");
  const name = (
    el.getAttribute("aria-label") ||
    (labelledby && document.getElementById(labelledby)?.textContent) ||
    el.textContent ||
    el.getAttribute("title") ||
    el.getAttribute("placeholder") ||
    ""
  ).trim();
  const isField = ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName);
  const labelled = isField && (el.closest("label") || (el.id && document.querySelector(`label[for="${el.id}"]`)));
  if (!name && !labelled) out.names.push(el.outerHTML.slice(0, 120));
}

const ids = {};
for (const el of document.querySelectorAll("[id]")) ids[el.id] = (ids[el.id] || 0) + 1;
for (const id of Object.keys(ids)) if (ids[id] > 1) out.ids.push(id);

let previous = 0;
for (const h of document.querySelectorAll("h1,h2,h3,h4")) {
  const level = Number(h.tagName[1]);
  if (previous && level > previous + 1) out.headings.push(`${h.textContent.trim().slice(0, 30)} h${level} after h${previous}`);
  previous = level;
}
const regions = { banner: "header", main: "main", navigation: "nav", complementary: "aside" };
for (const [role, tag] of Object.entries(regions)) out.landmarks[role] = document.querySelectorAll(`[role=${role}],${tag}`).length;
out.h1 = document.querySelectorAll("h1").length;
return out;
