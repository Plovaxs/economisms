import { useState } from "react";
import type { ReactNode } from "react";

import { Field, Segmented, Switch } from "../components/controls";
import { GlassCard } from "../components/GlassCard";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import {
  CONTRASTS,
  DENSITIES,
  DEPTHS,
  FOCUS_RINGS,
  FONT_FAMILIES,
  FONT_SCALES,
  GAPS,
  GLASSES,
  LABELS_3D,
  LINE_SPACINGS,
  MOTIONS,
  RADII,
  SIDEBARS,
  TARGET_SIZES,
  exportSettings,
  importSettings,
} from "../settings/settings";
import type { Settings as SettingsShape } from "../settings/settings";
import { THEMES, type ThemeDef, systemTheme, themeById } from "../settings/themes";
import { hex } from "../settings/contrast";
import { useSettings } from "../settings/useSettings";

const label = (word: string) => word.charAt(0).toUpperCase() + word.slice(1);
const options = <T extends string>(values: readonly T[], names: Partial<Record<T, string>> = {}) =>
  values.map((value) => ({ value, label: names[value] ?? label(value) }));

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <GlassCard className="p-6">
      <h2 className="text-base font-semibold text-slate-50">{title}</h2>
      {description && <p className="mt-1 text-sm text-slate-400">{description}</p>}
      <div className="mt-5 flex flex-col gap-5">{children}</div>
    </GlassCard>
  );
}

function ThemeCard({ theme, selected, onSelect }: { theme: ThemeDef; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={`flex flex-col gap-2 rounded-xl border p-3 text-left transition-colors ${
        selected ? "border-accent-a bg-accent-a/15" : "border-white/10 bg-white/5 hover:bg-white/10"
      }`}
    >
      <span
        aria-hidden="true"
        className="flex h-10 overflow-hidden rounded-lg border border-white/15"
        data-swatch={theme.id}
      >
        {[theme.bg, theme.surface, ...theme.accents, theme.good, theme.bad].map((c, i) => (
          <SwatchCell key={i} colour={hex(c)} />
        ))}
      </span>
      <span className="text-sm font-medium text-slate-100">{theme.name}</span>
      <span className="text-xs text-slate-400">{theme.scheme === "dark" ? "Dark" : "Light"}</span>
    </button>
  );
}

// A coloured cell. The colour is applied through the CSSOM (an inline-style attribute would be
// refused by the gateway's CSP), so it is set from a ref callback.
function SwatchCell({ colour }: { colour: string }) {
  return (
    <span
      className="h-full flex-1"
      ref={(el) => {
        if (el) el.style.backgroundColor = colour;
      }}
    />
  );
}

export function Settings() {
  const { settings, resolved, environment, persisted, update, replace, reset } = useSettings();
  const [text, setText] = useState("");
  const [message, setMessage] = useState<{ tone: "good" | "bad"; text: string } | null>(null);
  const set = <K extends keyof SettingsShape>(key: K) => (value: SettingsShape[K]) => update({ [key]: value } as Partial<SettingsShape>);
  const systemName = themeById(systemTheme(environment.prefersDark)).name;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Settings"
        description="Make the interface fit how you see, move and work. Every change applies at once and is kept in this browser."
      />

      <div className="flex flex-wrap items-center gap-3 text-sm text-slate-300">
        <StatusBadge label={persisted ? "saved in this browser" : "not saved (storage unavailable)"} tone={persisted ? "good" : "pending"} />
        <span>
          Active theme: <strong className="text-slate-50">{resolved.theme.name}</strong>
          {settings.theme === "system" ? ` (following your system: ${systemName})` : ""}
        </span>
      </div>

      <Section title="Theme" description="Palettes in the spirit of the omarchy and Hyprland rices. Every one is checked in the tests to WCAG contrast.">
        <div role="radiogroup" aria-label="Theme" className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
          <button
            type="button"
            role="radio"
            aria-checked={settings.theme === "system"}
            onClick={() => update({ theme: "system" })}
            className={`flex flex-col justify-center gap-1 rounded-xl border p-3 text-left ${
              settings.theme === "system" ? "border-accent-a bg-accent-a/15" : "border-white/10 bg-white/5 hover:bg-white/10"
            }`}
          >
            <span className="text-sm font-medium text-slate-100">Follow the system</span>
            <span className="text-xs text-slate-400">Now: {systemName}</span>
          </button>
          {THEMES.map((t) => (
            <ThemeCard key={t.id} theme={t} selected={settings.theme === t.id} onSelect={() => update({ theme: t.id })} />
          ))}
        </div>
      </Section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Text" description="Size, typeface and spacing. Text can be enlarged to 150% without breaking the layout.">
          <Field>
            <Segmented
              label="Text size"
              value={settings.fontScale}
              options={FONT_SCALES.map((v) => ({ value: v, label: `${Math.round(v * 100)}%` }))}
              onChange={set("fontScale")}
            />
            <Segmented
              label="Typeface"
              value={settings.fontFamily}
              options={options(FONT_FAMILIES, { inter: "Inter", mono: "JetBrains Mono", system: "System" })}
              onChange={set("fontFamily")}
            />
            <Segmented label="Line spacing" value={settings.lineSpacing} options={options(LINE_SPACINGS)} onChange={set("lineSpacing")} />
          </Field>
        </Section>

        <Section title="Motion and effects" description="Reduce or remove movement and transparency.">
          <Field>
            <Segmented
              label="Motion"
              value={settings.motion}
              options={options(MOTIONS, { system: "Follow system", full: "Full", reduced: "Reduced" })}
              onChange={set("motion")}
            />
            <Segmented
              label="Panels"
              value={settings.glass}
              options={options(GLASSES, { system: "Follow system", full: "Glass", reduced: "Less blur", solid: "Solid" })}
              onChange={set("glass")}
            />
            <Switch label="Ambient glow" description="The soft coloured light behind the panels." checked={settings.ambient} onChange={set("ambient")} />
            <Switch label="Cards lean toward the pointer" description="A small 3-D tilt. Off when motion is reduced." checked={settings.cardTilt} onChange={set("cardTilt")} />
          </Field>
        </Section>

        <Section title="Accessibility" description="Contrast, colour, focus and target size.">
          <Field>
            <Segmented
              label="Contrast"
              value={settings.contrast}
              options={options(CONTRASTS, { system: "Follow system", standard: "Standard", high: "High" })}
              onChange={set("contrast")}
            />
            <Switch label="Colour-blind-safe chart colours" description="The Okabe and Ito palette, tuned to the theme." checked={settings.cvdSafeCharts} onChange={set("cvdSafeCharts")} />
            <Switch label="Underline every link" checked={settings.underlineLinks} onChange={set("underlineLinks")} />
            <Segmented label="Focus ring" value={settings.focusRing} options={options(FOCUS_RINGS)} onChange={set("focusRing")} />
            <Segmented label="Click targets" value={settings.targetSize} options={options(TARGET_SIZES, { standard: "Standard", large: "Large (44 px)" })} onChange={set("targetSize")} />
          </Field>
        </Section>

        <Section title="Layout" description="Corners, spacing and where things sit.">
          <Field>
            <Segmented label="Corners" value={settings.radius} options={options(RADII)} onChange={set("radius")} />
            <Segmented label="Gaps between panels" value={settings.gaps} options={options(GAPS)} onChange={set("gaps")} />
            <Segmented label="Density" value={settings.density} options={options(DENSITIES)} onChange={set("density")} />
            <Segmented label="Sidebar" value={settings.sidebar} options={options(SIDEBARS)} onChange={set("sidebar")} />
            <Switch label="Status bar" description="The bar with workspaces, theme and the palette." checked={settings.topBar} onChange={set("topBar")} />
            <Switch label="Clock" checked={settings.clock} onChange={set("clock")} />
          </Field>
        </Section>
      </div>

      <Section title="3D model web" description="The Atlas can draw the model zoo in three dimensions. Turn it down or off on a slow machine.">
        <div className="grid gap-5 md:grid-cols-3">
          <Segmented label="Quality" value={settings.depth} options={options(DEPTHS, { auto: "Automatic", low: "Low", off: "Off (2D)" })} onChange={set("depth")} />
          <Segmented label="Labels" value={settings.labels3d} options={options(LABELS_3D, { selected: "Selected", all: "All", none: "None" })} onChange={set("labels3d")} />
          <Switch label="Auto-rotate" description="Never while motion is reduced." checked={settings.autoRotate} onChange={set("autoRotate")} />
        </div>
      </Section>

      <Section title="Back up, share or reset" description="Settings are one small JSON object. Nothing leaves your browser.">
        <label className="flex flex-col gap-2 text-sm text-slate-200">
          Settings as JSON
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={6}
            spellCheck={false}
            className="rounded-xl border border-white/15 bg-white/5 p-3 font-mono text-xs text-slate-100"
          />
        </label>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => {
              setText(exportSettings(settings));
              setMessage({ tone: "good", text: "Exported the current settings into the box." });
            }}
            className="rounded-lg border border-white/15 px-3 py-1.5 text-sm text-slate-100 hover:bg-white/10"
          >
            Export
          </button>
          <button
            type="button"
            onClick={() => {
              const result = importSettings(text);
              if (result.ok) {
                replace(result.settings);
                setMessage({ tone: "good", text: "Imported. Anything not recognised was ignored." });
              } else {
                setMessage({ tone: "bad", text: result.error });
              }
            }}
            className="rounded-lg border border-white/15 px-3 py-1.5 text-sm text-slate-100 hover:bg-white/10"
          >
            Import
          </button>
          <button
            type="button"
            onClick={() => {
              reset();
              setMessage({ tone: "good", text: "Every setting is back to its default." });
            }}
            className="rounded-lg border border-bad/40 px-3 py-1.5 text-sm text-bad hover:bg-bad/10"
          >
            Reset everything
          </button>
        </div>
        {message && (
          <p role="status" className={message.tone === "good" ? "text-sm text-good" : "text-sm text-bad"}>
            {message.text}
          </p>
        )}
      </Section>
    </div>
  );
}
