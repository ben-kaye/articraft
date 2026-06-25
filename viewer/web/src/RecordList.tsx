import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listRecords, thumbUrl } from './api'

// Relative time, plain JS — no date lib needed.
function timeAgo(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return 'just now'
  const units: [number, string][] = [
    [86400 * 365, 'y'],
    [86400 * 30, 'mo'],
    [86400, 'd'],
    [3600, 'h'],
    [60, 'm'],
  ]
  for (const [secs, label] of units) {
    if (s >= secs) return `${Math.floor(s / secs)}${label} ago`
  }
  return 'just now'
}

export function RecordList({
  selected,
  onSelect,
}: {
  selected: string | null
  onSelect: (id: string) => void
}) {
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 250)
    return () => clearTimeout(t)
  }, [q])

  const { data = [] } = useQuery({
    queryKey: ['records', debounced],
    queryFn: () => listRecords(debounced),
    refetchInterval: 2000,
  })

  // Arrow up/down moves selection through the visible list.
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
    e.preventDefault()
    if (data.length === 0) return
    const i = data.findIndex((r) => r.record_id === selected)
    const next = e.key === 'ArrowDown' ? Math.min(i + 1, data.length - 1) : Math.max(i - 1, 0)
    onSelect(data[i === -1 ? 0 : next].record_id)
  }

  return (
    <nav className="list" tabIndex={0} onKeyDown={onKeyDown}>
      <input
        className="search"
        placeholder="search prompts…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <ul>
        {data.map((r) => (
          <li
            key={r.record_id}
            className={r.record_id === selected ? 'active' : ''}
            onClick={() => onSelect(r.record_id)}
          >
            {/* Hide on 404 — records compiled before thumbnails won't have one. */}
            <img className="thumb" src={thumbUrl(r.record_id)} onError={(e) => (e.currentTarget.style.display = 'none')} />
            <div className="row-main">
              <span className="title">{r.title}</span>
              <span className="sub">
                <span className="sub-left">
                  <span
                    className={`dot ${r.compile_ok ? 'ok' : 'fail'}${r.status === 'running' ? ' running' : ''}`}
                  />
                  {r.model.split('/').pop()}
                </span>
                <span className="meta-right">
                  {r.rating != null && <span className="rating">★ {r.rating}</span>}
                  <span>{timeAgo(r.created_at)}</span>
                </span>
              </span>
            </div>
          </li>
        ))}
        {data.length === 0 && <li className="empty">no records</li>}
      </ul>
    </nav>
  )
}
