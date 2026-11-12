import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { clearToken } from "../api/client";
import { TokenGate } from "./TokenGate";

describe("TokenGate", () => {
  beforeEach(() => {
    clearToken();
  });

  it("blocks children and shows the token form when no token is set", () => {
    render(
      <TokenGate>
        <p>protected content</p>
      </TokenGate>,
    );
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Bearer token")).toBeInTheDocument();
  });

  it("renders children once a token is submitted", async () => {
    const user = userEvent.setup();
    render(
      <TokenGate>
        <p>protected content</p>
      </TokenGate>,
    );
    await user.type(screen.getByPlaceholderText("Bearer token"), "a-real-token");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByText("protected content")).toBeInTheDocument();
  });

  it("does not unlock on an empty/whitespace-only token", async () => {
    const user = userEvent.setup();
    render(
      <TokenGate>
        <p>protected content</p>
      </TokenGate>,
    );
    await user.type(screen.getByPlaceholderText("Bearer token"), "   ");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
  });
});
