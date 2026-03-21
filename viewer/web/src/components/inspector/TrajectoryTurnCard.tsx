import { type JSX } from "react";
import { LightAsync as SyntaxHighlighter } from "react-syntax-highlighter";
import json from "react-syntax-highlighter/dist/esm/languages/hljs/json";
import python from "react-syntax-highlighter/dist/esm/languages/hljs/python";
import { atomOneLight } from "react-syntax-highlighter/dist/esm/styles/hljs";

import { Badge } from "@/components/ui/badge";
import {
  type EnrichedTraceTurn,
  type EnrichedTraceMessage,
  type EnrichedToolCall,
  asRecord,
  asNumber,
  formatUsd,
  formatCount,
  fullMessageText,
} from "./trajectory-types";

SyntaxHighlighter.registerLanguage("json", json);
SyntaxHighlighter.registerLanguage("python", python);

const codeTheme = {
  ...atomOneLight,
  hljs: {
    ...atomOneLight.hljs,
    background: "transparent",
    color: "#1f2937",
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function toolCallName(call: EnrichedToolCall): string {
  if (call.function?.name) return call.function.name;
  if (call.custom?.name) return call.custom.name;
  return "unknown";
}

function toolCallArguments(call: EnrichedToolCall): string | null {
  if (call.function?.arguments) return call.function.arguments;
  if (call.custom?.input) return call.custom.input;
  return null;
}

function formatRelativeTime(ts: number | null | undefined, baseTs: number | null): string {
  if (ts == null || baseTs == null) return "";
  const delta = ts - baseTs;
  if (delta < 0) return "";
  if (delta < 60) return `+${delta.toFixed(1)}s`;
  const minutes = Math.floor(delta / 60);
  const seconds = delta % 60;
  return `+${minutes}m ${seconds.toFixed(0)}s`;
}

function tryPrettyJson(raw: string): string | null {
  try {
    const parsed = JSON.parse(raw);
    return JSON.stringify(parsed, null, 2);
  } catch {
    return null;
  }
}

function isPatchText(text: string): boolean {
  const trimmed = text.trimStart();
  return trimmed.startsWith("*** Begin Patch") || trimmed.startsWith("*** Update File");
}

/** Parse read_file JSON result, strip L-prefixed line numbers, return code + start line. */
function parseReadFileResult(raw: string): { code: string; startLine: number } | null {
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const result = typeof parsed.result === "string" ? parsed.result : null;
    if (!result) return null;

    const lines = result.split("\n");
    const linePattern = /^L(\d+):\s?/;
    const firstMatch = linePattern.exec(lines[0]);
    if (!firstMatch) return null;

    const startLine = parseInt(firstMatch[1], 10);
    const code = lines
      .map((line) => {
        const m = linePattern.exec(line);
        return m ? line.slice(m[0].length) : line;
      })
      .join("\n");

    return { code, startLine };
  } catch {
    return null;
  }
}

/** Render inline markdown: **bold**, *italic*, `code` */
function renderInlineMarkdown(text: string): JSX.Element {
  const parts: (string | JSX.Element)[] = [];
  const pattern = /(\*\*(.+?)\*\*|\*(.+?)\*|`([^`]+)`)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    if (match[2]) {
      parts.push(
        <strong key={key++} className="font-semibold text-[var(--text-primary)]">
          {match[2]}
        </strong>,
      );
    } else if (match[3]) {
      parts.push(<em key={key++}>{match[3]}</em>);
    } else if (match[4]) {
      parts.push(
        <code
          key={key++}
          className="rounded bg-[var(--surface-2)] px-1 py-0.5 font-mono text-[10px]"
        >
          {match[4]}
        </code>,
      );
    }
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return <>{parts}</>;
}

// ---------------------------------------------------------------------------
// Sub-renderers
// ---------------------------------------------------------------------------

function ThoughtBlock({ text }: { text: string }): JSX.Element {
  // Normalize: ensure multi-word **Header** patterns get their own paragraph.
  // Only matches bold text with ≥2 words (contains a space) to avoid breaking
  // inline bold like **barrel**.
  const normalized = text.replace(/([^\n])(\s+)(\*\*[^*\n]+ [^*\n]+\*\*)/g, "$1\n\n$3");
  const paragraphs = normalized.split(/\n\n+/).filter((p) => p.trim());

  return (
    <div className="border-l-2 border-[var(--accent)] pl-3">
      <p className="mb-1.5 text-[10px] font-medium text-[var(--accent)]">Reasoning</p>
      <div className="space-y-2 text-[11px] leading-relaxed text-[var(--text-secondary)]">
        {paragraphs.map((para, i) => {
          const trimmed = para.trim();
          if (!trimmed) return null;

          // Paragraph starting with **heading**: extract as styled header
          const headingMatch = /^\*\*(.+?)\*\*(.*)$/s.exec(trimmed);
          if (headingMatch) {
            const heading = headingMatch[1];
            const body = headingMatch[2].trim();
            return (
              <div key={i}>
                <p className="font-semibold text-[var(--text-primary)]">{heading}</p>
                {body ? <p className="mt-0.5">{renderInlineMarkdown(body)}</p> : null}
              </div>
            );
          }

          return <p key={i}>{renderInlineMarkdown(trimmed)}</p>;
        })}
      </div>
    </div>
  );
}

function PatchBlock({ text }: { text: string }): JSX.Element {
  const lines = text.split("\n");
  return (
    <div className="max-h-80 min-w-0 overflow-auto rounded-md bg-[var(--surface-2)]">
      <pre className="py-1.5 font-mono text-[10px] leading-relaxed">
        {lines.map((line, i) => {
          let cls = "text-[var(--text-secondary)]";
          if (line.startsWith("+")) cls = "text-[#1a7f37] bg-[#dafbe1]";
          else if (line.startsWith("-")) cls = "text-[#cf222e] bg-[#ffebe9]";
          else if (line.startsWith("@@")) cls = "text-[#656d76] italic";
          else if (line.startsWith("***")) cls = "text-[#656d76] font-medium";
          return (
            <div key={i} className={`whitespace-pre-wrap break-words px-3 ${cls}`}>
              {line || "\u00a0"}
            </div>
          );
        })}
      </pre>
    </div>
  );
}

function CodeBlock({
  code,
  language = "json",
  maxHeight = "max-h-64",
  startingLineNumber,
}: {
  code: string;
  language?: string;
  maxHeight?: string;
  startingLineNumber?: number;
}): JSX.Element {
  const showLines = startingLineNumber != null;
  return (
    <div className={`${maxHeight} min-w-0 overflow-auto rounded-md bg-[var(--surface-2)]`}>
      <SyntaxHighlighter
        language={language}
        style={codeTheme}
        wrapLongLines
        showLineNumbers={showLines}
        startingLineNumber={startingLineNumber}
        lineNumberStyle={
          showLines
            ? {
                minWidth: "2.5rem",
                paddingRight: "0.75rem",
                textAlign: "right" as const,
                color: "var(--text-quaternary)",
                userSelect: "none" as const,
              }
            : undefined
        }
        customStyle={{
          margin: 0,
          padding: "8px 12px",
          background: "transparent",
          fontFamily: "var(--font-mono)",
          fontSize: "10px",
          lineHeight: "1.6",
        }}
        codeTagProps={{
          style: { fontFamily: "var(--font-mono)" },
        }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}

function PlainBlock({
  text,
  maxHeight = "max-h-64",
}: {
  text: string;
  maxHeight?: string;
}): JSX.Element {
  return (
    <pre
      className={`${maxHeight} min-w-0 overflow-auto whitespace-pre-wrap break-words rounded-md bg-[var(--surface-2)] px-3 py-2 font-mono text-[10px] leading-relaxed text-[var(--text-secondary)]`}
    >
      {text}
    </pre>
  );
}

function ToolCallBlock({ call }: { call: EnrichedToolCall }): JSX.Element {
  const name = toolCallName(call);
  const rawArgs = toolCallArguments(call);
  const isPatch = name === "apply_patch" || (rawArgs != null && isPatchText(rawArgs));
  const prettyArgs = !isPatch && rawArgs ? tryPrettyJson(rawArgs) : null;

  return (
    <div className="min-w-0 space-y-1.5">
      <p className="text-[11px] text-[var(--text-primary)]">
        <code className="rounded bg-[var(--surface-2)] px-1 py-0.5 font-mono text-[10px]">
          {name}
        </code>
      </p>
      {isPatch && rawArgs ? (
        <PatchBlock text={rawArgs} />
      ) : rawArgs ? (
        prettyArgs ? (
          <CodeBlock code={prettyArgs} />
        ) : (
          <PlainBlock text={rawArgs} />
        )
      ) : null}
    </div>
  );
}

function AssistantEvent({ event }: { event: EnrichedTraceMessage }): JSX.Element {
  const contentText = fullMessageText(event.content);
  return (
    <div className="min-w-0 space-y-2">
      {event.thought_summary ? <ThoughtBlock text={event.thought_summary} /> : null}
      {contentText ? (
        <p className="min-w-0 whitespace-pre-wrap break-words text-[11px] leading-relaxed text-[var(--text-secondary)]">
          {contentText}
        </p>
      ) : null}
      {event.tool_calls?.map((call, i) => (
        <ToolCallBlock key={call.id ?? i} call={call} />
      ))}
    </div>
  );
}

function ToolEvent({ event }: { event: EnrichedTraceMessage }): JSX.Element {
  const raw = fullMessageText(event.content);

  // read_file results: extract code and highlight as Python
  if (event.name === "read_file" && raw) {
    const parsed = parseReadFileResult(raw);
    if (parsed) {
      return (
        <div className="min-w-0 space-y-1.5">
          <p className="text-[11px] text-[var(--text-tertiary)]">
            <code className="rounded bg-[var(--surface-2)] px-1 py-0.5 font-mono text-[10px] text-[var(--text-secondary)]">
              {event.name}
            </code>{" "}
            result
          </p>
          <CodeBlock
            code={parsed.code}
            language="python"
            maxHeight="max-h-80"
            startingLineNumber={parsed.startLine}
          />
        </div>
      );
    }
  }

  const prettyJson = raw ? tryPrettyJson(raw) : null;

  return (
    <div className="min-w-0 space-y-1.5">
      <p className="text-[11px] text-[var(--text-tertiary)]">
        <code className="rounded bg-[var(--surface-2)] px-1 py-0.5 font-mono text-[10px] text-[var(--text-secondary)]">
          {event.name ?? "tool"}
        </code>{" "}
        result
      </p>
      {raw ? (
        prettyJson ? (
          <CodeBlock code={prettyJson} maxHeight="max-h-80" />
        ) : (
          <PlainBlock text={raw} maxHeight="max-h-80" />
        )
      ) : null}
    </div>
  );
}

function UserEvent({ event }: { event: EnrichedTraceMessage }): JSX.Element {
  const text = fullMessageText(event.content);
  return (
    <div className="min-w-0">
      <p className="mb-1 text-[10px] font-medium text-[var(--text-tertiary)]">Feedback</p>
      {text ? <PlainBlock text={text} /> : null}
    </div>
  );
}

function EventRow({ event }: { event: EnrichedTraceMessage }): JSX.Element {
  if (event.role === "assistant") return <AssistantEvent event={event} />;
  if (event.role === "tool") return <ToolEvent event={event} />;
  return <UserEvent event={event} />;
}

// ---------------------------------------------------------------------------
// Main card
// ---------------------------------------------------------------------------

type TrajectoryTurnCardProps = {
  turn: EnrichedTraceTurn;
  baseTimestamp: number | null;
};

export function TrajectoryTurnCard({ turn, baseTimestamp }: TrajectoryTurnCardProps): JSX.Element {
  const turnTokens = asRecord(turn.cost?.tokens);
  const turnCosts = asRecord(turn.cost?.costs_usd);
  const relTime = formatRelativeTime(turn.timestamp, baseTimestamp);

  const eventUsage = turn.events.reduce(
    (acc, ev) => {
      if (ev.usage?.total_tokens) acc.total += ev.usage.total_tokens;
      return acc;
    },
    { total: 0 },
  );
  const tokenDisplay =
    asNumber(turnTokens?.total_tokens) != null
      ? formatCount(turnTokens?.total_tokens)
      : eventUsage.total > 0
        ? formatCount(eventUsage.total)
        : null;

  return (
    <div className="min-w-0">
      {/* Header row */}
      <div className="flex flex-wrap items-center gap-2 pb-2">
        <span className="font-mono text-[11px] font-medium text-[var(--text-primary)]">
          Turn {turn.index}
        </span>
        <Badge variant="success">{formatUsd(turnCosts?.total)}</Badge>
        {tokenDisplay ? <Badge variant="secondary">{tokenDisplay} tok</Badge> : null}
        {relTime ? (
          <span className="font-mono text-[10px] text-[var(--text-quaternary)]">{relTime}</span>
        ) : null}
      </div>

      {/* Events — flat list */}
      {turn.events.length > 0 ? (
        <div className="min-w-0 space-y-3 pl-3">
          {turn.events.map((event, eventIndex) => (
            <div key={`${turn.index}-${eventIndex}`} className="min-w-0">
              <EventRow event={event} />
            </div>
          ))}
        </div>
      ) : (
        <p className="py-1 text-[10px] text-[var(--text-quaternary)]">
          Trace unavailable for this turn.
        </p>
      )}
    </div>
  );
}
