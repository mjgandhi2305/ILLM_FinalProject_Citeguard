import { describe, expect, it } from "vitest";

import { parseSseChunk } from "./sse";

describe("parseSseChunk", () => {
  it("parses complete events and keeps the partial tail", () => {
    const { messages, rest } = parseSseChunk(
      'event: snapshot\ndata: {"a":1}\n\n: ping\n\nevent: citation.verified\ndata: {"b"',
    );
    expect(messages).toEqual([{ event: "snapshot", data: '{"a":1}' }]);
    expect(rest).toBe('event: citation.verified\ndata: {"b"');
  });

  it("handles CRLF, multi-line data and default event names", () => {
    const { messages } = parseSseChunk("data: line1\r\ndata: line2\r\n\r\n");
    expect(messages).toEqual([{ event: "message", data: "line1\nline2" }]);
  });
});
