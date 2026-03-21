import { useMemo, useState, type JSX } from "react";
import { Maximize2 } from "lucide-react";

import { TrajectoryInspectorModal } from "./TrajectoryInspectorModal";
import {
  asRecord,
  formatUsd,
  formatCount,
} from "./trajectory-types";

type TracePanelProps = {
  cost: Record<string, unknown> | null;
  traceText: string | null;
};

function countTurns(traceText: string | null, cost: Record<string, unknown> | null): number {
  const costTurns = Array.isArray(cost?.turns) ? cost.turns.length : 0;
  if (!traceText) return costTurns;

  let count = 0;
  for (const line of traceText.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const entry = JSON.parse(trimmed) as Record<string, unknown>;
      const message = typeof entry.message === "object" && entry.message !== null
        ? (entry.message as Record<string, unknown>)
        : null;
      if (message?.role === "assistant") count++;
    } catch {
      // skip malformed lines
    }
  }

  return count || costTurns;
}

export function TracePanel({ cost, traceText }: TracePanelProps): JSX.Element | null {
  const total = asRecord(cost?.total);
  const totalTokens = asRecord(total?.tokens);
  const totalCosts = asRecord(total?.costs_usd);
  const turnCount = useMemo(() => countTurns(traceText, cost), [traceText, cost]);
  const modelId = typeof cost?.model_id === "string" ? cost.model_id : null;
  const [inspectorOpen, setInspectorOpen] = useState(false);

  if (!cost && !traceText) return null;

  return (
    <section>
      <div className="flex items-center gap-2 pb-2">
        <span className="text-[10px] font-medium uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
          Agent Trace
        </span>
        <div className="h-px flex-1 bg-[var(--border-subtle)]" />
      </div>

      <div className="space-y-0">
        <div className="prop-row">
          <span className="prop-label">Model</span>
          <span className="prop-value font-mono text-[10px]">{modelId ?? "--"}</span>
        </div>
        <div className="prop-row">
          <span className="prop-label">Total Cost</span>
          <span className="prop-value font-mono">{formatUsd(totalCosts?.total)}</span>
        </div>
        <div className="prop-row">
          <span className="prop-label">Total Tokens</span>
          <span className="prop-value font-mono">{formatCount(totalTokens?.total_tokens)}</span>
        </div>
        <div className="prop-row">
          <span className="prop-label">Turns</span>
          <span className="prop-value font-mono">{turnCount}</span>
        </div>
      </div>

      <button
        type="button"
        onClick={() => setInspectorOpen(true)}
        className="mt-2.5 inline-flex items-center gap-1 text-[11px] text-[var(--accent)] transition-colors duration-100 hover:text-[var(--text-primary)]"
      >
        <Maximize2 className="size-3" />
        View full trajectory
      </button>

      <TrajectoryInspectorModal
        open={inspectorOpen}
        onOpenChange={setInspectorOpen}
        cost={cost}
        traceText={traceText}
      />
    </section>
  );
}
