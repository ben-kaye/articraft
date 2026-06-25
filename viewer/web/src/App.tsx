import { useState } from 'react'
import { RecordList } from './RecordList'
import { Viewer3D } from './Viewer3D'
import { Inspector } from './Inspector'

// Thin draggable bar between panes. During the drag only the bar itself slides
// (cheap); the column width is committed once on release so the 3D viewer
// relayouts a single time, not every pointermove.
function ResizeBar({ onCommit, style }: { onCommit: (dx: number) => void; style: React.CSSProperties }) {
  const [drag, setDrag] = useState(0)
  const start = (e: React.PointerEvent) => {
    e.preventDefault()
    const x0 = e.clientX
    const move = (ev: PointerEvent) => setDrag(ev.clientX - x0)
    const up = (ev: PointerEvent) => {
      removeEventListener('pointermove', move)
      removeEventListener('pointerup', up)
      setDrag(0)
      onCommit(ev.clientX - x0)
    }
    addEventListener('pointermove', move)
    addEventListener('pointerup', up)
  }
  return (
    <div
      className="resize-bar"
      style={{ ...style, transform: `translateX(${drag}px)` }}
      onPointerDown={start}
    />
  )
}

const clampW = (w: number) => Math.max(180, Math.min(640, w))

export default function App() {
  const params = new URLSearchParams(location.search)

  // Headless thumbnail mode: bare canvas, no chrome (driven by viewer/thumbnail.py).
  const snapRecord = params.get('snapshot') === '1' ? params.get('record') : null
  const [selected, setSelected] = useState<string | null>(() => params.get('record'))
  // Playback: which meta-turn's geometry to show (null = final/live model). Shared by
  // the scrubber (in Viewport) and the Trace tab's per-meta-turn "view" buttons.
  const [viewedMeta, setViewedMeta] = useState<number | null>(null)
  const [listW, setListW] = useState(260)
  const [inspW, setInspW] = useState(320)

  if (snapRecord)
    return (
      <div className="snapshot-root">
        <Viewer3D recordId={snapRecord} snapshot />
      </div>
    )

  const select = (id: string) => {
    setSelected(id)
    setViewedMeta(null) // new record → back to the final model
    const url = new URL(location.href)
    url.searchParams.set('record', id)
    history.replaceState(null, '', url)
  }

  return (
    <div
      className="app"
      style={{ gridTemplateColumns: `${listW}px 1fr ${selected ? inspW : 0}px` }}
    >
      <RecordList selected={selected} onSelect={select} />
      <ResizeBar onCommit={(dx) => setListW((w) => clampW(w + dx))} style={{ left: listW }} />
      {selected ? (
        <>
          {/* No key={selected}: keep OrbitControls mounted across records so the
              view angle survives a switch; Bounds.fit reframes each new model. */}
          <Viewer3D recordId={selected} viewedMeta={viewedMeta} setViewedMeta={setViewedMeta} />
          <ResizeBar onCommit={(dx) => setInspW((w) => clampW(w - dx))} style={{ right: inspW }} />
          <Inspector recordId={selected} viewedMeta={viewedMeta} setViewedMeta={setViewedMeta} />
        </>
      ) : (
        <div className="viewport empty">select a record</div>
      )}
    </div>
  )
}
