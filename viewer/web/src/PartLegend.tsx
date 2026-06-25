// Clickable list of links with their segment colour. Selecting echoes the same
// state the 3D click-to-select uses, so the two stay in sync.
export function PartLegend({
  links,
  selected,
  onSelect,
}: {
  links: { name: string; color: string }[]
  selected: string | null
  onSelect: (name: string | null) => void
}) {
  if (links.length <= 1) return null
  return (
    <div className="part-legend">
      {links.map((l) => (
        <button
          key={l.name}
          className={selected === l.name ? 'active' : ''}
          onClick={() => onSelect(selected === l.name ? null : l.name)}
        >
          <span className="swatch" style={{ background: l.color }} />
          {l.name}
        </button>
      ))}
    </div>
  )
}
