import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { STORAGE_KEY } from "../settings/settings";
import { SettingsProvider } from "../settings/SettingsProvider";
import { THEMES } from "../settings/themes";
import { Settings } from "./Settings";

function setup() {
  return render(
    <SettingsProvider>
      <MemoryRouter>
        <Settings />
      </MemoryRouter>
    </SettingsProvider>,
  );
}

const root = () => document.documentElement;

beforeEach(() => {
  window.localStorage.clear();
  root().removeAttribute("data-theme");
});

describe("the Settings page", () => {
  it("offers every theme, plus following the system, as one radio group", () => {
    setup();
    const group = screen.getByRole("radiogroup", { name: "Theme" });
    expect(within(group).getAllByRole("radio")).toHaveLength(THEMES.length + 1);
    expect(within(group).getByRole("radio", { name: /Aurora/ })).toHaveAttribute("aria-checked", "true");
  });

  it("applies a theme at once, marks it selected and saves it", () => {
    setup();
    fireEvent.click(screen.getByRole("radio", { name: /Gruvbox/ }));
    expect(root().getAttribute("data-theme")).toBe("gruvbox");
    expect(screen.getByRole("radio", { name: /Gruvbox/ })).toHaveAttribute("aria-checked", "true");
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}").theme).toBe("gruvbox");
    expect(screen.getByText("saved in this browser")).toBeInTheDocument();
  });

  it("changes the text size, typeface and spacing on the document", () => {
    setup();
    fireEvent.click(screen.getByRole("radio", { name: "130%" }));
    expect(root().getAttribute("data-font-scale")).toBe("1.3");
    fireEvent.click(screen.getByRole("radio", { name: "JetBrains Mono" }));
    expect(root().getAttribute("data-font")).toBe("mono");
    fireEvent.click(screen.getByRole("radio", { name: "Loose" }));
    expect(root().getAttribute("data-spacing")).toBe("loose");
  });

  it("switches the accessibility options", () => {
    setup();
    fireEvent.click(screen.getByRole("radio", { name: "High" }));
    expect(root().getAttribute("data-contrast")).toBe("high");
    expect(root().getAttribute("data-theme")).toBe("high-contrast");
    fireEvent.click(screen.getByRole("switch", { name: "Underline every link" }));
    expect(root().getAttribute("data-links")).toBe("underline");
    fireEvent.click(screen.getByRole("radio", { name: "Large (44 px)" }));
    expect(root().getAttribute("data-targets")).toBe("large");
    fireEvent.click(screen.getByRole("radio", { name: "Strong" }));
    expect(root().getAttribute("data-focus")).toBe("strong");
    fireEvent.click(screen.getByRole("radio", { name: "Reduced" }));
    expect(root().getAttribute("data-motion")).toBe("reduced");
  });

  it("changes the layout options", () => {
    setup();
    fireEvent.click(screen.getByRole("radio", { name: "Sharp" }));
    expect(root().getAttribute("data-radius")).toBe("sharp");
    fireEvent.click(screen.getByRole("radio", { name: "Compact" }));
    expect(root().getAttribute("data-density")).toBe("compact");
    fireEvent.click(screen.getByRole("radio", { name: "Right" }));
    expect(root().getAttribute("data-sidebar")).toBe("right");
  });

  it("controls the 3D options", () => {
    setup();
    fireEvent.click(screen.getByRole("radio", { name: "Off (2D)" }));
    expect(root().getAttribute("data-depth")).toBe("off");
    fireEvent.click(screen.getByRole("switch", { name: "Auto-rotate" }));
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}").autoRotate).toBe(false);
  });

  it("exports, imports and resets, and rejects bad input with a reason", () => {
    setup();
    fireEvent.click(screen.getByRole("radio", { name: /Nord/ }));
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    const box = screen.getByRole("textbox", { name: "Settings as JSON" }) as HTMLTextAreaElement;
    expect(JSON.parse(box.value).settings.theme).toBe("nord");
    fireEvent.click(screen.getByRole("button", { name: "Reset everything" }));
    expect(root().getAttribute("data-theme")).toBe("aurora");
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(root().getAttribute("data-theme")).toBe("nord");
    expect(screen.getByRole("status")).toHaveTextContent("Imported");
    fireEvent.change(box, { target: { value: "not json" } });
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(screen.getByRole("status")).toHaveTextContent("not valid JSON");
    expect(root().getAttribute("data-theme")).toBe("nord"); // a bad import changes nothing
  });
});
