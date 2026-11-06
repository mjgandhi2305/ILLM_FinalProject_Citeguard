import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VERDICTS, VERDICT_ORDER } from "../lib/verdicts";
import { VerdictBadge } from "./ui";

describe("VerdictBadge", () => {
  it("renders a human label with an explanatory title", () => {
    render(<VerdictBadge verdict="FABRICATED" />);
    const badge = screen.getByText("Likely fabricated");
    expect(badge.getAttribute("title")).toBe(VERDICTS.FABRICATED.description);
  });

  it("orders verdicts from most to least severe", () => {
    expect(VERDICT_ORDER[0]).toBe("FABRICATED");
    expect(VERDICT_ORDER.at(-1)).toBe("VERIFIED");
  });
});
