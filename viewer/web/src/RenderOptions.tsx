import type { RenderOptions as Opts } from './useRenderOptions'

const ITEMS: [keyof Opts, string][] = [
  ['segmentColors', 'segment colours'],
  ['showCollisions', 'collisions'],
  ['doubleSided', 'double-sided'],
  ['fancyLighting', 'fancy lighting'],
  ['jointOverlay', 'joint overlay'],
  ['animate', 'animate'],
]

export function RenderOptions({ options, toggle }: { options: Opts; toggle: (k: keyof Opts) => void }) {
  return (
    <div className="render-options">
      {ITEMS.map(([k, label]) => (
        <label key={k}>
          <input type="checkbox" checked={options[k]} onChange={() => toggle(k)} /> {label}
        </label>
      ))}
    </div>
  )
}
