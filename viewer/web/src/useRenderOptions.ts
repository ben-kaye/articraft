import { useEffect, useState } from 'react'

// Viewer display toggles. Persisted to localStorage so a chosen setup survives
// reloads and record switches. ponytail: localStorage only — add URL sync if
// sharing an exact view ever matters.
export type RenderOptions = {
  segmentColors: boolean // per-link palette vs URDF/neutral colours
  showCollisions: boolean // collision geometry instead of visual
  doubleSided: boolean // render back faces (thin walls)
  fancyLighting: boolean // env map + softer studio rig
  jointOverlay: boolean // axis/arrow/label gizmos at each joint
  animate: boolean // auto-sweep joints to preview motion
}

const DEFAULTS: RenderOptions = {
  segmentColors: true,
  showCollisions: false,
  doubleSided: false,
  fancyLighting: false,
  jointOverlay: false,
  animate: false,
}

const KEY = 'renderOptions'

export function useRenderOptions() {
  const [options, setOptions] = useState<RenderOptions>(() => {
    try {
      return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') }
    } catch {
      return DEFAULTS
    }
  })
  useEffect(() => {
    localStorage.setItem(KEY, JSON.stringify(options))
  }, [options])

  const toggle = (k: keyof RenderOptions) => setOptions((o) => ({ ...o, [k]: !o[k] }))
  return { options, toggle }
}
