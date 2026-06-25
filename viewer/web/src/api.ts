export type Summary = {
  record_id: string
  title: string
  prompt: string
  rating: number | null
  n_ratings: number
  model: string
  compile_ok: boolean
  has_urdf: boolean
  status: string
  created_at: string
}

export type ToolCall = {
  name: string
  args: Record<string, unknown>
  result: string
  compile?: { ok: boolean; passed: boolean }
}

export type TraceTurn = {
  turn: number
  text: string
  reasoning?: string
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cost_usd: number
  tool_calls: ToolCall[]
}

// One playback step: the span between two model.py edits. Repeated probes against the
// same geometry collapse here. geometry_turn is the snapshot the viewer renders.
export type MetaTurn = {
  index: number
  raw_turns: number[]
  edit_turn: number | null
  geometry_turn: number | null
  passed: boolean
  probes: { turn: number; name: string; args: Record<string, unknown>; result: string }[]
}

export type RecordDetail = Summary & {
  updated_at: string
  ratings: Record<string, number>
  cost: {
    input_tokens: number
    output_tokens: number
    cache_read_tokens: number
    total_usd: number
  }
  model_py: string
  provenance: Record<string, unknown> | null
  trace: TraceTurn[]
  diffs: Record<string, string>
  meta_turns: MetaTurn[]
}

const json = (r: Response) => {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

export const listRecords = (q: string): Promise<Summary[]> =>
  fetch(`/api/records?q=${encodeURIComponent(q)}`).then(json)

export const getRecord = (id: string): Promise<RecordDetail> =>
  fetch(`/api/records/${id}`).then(json)

export const stopRun = (id: string): Promise<{ stopped: boolean }> =>
  fetch(`/api/records/${id}/stop`, { method: 'POST' }).then(json)

export const setRating = (id: string, rater: string, score: number): Promise<RecordDetail> =>
  fetch(`/api/records/${id}/rating`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rater, score }),
  }).then(json)

export const clearRating = (id: string, rater: string): Promise<RecordDetail> =>
  fetch(`/api/records/${id}/rating?rater=${encodeURIComponent(rater)}`, { method: 'DELETE' }).then(json)

export const urdfUrl = (id: string) => `/api/records/${id}/files/model.urdf`
export const fileUrl = (id: string, path: string) => `/api/records/${id}/files/${path}`
// Per-turn geometry: compiled on demand + cached server-side (see viewer/server.py).
export const turnFileUrl = (id: string, turn: number, path: string) =>
  `/api/records/${id}/turn/${turn}/files/${path}`
export const turnUrdfUrl = (id: string, turn: number) => turnFileUrl(id, turn, 'model.urdf')
export const thumbUrl = (id: string) => fileUrl(id, 'assets/thumb.png')
