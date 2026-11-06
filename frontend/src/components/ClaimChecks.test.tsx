import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ClaimCheck } from "../api/types";
import { safeUrl } from "../lib/url";
import { ClaimChecks } from "./ClaimChecks";

const check = (over: Partial<ClaimCheck>): ClaimCheck => ({
  claim: "Transformers cure protein misfolding [1].",
  label: "NOT_SUPPORTED",
  rationale: "The abstract is about machine translation.",
  quote: "Experiments on two machine translation tasks",
  abstract_source: "openalex",
  abstract_url: "https://openalex.org/W1",
  mode: "llm",
  ...over,
});

afterEach(cleanup);

describe("ClaimChecks", () => {
  it("shows the label, the claim and the abstract quote with its source", () => {
    render(<ClaimChecks checks={[check({})]} />);
    expect(screen.getByText("Not supported")).toBeTruthy();
    expect(screen.getByText(/Transformers cure protein misfolding/)).toBeTruthy();
    expect(screen.getByText(/Experiments on two machine translation tasks/)).toBeTruthy();
    expect(screen.getByRole("link", { name: /OpenAlex/ }).getAttribute("href")).toBe("https://openalex.org/W1");
    expect(screen.getByText(/a hint, not a verdict/)).toBeTruthy();
  });

  it("never links a non-http URL", () => {
    render(<ClaimChecks checks={[check({ abstract_url: "javascript:alert(1)" })]} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(safeUrl("javascript:alert(1)")).toBeUndefined();
    expect(safeUrl("HTTPS://doi.org/10.1/x")).toBe("HTTPS://doi.org/10.1/x");
  });

  it("renders nothing without checks", () => {
    const { container } = render(<ClaimChecks checks={[]} />);
    expect(container.textContent).toBe("");
  });
});
