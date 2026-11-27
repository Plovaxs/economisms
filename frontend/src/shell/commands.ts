import graphJson from "../atlas/graph.json";
import type { AtlasGraph } from "../atlas/web";
import { FONT_SCALES } from "../settings/settings";
import type { Settings } from "../settings/settings";
import { THEMES } from "../settings/themes";
import { NAV_ITEMS, WORKSPACES } from "./nav";

// Everything the command palette can do. Pure data plus closures over a small context, so the list
// can be tested without rendering anything.

export interface Command {
  id: string;
  label: string;
  group: "Go to" | "Theme" | "Accessibility" | "Layout" | "3D" | "Model zoo" | "Help";
  keywords?: string;
  hint?: string;
  run: () => void;
}

export interface CommandContext {
  navigate: (to: string) => void;
  settings: Settings;
  update: (patch: Partial<Settings>) => void;
  reset: () => void;
  openShortcuts: () => void;
}

const GRAPH = graphJson as unknown as AtlasGraph;

export function buildCommands(ctx: CommandContext): Command[] {
  const s = ctx.settings;
  const commands: Command[] = [];
  for (const item of NAV_ITEMS) {
    commands.push({
      id: `go:${item.to}`,
      label: `Go to ${item.label}`,
      group: "Go to",
      keywords: `${item.keywords ?? ""} ${item.to}`,
      run: () => ctx.navigate(item.to),
    });
  }
  for (const w of WORKSPACES) {
    commands.push({
      id: `ws:${w.id}`,
      label: `Workspace ${w.key}: ${w.label}`,
      group: "Go to",
      hint: `Alt+${w.key}`,
      run: () => ctx.navigate(w.home),
    });
  }
  commands.push({
    id: "theme:system",
    label: "Theme: follow the operating system",
    group: "Theme",
    keywords: "auto light dark",
    run: () => ctx.update({ theme: "system" }),
  });
  for (const t of THEMES) {
    commands.push({
      id: `theme:${t.id}`,
      label: `Theme: ${t.name}`,
      group: "Theme",
      keywords: `${t.scheme} colour palette`,
      run: () => ctx.update({ theme: t.id }),
    });
  }
  const toggles: [string, string, string, () => void][] = [
    ["a11y:motion", s.motion === "reduced" ? "Allow motion" : "Reduce motion", "animation", () => ctx.update({ motion: s.motion === "reduced" ? "full" : "reduced" })],
    ["a11y:contrast", s.contrast === "high" ? "Standard contrast" : "High contrast", "wcag", () => ctx.update({ contrast: s.contrast === "high" ? "standard" : "high" })],
    ["a11y:cvd", s.cvdSafeCharts ? "Chart colours: theme palette" : "Chart colours: colour-blind safe", "cvd deuteranopia protanopia", () => ctx.update({ cvdSafeCharts: !s.cvdSafeCharts })],
    ["a11y:links", s.underlineLinks ? "Links: no underline" : "Underline all links", "", () => ctx.update({ underlineLinks: !s.underlineLinks })],
    ["a11y:targets", s.targetSize === "large" ? "Standard click targets" : "Large click targets", "touch 44px", () => ctx.update({ targetSize: s.targetSize === "large" ? "standard" : "large" })],
    ["a11y:focus", s.focusRing === "strong" ? "Standard focus ring" : "Strong focus ring", "keyboard outline", () => ctx.update({ focusRing: s.focusRing === "strong" ? "standard" : "strong" })],
    ["a11y:glass", s.glass === "solid" ? "Glass panels: translucent" : "Solid panels (no transparency)", "blur transparency", () => ctx.update({ glass: s.glass === "solid" ? "full" : "solid" })],
  ];
  for (const [id, label, keywords, run] of toggles) {
    commands.push({ id, label, group: "Accessibility", keywords, run });
  }
  const bigger = FONT_SCALES[Math.min(FONT_SCALES.indexOf(s.fontScale) + 1, FONT_SCALES.length - 1)];
  const smaller = FONT_SCALES[Math.max(FONT_SCALES.indexOf(s.fontScale) - 1, 0)];
  commands.push(
    { id: "a11y:bigger", label: "Larger text", group: "Accessibility", hint: `${Math.round(bigger * 100)}%`, keywords: "font size zoom", run: () => ctx.update({ fontScale: bigger }) },
    { id: "a11y:smaller", label: "Smaller text", group: "Accessibility", hint: `${Math.round(smaller * 100)}%`, keywords: "font size", run: () => ctx.update({ fontScale: smaller }) },
    { id: "a11y:size-reset", label: "Reset text size", group: "Accessibility", hint: "100%", run: () => ctx.update({ fontScale: 1 }) },
  );
  commands.push(
    { id: "layout:sidebar-left", label: "Sidebar on the left", group: "Layout", run: () => ctx.update({ sidebar: "left" }) },
    { id: "layout:sidebar-right", label: "Sidebar on the right", group: "Layout", run: () => ctx.update({ sidebar: "right" }) },
    { id: "layout:sidebar-hidden", label: "Hide the sidebar", group: "Layout", keywords: "focus", run: () => ctx.update({ sidebar: "hidden" }) },
    { id: "layout:compact", label: s.density === "compact" ? "Comfortable density" : "Compact density", group: "Layout", run: () => ctx.update({ density: s.density === "compact" ? "comfortable" : "compact" }) },
    { id: "layout:ambient", label: s.ambient ? "Turn the ambient glow off" : "Turn the ambient glow on", group: "Layout", run: () => ctx.update({ ambient: !s.ambient }) },
    { id: "layout:tilt", label: s.cardTilt ? "Cards: stay flat" : "Cards: lean toward the pointer", group: "Layout", keywords: "3d depth", run: () => ctx.update({ cardTilt: !s.cardTilt }) },
  );
  commands.push(
    { id: "3d:off", label: "3D views: off (use the 2D web)", group: "3D", keywords: "depth webgl performance", run: () => ctx.update({ depth: "off" }) },
    { id: "3d:low", label: "3D views: low quality", group: "3D", run: () => ctx.update({ depth: "low" }) },
    { id: "3d:auto", label: "3D views: automatic quality", group: "3D", run: () => ctx.update({ depth: "auto" }) },
    { id: "3d:rotate", label: s.autoRotate ? "3D: stop auto-rotation" : "3D: auto-rotate", group: "3D", run: () => ctx.update({ autoRotate: !s.autoRotate }) },
  );
  for (const node of GRAPH.nodes) {
    if (node.kind !== "model" && node.kind !== "baseline" && node.kind !== "pipeline") continue;
    commands.push({
      id: `model:${node.id}`,
      label: `Atlas: ${node.label}`,
      group: "Model zoo",
      keywords: `${node.family} ${node.kind}`,
      run: () => ctx.navigate(`/atlas?model=${encodeURIComponent(node.id)}`),
    });
  }
  commands.push(
    { id: "help:shortcuts", label: "Show keyboard shortcuts", group: "Help", hint: "?", run: ctx.openShortcuts },
    { id: "help:reset", label: "Reset every setting to the default", group: "Help", run: ctx.reset },
  );
  return commands;
}

export interface Shortcut {
  keys: string;
  does: string;
}

export const SHORTCUTS: readonly Shortcut[] = [
  { keys: "Ctrl K  or  Cmd K", does: "Open the command palette" },
  { keys: "/", does: "Open the command palette" },
  { keys: "?", does: "Show this list" },
  { keys: "Alt 1 .. 5", does: "Switch workspace: Overview, Dashboard, Labs, Model zoo, Settings" },
  { keys: "Alt T", does: "Next theme" },
  { keys: "Alt M", does: "Reduce or allow motion" },
  { keys: "Alt B", does: "Show or hide the sidebar" },
  { keys: "Esc", does: "Close a dialog or the palette" },
  { keys: "Arrow keys (3D web)", does: "Rotate the model web; + and - zoom; 0 resets the view" },
  { keys: "Enter or Space (on a model)", does: "Select it" },
];
