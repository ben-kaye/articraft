import { useEffect, useRef } from 'react'
import type { MetaTurn } from './api'

// Step/scrub/play over meta-turns (the spans between model.py edits). Binds entirely to
// the shared viewedMeta state; null = the final/live model. ponytail: setInterval play,
// no easing or scrub-preview — it's a dev inspect tool.
export function Playback({
  metas,
  viewedMeta,
  setViewedMeta,
}: {
  metas: MetaTurn[]
  viewedMeta: number | null
  setViewedMeta: (m: number | null) => void
}) {
  const last = metas.length - 1
  const at = viewedMeta ?? last
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  const stop = () => {
    if (timer.current) clearInterval(timer.current)
    timer.current = null
  }
  // Clean up the interval if the component unmounts mid-play.
  useEffect(() => stop, [])

  const go = (m: number) => {
    stop()
    setViewedMeta(Math.max(0, Math.min(last, m)))
  }

  const play = () => {
    stop()
    // Resume from the start if we're parked at the end (or on the live model).
    let i = viewedMeta == null || viewedMeta >= last ? 0 : viewedMeta
    setViewedMeta(i)
    timer.current = setInterval(() => {
      i += 1
      if (i > last) {
        stop()
        return
      }
      setViewedMeta(i)
    }, 1000)
  }

  const playing = timer.current != null
  const m = metas[at]
  const label = m
    ? m.edit_turn != null
      ? `→ edit t${m.edit_turn}${m.passed ? ' ✓' : ''}`
      : 'tail'
    : ''

  return (
    <div className="playback">
      <button onClick={() => go(at - 1)} disabled={at <= 0} title="previous meta-turn">
        ◀
      </button>
      <button onClick={playing ? stop : play} title={playing ? 'pause' : 'play'}>
        {playing ? '❚❚' : '▶'}
      </button>
      <button onClick={() => go(at + 1)} disabled={at >= last} title="next meta-turn">
        ▶
      </button>
      <input
        type="range"
        min={0}
        max={last}
        step={1}
        value={at}
        onChange={(e) => go(e.target.valueAsNumber)}
      />
      <span className="pb-label">
        {at}/{last} · {label}
      </span>
      <button className="pb-live" onClick={() => { stop(); setViewedMeta(null) }} disabled={viewedMeta == null}>
        live
      </button>
    </div>
  )
}
