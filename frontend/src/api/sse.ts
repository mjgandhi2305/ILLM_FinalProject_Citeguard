/**
 * Minimal Server-Sent Events reader over fetch. Unlike `EventSource`, it can send the
 * API-key header. Parses the text/event-stream format incrementally.
 */
export interface SseMessage {
  event: string;
  data: string;
}

export function parseSseChunk(buffer: string): { messages: SseMessage[]; rest: string } {
  const messages: SseMessage[] = [];
  const blocks = buffer.replace(/\r\n/g, "\n").split("\n\n");
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue; // comment / keep-alive ping
      const idx = line.indexOf(":");
      const field = idx === -1 ? line : line.slice(0, idx);
      const value = idx === -1 ? "" : line.slice(idx + 1).replace(/^ /, "");
      if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (data.length) messages.push({ event, data: data.join("\n") });
  }
  return { messages, rest };
}

export async function streamEvents(
  url: string,
  headers: Record<string, string>,
  onMessage: (msg: SseMessage) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(url, { headers: { Accept: "text/event-stream", ...headers }, signal });
  if (!res.ok || !res.body) throw new Error(`event stream failed: HTTP ${res.status}`);
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    const { messages, rest } = parseSseChunk(buffer);
    buffer = rest;
    messages.forEach(onMessage);
  }
}
