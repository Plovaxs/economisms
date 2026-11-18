import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

function Bomb(): never {
  throw new Error("simulated render failure");
}

describe("ErrorBoundary", () => {
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    // React itself logs the caught error to console.error too; silence
    // both that and our own componentDidCatch log so the test output
    // stays clean, without hiding a real assertion failure.
    consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
  });

  it("renders children normally when nothing throws", () => {
    render(
      <ErrorBoundary>
        <p>safe content</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("safe content")).toBeInTheDocument();
  });

  it("catches a render-time throw and shows the fallback instead of crashing", () => {
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByText("This page hit an unexpected error")).toBeInTheDocument();
    expect(screen.getByText("simulated render failure")).toBeInTheDocument();
  });

  it("logs the caught error so it stays visible in devtools/CI output", () => {
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      "ErrorBoundary caught a render error:",
      expect.objectContaining({ message: "simulated render failure" }),
      expect.anything(),
    );
  });

  it("clears the caught error and recovers when resetKey changes", () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="/a">
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByText("This page hit an unexpected error")).toBeInTheDocument();

    rerender(
      <ErrorBoundary resetKey="/b">
        <p>back to safety</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("back to safety")).toBeInTheDocument();
  });

  it("clears the caught error when 'Try again' is clicked", async () => {
    const user = userEvent.setup();
    let shouldThrow = true;
    function MaybeBomb() {
      if (shouldThrow) {
        throw new Error("simulated render failure");
      }
      return <p>recovered</p>;
    }

    render(
      <ErrorBoundary>
        <MaybeBomb />
      </ErrorBoundary>,
    );
    expect(screen.getByText("This page hit an unexpected error")).toBeInTheDocument();

    shouldThrow = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByText("recovered")).toBeInTheDocument();
  });
});
