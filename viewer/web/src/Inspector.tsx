import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { marked } from 'marked'
import { getRecord, stopRun, setRating, clearRating, type TraceTurn } from './api'

const getRater = () => {
  let r = localStorage.getItem('rater')
  if (!r) {
    r = window.prompt('Your rater name?')?.trim() || ''
    if (r) localStorage.setItem('rater', r)
  }
  return r
}

function Rating({ recordId, ratings, avg, n }: { recordId: string; ratings: Record<string, number>; avg: number | null; n: number }) {
  const qc = useQueryClient()
  const mine = ratings[localStorage.getItem('rater') || ''] ?? 0
  return (
    <span className="rating-input">
      {[1, 2, 3, 4, 5].map((star) => (
        <button
          key={star}
          className={`star ${star <= mine ? 'filled' : ''}`}
          onClick={async () => {
            const rater = getRater()
            if (!rater) return
            await setRating(recordId, rater, star)
            qc.invalidateQueries({ queryKey: ['record', recordId] })
            qc.invalidateQueries({ queryKey: ['records'] })
          }}
        >
          ★
        </button>
      ))}
      {mine > 0 && (
        <button
          className="star clear"
          title="clear your rating"
          onClick={async () => {
            await clearRating(recordId, localStorage.getItem('rater') || '')
            qc.invalidateQueries({ queryKey: ['record', recordId] })
            qc.invalidateQueries({ queryKey: ['records'] })
          }}
        >
          ✕
        </button>
      )}
      {n > 0 && <span className="rating-avg"> {avg} avg · {n} rater{n > 1 ? 's' : ''}</span>}
    </span>
  )
}

// Render a unified diff with +/- line coloring. ~10 lines, no diff lib.
function Diff({ patch }: { patch: string }) {
  const body = patch.split('\n').filter((l) => !/^(diff |index |--- |\+\+\+ )/.test(l))
  return (
    <pre className="diff">
      {body.map((l, i) => {
        const cls = l.startsWith('+') ? 'add' : l.startsWith('-') ? 'del' : l.startsWith('@@') ? 'hunk' : ''
        return (
          <div key={i} className={cls}>
            {l || ' '}
          </div>
        )
      })}
    </pre>
  )
}

function fmtDuration(start: string, end: string): string {
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (!(ms > 0)) return '—'
  const s = ms / 1000
  return s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`
}

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      className="copy"
      onClick={() => {
        navigator.clipboard.writeText(text)
        setDone(true)
        setTimeout(() => setDone(false), 1000)
      }}
    >
      {done ? 'copied' : 'copy'}
    </button>
  )
}

function StopButton({ recordId }: { recordId: string }) {
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  return (
    <button
      className="stop"
      disabled={busy}
      onClick={async () => {
        setBusy(true)
        await stopRun(recordId).catch(() => {})
        qc.invalidateQueries({ queryKey: ['record', recordId] })
        qc.invalidateQueries({ queryKey: ['records'] })
        setBusy(false)
      }}
    >
      {busy ? 'stopping…' : 'stop run'}
    </button>
  )
}

export function Inspector({
  recordId,
  viewedMeta = null,
  setViewedMeta = () => {},
}: {
  recordId: string
  viewedMeta?: number | null
  setViewedMeta?: (m: number | null) => void
}) {
  const [tab, setTab] = useState<'meta' | 'code' | 'trace'>('meta')
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set())
  const [fullscreen, setFullscreen] = useState(false)
  const { data, isLoading } = useQuery({
    queryKey: ['record', recordId],
    queryFn: () => getRecord(recordId),
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 1500 : false),
  })

  if (isLoading || !data)
    return (
      <aside className="inspector skeleton">
        <div className="sk-bar" />
        <div className="sk-line" />
        <div className="sk-line short" />
        <div className="sk-line" />
      </aside>
    )

  const byTurn = new Map(data.trace.map((t) => [t.turn, t]))

  // One raw LLM turn: thinking text, model.py diff, and its tool calls.
  const renderTurn = (t: TraceTurn) => {
    const open = !collapsed.has(t.turn)
    return (
      <div key={t.turn} className="trace-turn">
        <h4
          className="turn-head"
          onClick={() =>
            setCollapsed((c) => {
              const n = new Set(c)
              n.has(t.turn) ? n.delete(t.turn) : n.add(t.turn)
              return n
            })
          }
        >
          <span>{open ? '▾' : '▸'}</span> turn {t.turn} · {t.input_tokens}in/
          {t.output_tokens}out · {t.cache_read_tokens}cached · ${t.cost_usd.toFixed(4)}
        </h4>
        {open && (
          <>
            {t.reasoning && (
              <details className="reasoning">
                <summary>💭 thinking</summary>
                {/* ponytail: trusting local trace text, not sanitizing — local dev tool. */}
                <div
                  className="thought"
                  dangerouslySetInnerHTML={{ __html: marked.parse(t.reasoning) as string }}
                />
              </details>
            )}
            {t.text && (
              // ponytail: trusting local trace text, not sanitizing — local dev tool.
              <div
                className="thought"
                dangerouslySetInnerHTML={{ __html: marked.parse(t.text) as string }}
              />
            )}
            {data.diffs[`turn ${t.turn}`] && <Diff patch={data.diffs[`turn ${t.turn}`]} />}
            {t.tool_calls.map((tc, i) => (
              <details key={i} className="tool-call">
                <summary>
                  {tc.name}
                  {tc.args.path ? `: ${String(tc.args.path)}` : ''}
                </summary>
                {Object.keys(tc.args).length > 0 && (
                  <>
                    <div className="tools">args</div>
                    <pre className="code">{JSON.stringify(tc.args, null, 2)}</pre>
                  </>
                )}
                <div className="tools">result</div>
                <CopyButton text={tc.result} />
                <pre className="code">{tc.result}</pre>
              </details>
            ))}
          </>
        )}
      </div>
    )
  }

  return (
    <aside className={fullscreen ? 'inspector fullscreen' : 'inspector'}>
      <div className="tabs">
        <button className={tab === 'meta' ? 'active' : ''} onClick={() => setTab('meta')}>
          Metadata
        </button>
        <button className={tab === 'code' ? 'active' : ''} onClick={() => setTab('code')}>
          Code
        </button>
        <button className={tab === 'trace' ? 'active' : ''} onClick={() => setTab('trace')}>
          Trace
        </button>
        <button className="expand" onClick={() => setFullscreen((f) => !f)} title="full screen">
          {fullscreen ? '✕' : '⛶'}
        </button>
      </div>
      {tab === 'meta' ? (
        <dl className="meta">
          <dt>prompt</dt>
          <dd>{data.prompt}</dd>
          <dt>model</dt>
          <dd>{data.model}</dd>
          <dt>compiled</dt>
          <dd>
            <span className={`dot ${data.compile_ok ? 'ok' : 'fail'}${data.status === 'running' ? ' running' : ''}`} />
            {data.compile_ok ? 'ok' : 'failed'}
            {data.status === 'running' && (
              <>
                {' · running… '}
                <StopButton recordId={recordId} />
              </>
            )}
          </dd>
          <dt>rating</dt>
          <dd>
            <Rating recordId={recordId} ratings={data.ratings} avg={data.rating} n={data.n_ratings} />
          </dd>
          <dt>cost</dt>
          <dd>
            ${data.cost.total_usd.toFixed(4)} ({data.cost.input_tokens}in /{' '}
            {data.cost.output_tokens}out)
          </dd>
          <dt>cache</dt>
          <dd>
            {data.cost.cache_read_tokens} cached
            {data.cost.input_tokens > 0 &&
              ` (${Math.round((100 * data.cost.cache_read_tokens) / data.cost.input_tokens)}%)`}
          </dd>
          <dt>gen time</dt>
          <dd>{fmtDuration(data.created_at, data.updated_at)}</dd>
          <dt>created</dt>
          <dd>{new Date(data.created_at).toLocaleString()}</dd>
        </dl>
      ) : tab === 'code' ? (
        <div className="code-pane">
          <CopyButton text={data.model_py} />
          <pre className="code">{data.model_py}</pre>
        </div>
      ) : (
        <div className="trace">
          <div className="trace-turn">
            <h4>turn 0 · prompt</h4>
            <div
              className="thought"
              dangerouslySetInnerHTML={{ __html: marked.parse(data.prompt) as string }}
            />
          </div>
          {data.trace.length === 0 ? (
            <p>(no trace recorded)</p>
          ) : (
            // Group raw turns under meta-turns (spans between model.py edits). The ⦿ button
            // loads that meta-turn's geometry into the 3D viewer (shared with the scrubber).
            data.meta_turns.map((meta) => {
              const viewed = viewedMeta === meta.index
              return (
                <div key={meta.index} className={`meta-turn ${viewed ? 'viewed' : ''}`}>
                  <div className="meta-head">
                    <button
                      className="meta-view"
                      title="view this meta-turn's geometry"
                      onClick={() => setViewedMeta(viewed ? null : meta.index)}
                    >
                      ⦿
                    </button>
                    meta {meta.index} ·{' '}
                    {meta.edit_turn != null ? `→ edit t${meta.edit_turn}` : 'tail'}
                    {meta.passed ? ' ✓' : ''}
                    {meta.probes.length > 0 &&
                      ` · ${meta.probes.length} probe${meta.probes.length > 1 ? 's' : ''}`}
                  </div>
                  {meta.raw_turns.map((tn) => byTurn.get(tn)).filter(Boolean).map((t) => renderTurn(t as TraceTurn))}
                </div>
              )
            })
          )}
        </div>
      )}
    </aside>
  )
}
