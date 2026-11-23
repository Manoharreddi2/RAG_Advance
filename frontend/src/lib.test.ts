import { describe, expect, it, vi } from "vitest";
import { streamChat, type ChatEvent } from "./api";
import { fix, highlight, ms, pages, pct } from "./util";

describe("formatting", () => {
  it("formats pages, percents and durations", () => {
    expect(pages(3, 3)).toBe("p. 3");
    expect(pages(2, 4)).toBe("pp. 2–4");
    expect(pages(null, null)).toBe("");
    expect(pct(0.1234)).toBe("12.3%");
    expect(fix(null)).toBe("–");
    expect(ms(250)).toBe("250 ms");
    expect(ms(2500)).toBe("2.50 s");
  });
  it("highlights query terms but not stopwords", () => {
    const parts = highlight("The hotel cap is 320 USD", "what is the hotel cap") as unknown[];
    const marked = parts.filter((p) => typeof p === "object").length;
    expect(marked).toBe(2);
  });
});

describe("streamChat SSE parser", () => {
  it("parses CRLF-delimited events split across network chunks", async () => {
    const wire = 'event: sources\r\ndata: {"type":"sources","chunks":[],"timings_ms":{}}\r\n\r\n' +
      'event: token\r\ndata: {"type":"token","text":"Hel"}\r\n\r\nevent: token\r\ndata: {"type":"token","text":"lo"}\r\n\r\n' +
      'event: done\r\ndata: {"type":"done","answer":"Hello"}\r\n\r\n';
    const bytes = new TextEncoder().encode(wire);
    const pieces = [bytes.slice(0, 17), bytes.slice(17, 90), bytes.slice(90)];
    const body = new ReadableStream({ start(c) { pieces.forEach((p) => c.enqueue(p)); c.close(); } });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200 })));
    const events: ChatEvent[] = [];
    await streamChat({ message: "hi" }, (e) => events.push(e));
    expect(events.map((e) => e.type)).toEqual(["sources", "token", "token", "done"]);
    expect(events.filter((e) => e.type === "token").map((e: any) => e.text).join("")).toBe("Hello");
  });
});
