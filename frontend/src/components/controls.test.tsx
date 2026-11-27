import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { Segmented, Switch } from "./controls";

function Harness() {
  const [size, setSize] = useState<number>(1);
  const [on, setOn] = useState(false);
  return (
    <div>
      <Segmented
        label="Text size"
        value={size}
        options={[
          { value: 0.85, label: "85%" },
          { value: 1, label: "100%" },
          { value: 1.3, label: "130%" },
        ]}
        onChange={setSize}
      />
      <Switch label="Glow" description="soft light" checked={on} onChange={setOn} />
      <output data-testid="size">{size}</output>
    </div>
  );
}

describe("Segmented", () => {
  it("is a radio group with one tab stop, named by its label", () => {
    render(<Harness />);
    const group = screen.getByRole("radiogroup", { name: "Text size" });
    expect(group).toBeInTheDocument();
    const radios = screen.getAllByRole("radio");
    expect(radios.map((r) => r.getAttribute("aria-checked"))).toEqual(["false", "true", "false"]);
    expect(radios.map((r) => r.tabIndex)).toEqual([-1, 0, -1]);
  });

  it("moves and selects with the arrow keys, wraps, and honours Home and End", () => {
    render(<Harness />);
    const current = screen.getByRole("radio", { name: "100%" });
    current.focus();
    fireEvent.keyDown(current, { key: "ArrowRight" });
    expect(screen.getByTestId("size")).toHaveTextContent("1.3");
    expect(screen.getByRole("radio", { name: "130%" })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("radio", { name: "130%" }), { key: "ArrowRight" });
    expect(screen.getByTestId("size")).toHaveTextContent("0.85"); // wrapped
    fireEvent.keyDown(screen.getByRole("radio", { name: "85%" }), { key: "End" });
    expect(screen.getByTestId("size")).toHaveTextContent("1.3");
    fireEvent.keyDown(screen.getByRole("radio", { name: "130%" }), { key: "Home" });
    expect(screen.getByTestId("size")).toHaveTextContent("0.85");
    fireEvent.keyDown(screen.getByRole("radio", { name: "85%" }), { key: "ArrowLeft" });
    expect(screen.getByTestId("size")).toHaveTextContent("1.3");
  });

  it("selects on click", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("radio", { name: "85%" }));
    expect(screen.getByTestId("size")).toHaveTextContent("0.85");
  });
});

describe("Switch", () => {
  it("is a named switch that toggles and reports its state", () => {
    render(<Harness />);
    const sw = screen.getByRole("switch", { name: "Glow" });
    expect(sw).toHaveAttribute("aria-checked", "false");
    fireEvent.click(sw);
    expect(sw).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("soft light")).toBeInTheDocument();
  });
});
