import { describe, expect, it } from "vitest";

import { cleanJson, stripPdfArtifacts } from "./text";

describe("PDF hyphenation marks", () => {
  it("rejoins words split by a hyphenation mark", () => {
    expect(stripPdfArtifacts("Hybrid transfer learn￾ing strategy")).toBe("Hybrid transfer learning strategy");
    expect(stripPdfArtifacts("Un￾\nleashing")).toBe("Unleashing");
    expect(stripPdfArtifacts("trans­\r\nduction")).toBe("transduction");
    expect(stripPdfArtifacts("a real-world hyphen stays")).toBe("a real-world hyphen stays");
  });

  it("cleans every string in a parsed response, however deep", () => {
    const raw = JSON.stringify({
      title: "learn￾ing",
      citations: [{ raw: "quan￾tile", n: 3, ok: true, none: null }],
    });
    expect(JSON.parse(raw, cleanJson)).toEqual({
      title: "learning",
      citations: [{ raw: "quantile", n: 3, ok: true, none: null }],
    });
  });
});
