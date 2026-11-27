import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { CommandPalette } from "./CommandPalette";
import type { Command } from "./commands";

function makeCommands(run: (id: string) => void = vi.fn()): Command[] {
  return [
    { id: "a", label: "Go to Pricing diagnostics", group: "Go to", keywords: "greeks", run: () => run("pricing") },
    { id: "b", label: "Go to Portfolio risk", group: "Go to", run: () => run("risk") },
    { id: "c", label: "Theme: Nord", group: "Theme", run: () => run("nord") },
  ];
}

function Harness({ run }: { run: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button onClick={() => setOpen(true)}>open it</button>
      <CommandPalette open={open} onClose={() => setOpen(false)} commands={makeCommands(run)} />
    </div>
  );
}

describe("CommandPalette", () => {
  it("renders nothing while closed, and a labelled modal combobox with options while open", () => {
    render(<Harness run={vi.fn()} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByText("open it"));
    expect(screen.getByRole("dialog", { name: "Command palette" })).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("combobox")).toHaveFocus();
    expect(screen.getAllByRole("option")).toHaveLength(3);
    expect(screen.getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
  });

  it("filters as you type, searches keywords, and says when nothing matches", () => {
    render(<Harness run={vi.fn()} />);
    fireEvent.click(screen.getByText("open it"));
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "greeks" } });
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual([expect.stringContaining("Pricing diagnostics")]);
    fireEvent.change(input, { target: { value: "zzzzz" } });
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(screen.getByText(/Nothing matches/)).toBeInTheDocument();
  });

  it("moves with the arrow keys, announces the active option, and runs it on Enter", () => {
    const run = vi.fn();
    render(<Harness run={run} />);
    fireEvent.click(screen.getByText("open it"));
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    const options = screen.getAllByRole("option");
    expect(options[1]).toHaveAttribute("aria-selected", "true");
    expect(input).toHaveAttribute("aria-activedescendant", options[1].id);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(run).toHaveBeenCalledWith("risk");
    expect(screen.queryByRole("dialog")).toBeNull(); // it closes when it runs something
  });

  it("does not run past the ends of the list and supports Home and End", () => {
    render(<Harness run={vi.fn()} />);
    fireEvent.click(screen.getByText("open it"));
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(screen.getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(input, { key: "End" });
    expect(screen.getAllByRole("option")[2]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(screen.getAllByRole("option")[2]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(input, { key: "Home" });
    expect(screen.getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
  });

  it("runs a command on click, and closes on Escape or a click outside, returning focus", () => {
    const run = vi.fn();
    render(<Harness run={run} />);
    const opener = screen.getByText("open it");
    opener.focus();
    fireEvent.click(opener);
    fireEvent.click(screen.getByText(/Theme: Nord/));
    expect(run).toHaveBeenCalledWith("nord");
    fireEvent.click(opener);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
    fireEvent.click(opener);
    const backdrop = screen.getByRole("dialog").parentElement as HTMLElement;
    fireEvent.mouseDown(backdrop);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("keeps Tab inside the dialog", () => {
    render(<Harness run={vi.fn()} />);
    fireEvent.click(screen.getByText("open it"));
    const input = screen.getByRole("combobox");
    input.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(input).toHaveFocus(); // the only focusable control: focus wraps onto itself
  });
});
