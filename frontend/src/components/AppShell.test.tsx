import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { DEFAULT_SETTINGS } from "../settings/settings";
import { SettingsProvider } from "../settings/SettingsProvider";
import type { Settings } from "../settings/settings";
import { AppShell } from "./AppShell";

function Where() {
  return <output data-testid="where">{useLocation().pathname}</output>;
}

function setup(initial: Partial<Settings> = {}, path = "/") {
  return render(
    <SettingsProvider initial={{ ...DEFAULT_SETTINGS, ...initial }}>
      <MemoryRouter initialEntries={[path]}>
        <AppShell>
          <Routes>
            <Route path="*" element={<Where />} />
          </Routes>
        </AppShell>
      </MemoryRouter>
    </SettingsProvider>,
  );
}

beforeEach(() => {
  document.title = "";
});

describe("AppShell structure and accessibility", () => {
  it("has a skip link, landmarks and a named main region", () => {
    setup();
    expect(screen.getByRole("link", { name: "Skip to the content" })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("main", { name: "Overview" })).toHaveAttribute("id", "main");
    expect(screen.getByRole("navigation", { name: "Workspaces" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Sections" })).toBeInTheDocument();
    expect(document.title).toBe("Overview · ECONOSIM");
  });

  it("marks the current workspace and names the keys", () => {
    setup({}, "/lab/qmacro");
    const labs = screen.getByRole("link", { name: "Labs (Alt 3)" });
    expect(labs).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Overview (Alt 1)" })).not.toHaveAttribute("aria-current");
    expect(document.title).toBe("Q-MACRO lab · ECONOSIM");
  });

  it("says the research-only gate on every page", () => {
    setup();
    expect(screen.getByText(/research only · NO-GO/)).toBeInTheDocument();
  });
});

describe("AppShell settings-driven layout", () => {
  it("hides the sidebar or the status bar when asked", () => {
    const hidden = setup({ sidebar: "hidden", topBar: false });
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(screen.queryByRole("banner")).toBeNull();
    hidden.unmount();
    setup({ sidebar: "right" });
    expect(screen.getByRole("complementary").parentElement?.className).toContain("flex-row-reverse");
  });

  it("shows the clock only when enabled", () => {
    const on = setup({ clock: true });
    expect(screen.getByLabelText("Local time")).toBeInTheDocument();
    on.unmount();
    setup({ clock: false });
    expect(screen.queryByLabelText("Local time")).toBeNull();
  });
});

describe("AppShell keyboard", () => {
  it("opens the palette with Ctrl K and a slash, and the shortcuts with a question mark", () => {
    setup();
    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.keyDown(document.body, { key: "/" });
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.keyDown(document.body, { key: "?" });
    expect(screen.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument();
  });

  it("does not steal slash or question mark while typing", () => {
    setup();
    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "?" });
    expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).toBeNull();
  });

  it("switches workspace with Alt and a digit", () => {
    setup();
    fireEvent.keyDown(document, { key: "3", altKey: true });
    expect(screen.getByTestId("where")).toHaveTextContent("/lab/qmacro");
    fireEvent.keyDown(document, { key: "4", altKey: true });
    expect(screen.getByTestId("where")).toHaveTextContent("/atlas");
    fireEvent.keyDown(document, { key: "5", altKey: true });
    expect(screen.getByTestId("where")).toHaveTextContent("/settings");
  });

  it("runs a palette command to navigate, then lands on the page", () => {
    setup();
    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "market paths" } });
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });
    expect(screen.getByTestId("where")).toHaveTextContent("/market-paths");
    expect(document.title).toBe("Market paths · ECONOSIM");
  });
});
