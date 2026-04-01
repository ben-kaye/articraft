import { type JSX, type ComponentPropsWithoutRef } from "react";
import Markdown from "react-markdown";
import { LightAsync as SyntaxHighlighter } from "react-syntax-highlighter";
import json from "react-syntax-highlighter/dist/esm/languages/hljs/json";
import python from "react-syntax-highlighter/dist/esm/languages/hljs/python";
import { atomOneLight } from "react-syntax-highlighter/dist/esm/styles/hljs";
import remarkGfm from "remark-gfm";

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

type FindExamplesResultMatch = {
  title: string;
  description: string;
  tags: string[];
  path: string;
  content: string;
};

function parseFindExamplesResult(raw: string): FindExamplesResultMatch[] | null {
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const result = Array.isArray(parsed.result) ? parsed.result : null;
    if (!result) return null;

    const matches = result
      .map((item) => asRecord(item))
      .filter((item): item is Record<string, unknown> => item !== null)
      .map((item) => {
        const title = typeof item.title === "string" ? item.title : null;
        const description = typeof item.description === "string" ? item.description : null;
        const path = typeof item.path === "string" ? item.path : null;
        const content = typeof item.content === "string" ? item.content : null;
        const tags = Array.isArray(item.tags)
          ? item.tags.filter((tag): tag is string => typeof tag === "string")
          : [];
        if (!title || !description || !path || !content) return null;
        return { title, description, path, content, tags };
      })
      .filter((item): item is FindExamplesResultMatch => item !== null);

    return matches.length > 0 ? matches : null;
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

/** Strip YAML frontmatter (---...---) from markdown content. */
function stripFrontmatter(md: string): string {
  const match = /^---\n[\s\S]*?\n---\n?/.exec(md);
  return match ? md.slice(match[0].length) : md;
}

/** Render markdown content with syntax-highlighted code blocks. */
function MarkdownBlock({
  text,
  maxHeight = "max-h-80",
}: {
  text: string;
  maxHeight?: string;
}): JSX.Element {
  const stripped = stripFrontmatter(text);
  return (
    <div
      className={`${maxHeight} min-w-0 overflow-auto rounded-md bg-[var(--surface-2)] px-3 py-2 text-[11px] leading-relaxed text-[var(--text-secondary)]`}
    >
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }: ComponentPropsWithoutRef<"h1">) => (
            <h3 className="mb-1.5 mt-2 text-[12px] font-semibold text-[var(--text-primary)] first:mt-0">
              {children}
            </h3>
          ),
          h2: ({ children }: ComponentPropsWithoutRef<"h2">) => (
            <h4 className="mb-1 mt-2 text-[11px] font-semibold text-[var(--text-primary)]">
              {children}
            </h4>
          ),
          h3: ({ children }: ComponentPropsWithoutRef<"h3">) => (
            <h5 className="mb-1 mt-1.5 text-[11px] font-medium text-[var(--text-primary)]">
              {children}
            </h5>
          ),
          p: ({ children }: ComponentPropsWithoutRef<"p">) => (
            <p className="my-1.5">{children}</p>
          ),
          ul: ({ children }: ComponentPropsWithoutRef<"ul">) => (
            <ul className="my-1.5 list-disc space-y-0.5 pl-4">{children}</ul>
          ),
          ol: ({ children }: ComponentPropsWithoutRef<"ol">) => (
            <ol className="my-1.5 list-decimal space-y-0.5 pl-4">{children}</ol>
          ),
          li: ({ children }: ComponentPropsWithoutRef<"li">) => (
            <li className="text-[11px]">{children}</li>
          ),
          code: ({
            className,
            children,
            ...rest
          }: ComponentPropsWithoutRef<"code"> & { inline?: boolean }) => {
            const langMatch = /language-(\w+)/.exec(className || "");
            const codeStr = String(children).replace(/\n$/, "");
            if (langMatch) {
              return (
                <div className="my-2 overflow-auto rounded bg-[var(--surface-1)]">
                  <SyntaxHighlighter
                    language={langMatch[1]}
                    style={codeTheme}
                    wrapLongLines
                    customStyle={{
                      margin: 0,
                      padding: "8px 12px",
                      background: "transparent",
                      fontFamily: "var(--font-mono)",
                      fontSize: "10px",
                      lineHeight: "1.6",
                    }}
                    codeTagProps={{ style: { fontFamily: "var(--font-mono)" } }}
                  >
                    {codeStr}
                  </SyntaxHighlighter>
                </div>
              );
            }
            return (
              <code
                className="rounded bg-[var(--surface-1)] px-1 py-0.5 font-mono text-[10px]"
                {...rest}
              >
                {children}
              </code>
            );
          },
          pre: ({ children }: ComponentPropsWithoutRef<"pre">) => <>{children}</>,
        }}
      >
        {stripped}
      </Markdown>
    </div>
  );
}

/** Parse probe_model tool call arguments to extract the code snippet. */
function parseProbeModelCode(raw: string): string | null {
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return typeof parsed.code === "string" ? parsed.code : null;
  } catch {
    return null;
  }
}

/** Parse probe_model tool result into structured fields. */
function parseProbeModelResult(
  raw: string,
): { ok: boolean; elapsedMs: number; result: unknown } | null {
  try {
    const outer = JSON.parse(raw) as Record<string, unknown>;
    const inner = asRecord(outer.result);
    if (!inner) return null;
    const ok = typeof inner.ok === "boolean" ? inner.ok : true;
    const elapsedMs = typeof inner.elapsed_ms === "number" ? inner.elapsed_ms : 0;
    return { ok, elapsedMs, result: inner.result ?? inner.error ?? null };
  } catch {
    return null;
  }
}

/** Parse read_code JSON result, return the code string. */
function parseReadCodeResult(raw: string): string | null {
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return typeof parsed.result === "string" ? parsed.result : null;
  } catch {
    return null;
  }
}

/** Parse edit_code tool call arguments to extract old_string / new_string / replace_all. */
function parseEditCodeArgs(
  raw: string,
): { old_string: string; new_string: string; replace_all?: boolean } | null {
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const old_string = typeof parsed.old_string === "string" ? parsed.old_string : null;
    const new_string = typeof parsed.new_string === "string" ? parsed.new_string : null;
    if (old_string == null || new_string == null) return null;
    const replace_all =
      typeof parsed.replace_all === "boolean" ? parsed.replace_all : undefined;
    return { old_string, new_string, replace_all };
  } catch {
    return null;
  }
}

/** Parse edit_code tool result into message + compilation info. */
function parseEditCodeResult(
  raw: string,
): { message: string; status: "success" | "error" | "unknown"; error: string | null } | null {
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const message = typeof parsed.result === "string" ? parsed.result : null;
    if (!message) return null;
    const compilation = asRecord(parsed.compilation);
    const status =
      compilation?.status === "success" || compilation?.status === "error"
        ? compilation.status
        : "unknown";
    const error = typeof compilation?.error === "string" ? compilation.error : null;
    return { message, status, error };
  } catch {
    return null;
  }
}

/** Parse write_code tool call arguments to extract the code. */
function parseWriteCodeArgs(raw: string): string | null {
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return typeof parsed.code === "string" ? parsed.code : null;
  } catch {
    return null;
  }
}

/** Diff-style view for edit_code old_string → new_string. */
function EditCodeDiffBlock({
  old_string,
  new_string,
  replace_all,
}: {
  old_string: string;
  new_string: string;
  replace_all?: boolean;
}): JSX.Element {
  const oldLines = old_string.split("\n");
  const newLines = new_string.split("\n");
  return (
    <div className="max-h-80 min-w-0 overflow-auto rounded-md bg-[var(--surface-2)]">
      {replace_all ? (
        <div className="px-3 pt-1.5">
          <Badge variant="secondary">replace all</Badge>
        </div>
      ) : null}
      <pre className="py-1.5 font-mono text-[10px] leading-relaxed">
        {oldLines.map((line, i) => (
          <div
            key={`old-${i}`}
            className="whitespace-pre-wrap break-words px-3 text-[#cf222e] bg-[#ffebe9]"
          >
            {`-${line}`}
          </div>
        ))}
        {newLines.map((line, i) => (
          <div
            key={`new-${i}`}
            className="whitespace-pre-wrap break-words px-3 text-[#1a7f37] bg-[#dafbe1]"
          >
            {`+${line}`}
          </div>
        ))}
      </pre>
    </div>
  );
}

function ToolCallBlock({ call }: { call: EnrichedToolCall }): JSX.Element {
  const name = toolCallName(call);
  const rawArgs = toolCallArguments(call);
  const isPatch = name === "apply_patch" || (rawArgs != null && isPatchText(rawArgs));

  // probe_model: show the code snippet with Python highlighting
  if (name === "probe_model" && rawArgs) {
    const probeCode = parseProbeModelCode(rawArgs);
    return (
      <div className="min-w-0 space-y-1.5">
        <p className="text-[11px] text-[var(--text-primary)]">
          <code className="rounded bg-[var(--surface-2)] px-1 py-0.5 font-mono text-[10px]">
            {name}
          </code>
        </p>
        {probeCode ? (
          <CodeBlock code={probeCode} language="python" />
        ) : (
          <PlainBlock text={rawArgs} />
        )}
      </div>
    );
  }

  // edit_code: show old/new as a diff view
  if (name === "edit_code" && rawArgs) {
    const editArgs = parseEditCodeArgs(rawArgs);
    if (editArgs) {
      return (
        <div className="min-w-0 space-y-1.5">
          <p className="text-[11px] text-[var(--text-primary)]">
            <code className="rounded bg-[var(--surface-2)] px-1 py-0.5 font-mono text-[10px]">
              {name}
            </code>
          </p>
          <EditCodeDiffBlock
            old_string={editArgs.old_string}
            new_string={editArgs.new_string}
            replace_all={editArgs.replace_all}
          />
        </div>
      );
    }
  }

  // write_code: show code with Python highlighting
  if (name === "write_code" && rawArgs) {
    const writeCode = parseWriteCodeArgs(rawArgs);
    if (writeCode) {
      return (
        <div className="min-w-0 space-y-1.5">
          <p className="text-[11px] text-[var(--text-primary)]">
            <code className="rounded bg-[var(--surface-2)] px-1 py-0.5 font-mono text-[10px]">
              {name}
            </code>
          </p>
          <CodeBlock code={writeCode} language="python" maxHeight="max-h-80" />
        </div>
      );
    }
  }

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

  if (event.name === "find_examples" && raw) {
    const matches = parseFindExamplesResult(raw);
    if (matches) {
      return (
        <div className="min-w-0 space-y-2">
          <p className="text-[11px] text-[var(--text-tertiary)]">
            <code className="rounded bg-[var(--surface-2)] px-1 py-0.5 font-mono text-[10px] text-[var(--text-secondary)]">
              {event.name}
            </code>{" "}
            result
          </p>
          <div className="space-y-2">
            {matches.map((match) => (
              <div
                key={match.path}
                className="space-y-2 rounded-md border border-[var(--border)] bg-[var(--surface-1)] p-3"
              >
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-[11px] font-medium text-[var(--text-primary)]">
                      {match.title}
                    </p>
                    <Badge variant="secondary">{match.path}</Badge>
                  </div>
                  <p className="text-[11px] leading-relaxed text-[var(--text-secondary)]">
                    {match.description}
                  </p>
                  {match.tags.length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                      {match.tags.map((tag) => (
                        <Badge key={`${match.path}-${tag}`} variant="secondary">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                </div>
                <MarkdownBlock text={match.content} maxHeight="max-h-80" />
              </div>
            ))}
          </div>
        </div>
      );
    }
  }

  // probe_model results: show status badge + formatted result JSON
  if (event.name === "probe_model" && raw) {
    const parsed = parseProbeModelResult(raw);
    if (parsed) {
      const resultJson = JSON.stringify(parsed.result, null, 2);
      return (
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[11px] text-[var(--text-tertiary)]">
              <code className="rounded bg-[var(--surface-2)] px-1 py-0.5 font-mono text-[10px] text-[var(--text-secondary)]">
                {event.name}
              </code>{" "}
              result
            </p>
            <Badge variant={parsed.ok ? "success" : "destructive"}>
              {parsed.ok ? "ok" : "error"}
            </Badge>
            <span className="font-mono text-[10px] text-[var(--text-quaternary)]">
              {parsed.elapsedMs.toFixed(0)}ms
            </span>
          </div>
          <CodeBlock code={resultJson} maxHeight="max-h-80" />
        </div>
      );
    }
  }

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

  // read_code results: extract code and highlight as Python
  if (event.name === "read_code" && raw) {
    const parsed = parseReadCodeResult(raw);
    if (parsed) {
      return (
        <div className="min-w-0 space-y-1.5">
          <p className="text-[11px] text-[var(--text-tertiary)]">
            <code className="rounded bg-[var(--surface-2)] px-1 py-0.5 font-mono text-[10px] text-[var(--text-secondary)]">
              {event.name}
            </code>{" "}
            result
          </p>
          <CodeBlock code={parsed} language="python" maxHeight="max-h-80" />
        </div>
      );
    }
  }

  // edit_code results: show compilation status badge + error
  if ((event.name === "edit_code" || event.name === "write_code") && raw) {
    const parsed = parseEditCodeResult(raw);
    if (parsed) {
      const statusVariant =
        parsed.status === "success"
          ? "success"
          : parsed.status === "error"
            ? "destructive"
            : "secondary";
      return (
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[11px] text-[var(--text-tertiary)]">
              <code className="rounded bg-[var(--surface-2)] px-1 py-0.5 font-mono text-[10px] text-[var(--text-secondary)]">
                {event.name}
              </code>{" "}
              result
            </p>
            {parsed.status !== "unknown" ? (
              <Badge variant={statusVariant}>
                {parsed.status === "success" ? "compiled" : "compile error"}
              </Badge>
            ) : null}
          </div>
          <p className="text-[11px] text-[var(--text-secondary)]">{parsed.message}</p>
          {parsed.error ? <PlainBlock text={parsed.error} maxHeight="max-h-48" /> : null}
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
