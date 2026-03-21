// Enriched trajectory types and parser — preserves fields that the sidebar
// `parseTurns` discards (thought_summary, tool-call arguments, timestamps, usage).

export type EnrichedToolCall = {
  id?: string;
  type?: string;
  function?: { name?: string; arguments?: string };
  custom?: { name?: string; input?: string };
};

export type EnrichedTraceMessage = {
  role: string;
  content?: unknown;
  thought_summary?: string;
  tool_calls?: EnrichedToolCall[];
  usage?: {
    prompt_tokens?: number;
    candidates_tokens?: number;
    total_tokens?: number;
    cached_tokens?: number;
  };
  name?: string;
  tool_call_id?: string;
  tool_type?: string;
  timestamp?: number;
};

export type EnrichedTraceTurn = {
  index: number;
  cost: Record<string, unknown> | null;
  events: EnrichedTraceMessage[];
  timestamp: number | null;
};

// ---------------------------------------------------------------------------
// Shared utilities (extracted from TracePanel to avoid duplication)
// ---------------------------------------------------------------------------

export function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function asNumber(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

export function formatUsd(value: unknown): string {
  const number = asNumber(value);
  return number == null ? "--" : `$${number.toFixed(4)}`;
}

export function formatCount(value: unknown): string {
  const number = asNumber(value);
  return number == null ? "--" : number.toLocaleString();
}

export function excerpt(text: string, max = 220): string {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (normalized.length <= max) return normalized;
  return `${normalized.slice(0, max - 1)}...`;
}

export function messageText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((item) => {
        if (typeof item === "string") return item;
        const record = asRecord(item);
        if (!record) return "";
        if (typeof record.text === "string") return record.text;
        return "";
      })
      .filter(Boolean)
      .join("\n");
  }
  if (content == null) return "";
  try {
    return JSON.stringify(content);
  } catch {
    return String(content);
  }
}

export function fullMessageText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    const parts = content
      .map((item) => {
        if (typeof item === "string") return item;
        const record = asRecord(item);
        if (!record) return null;
        if (typeof record.text === "string") return record.text;
        try {
          return JSON.stringify(record, null, 2);
        } catch {
          return String(record);
        }
      })
      .filter((value): value is string => Boolean(value));
    return parts.join("\n\n");
  }
  if (content == null) return "";
  if (typeof content === "object") {
    try {
      return JSON.stringify(content, null, 2);
    } catch {
      return String(content);
    }
  }
  return String(content);
}

// ---------------------------------------------------------------------------
// Enriched parser
// ---------------------------------------------------------------------------

export function parseEnrichedTurns(
  traceText: string | null,
  cost: Record<string, unknown> | null,
): EnrichedTraceTurn[] {
  const costTurns = Array.isArray(cost?.turns) ? cost.turns : [];

  if (!traceText) {
    return costTurns.map((turn, index) => ({
      index: index + 1,
      cost: asRecord(turn),
      events: [],
      timestamp: null,
    }));
  }

  const entries = traceText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      try {
        return JSON.parse(line) as Record<string, unknown>;
      } catch {
        return null;
      }
    })
    .filter((entry): entry is Record<string, unknown> => entry !== null);

  const turns: EnrichedTraceTurn[] = [];

  for (const entry of entries) {
    const message = asRecord(entry.message);
    const role = typeof message?.role === "string" ? message.role : null;
    if (!message || !role) continue;

    const ts = typeof entry.ts === "number" ? entry.ts : null;

    const traceMessage: EnrichedTraceMessage = {
      role,
      content: message.content,
      thought_summary:
        typeof message.thought_summary === "string" ? message.thought_summary : undefined,
      tool_calls: Array.isArray(message.tool_calls)
        ? (message.tool_calls as EnrichedToolCall[])
        : undefined,
      usage: asRecord(message.usage) as EnrichedTraceMessage["usage"] | undefined ?? undefined,
      name: typeof message.name === "string" ? message.name : undefined,
      tool_call_id:
        typeof message.tool_call_id === "string" ? message.tool_call_id : undefined,
      tool_type: typeof message.tool_type === "string" ? message.tool_type : undefined,
      timestamp: ts ?? undefined,
    };

    if (role === "assistant") {
      turns.push({
        index: turns.length + 1,
        cost: asRecord(costTurns[turns.length]),
        events: [traceMessage],
        timestamp: ts,
      });
      continue;
    }

    if (turns.length === 0) continue;
    turns[turns.length - 1].events.push(traceMessage);
  }

  if (turns.length === 0) {
    return costTurns.map((turn, index) => ({
      index: index + 1,
      cost: asRecord(turn),
      events: [],
      timestamp: null,
    }));
  }

  return turns;
}
