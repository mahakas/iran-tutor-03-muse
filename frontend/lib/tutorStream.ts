/**
 * Phase 4: recoverable tutor streaming client.
 *
 * - `startTutorStream` POSTs the question and receives a `stream_id`.
 * - `consumeTutorStream` reads `chunk` / `end` SSE events with `fetch` (so the
 *   auth headers are sent, which `EventSource` cannot do). If the connection
 *   drops, it reconnects with `cursor` = chunks already received, so no text
 *   is duplicated or lost.
 * - `stopTutorStream` asks the server to cancel; the stream then ends with
 *   status `stopped`, and nothing from that turn is persisted.
 */

import type { Source, TutorMode } from "@/lib/types";

export type AuthFetch = (input: string, init?: RequestInit) => Promise<Response>;

export type TutorStreamRequest = {
  query: string;
  grade_number?: number | null;
  major_code?: string | null;
  branch_code?: string | null;
  book_id?: number | null;
  grade_numbers?: number[] | null;
  book_ids?: number[] | null;
  mode: TutorMode;
  auto_mode: boolean;
  top_k?: number;
  chat_session_id?: string | null;
  regenerate_of?: string | null;
};

export type TutorStreamFinal = {
  sources?: Source[];
  mode?: TutorMode;
  router?: { mode: TutorMode; confidence: number; reason: string; source: "llm" | "heuristic" };
  retrieved_count?: number;
  scope_count?: number;
  expanded_count?: number;
  memory_used?: boolean;
  blocks?: unknown[];
  usage?: {
    total_tokens: number;
    tokens_remaining: number;
  };
};

export type TutorStreamOutcome = {
  status: "done" | "stopped" | "error";
  text: string;
  final: TutorStreamFinal | null;
};

export type StartResult =
  | { ok: true; streamId: string }
  | { ok: false; status: number; detail: string };

const MAX_RECONNECTS = 3;

function detailOf(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

export async function startTutorStream(
  authFetch: AuthFetch,
  body: TutorStreamRequest
): Promise<StartResult> {
  const response = await authFetch("/api/v1/tutor/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = (await response.json().catch(() => ({}))) as unknown;
  if (!response.ok) {
    return { ok: false, status: response.status, detail: detailOf(payload, "") };
  }
  const streamId = (payload as { stream_id?: unknown }).stream_id;
  if (typeof streamId !== "string") {
    return { ok: false, status: response.status, detail: "" };
  }
  return { ok: true, streamId };
}

export async function stopTutorStream(authFetch: AuthFetch, streamId: string): Promise<boolean> {
  const response = await authFetch(`/api/v1/tutor/stream/${streamId}/stop`, { method: "POST" });
  return response.ok;
}

type ParsedEvent = { event: string; data: string };

/** Split complete SSE events from a buffer; returns the events and the unparsed rest. */
export function parseSseBuffer(buffer: string): { events: ParsedEvent[]; rest: string } {
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";
  const events: ParsedEvent[] = [];
  for (const block of parts) {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) event = line.slice(7).trim();
      else if (line.startsWith("data: ")) dataLines.push(line.slice(6));
    }
    if (dataLines.length) events.push({ event, data: dataLines.join("\n") });
  }
  return { events, rest };
}

export async function consumeTutorStream(
  authFetch: AuthFetch,
  streamId: string,
  onChunk: (text: string) => void
): Promise<TutorStreamOutcome> {
  let received = 0;
  let text = "";
  let attempts = 0;

  while (attempts <= MAX_RECONNECTS) {
    attempts += 1;
    let response: Response;
    try {
      response = await authFetch(`/api/v1/tutor/stream/${streamId}?cursor=${received}`, {
        method: "GET",
        headers: { Accept: "text/event-stream" },
      });
    } catch {
      continue; // network hiccup: reconnect with the same cursor
    }
    if (!response.ok || !response.body) {
      if (response.status === 404) return { status: "error", text, final: null };
      continue;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let ended: TutorStreamOutcome | null = null;
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseSseBuffer(buffer);
        buffer = parsed.rest;
        for (const item of parsed.events) {
          if (item.event === "chunk") {
            const data = JSON.parse(item.data) as { index: number; text: string };
            if (data.index !== received) continue; // duplicate after resume
            received += 1;
            text += data.text;
            onChunk(data.text);
          } else if (item.event === "end") {
            const data = JSON.parse(item.data) as {
              status: "done" | "stopped" | "error";
              final?: TutorStreamFinal | null;
            };
            ended = { status: data.status, text, final: data.final ?? null };
          } else if (item.event === "error") {
            ended = { status: "error", text, final: null };
          }
        }
      }
    } catch {
      // Connection dropped mid-stream: fall through and resume from `received`.
    }
    if (ended) return ended;
  }
  return { status: "error", text, final: null };
}
