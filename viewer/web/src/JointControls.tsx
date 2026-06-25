import { useState } from 'react'
import type { URDFRobot, URDFJoint } from 'urdf-loader'

// `joints` is pre-filtered to independent joints (non-fixed, non-mimic) by the
// parent — driven mimic joints follow their source, so they get no slider.
export function JointControls({ robot, joints }: { robot: URDFRobot; joints: URDFJoint[] }) {
  const [, force] = useState(0)
  const [open, setOpen] = useState(true)
  if (joints.length === 0) return null

  const reset = () => {
    joints.forEach((j) => robot.setJointValue(j.name, 0))
    force((n) => n + 1)
  }

  return (
    <div className="joints">
      <div className="joints-head" onClick={() => setOpen((o) => !o)}>
        <span>{open ? '▾' : '▸'} joints</span>
        <button className="copy" onClick={(e) => { e.stopPropagation(); reset() }}>reset</button>
      </div>
      {open &&
        joints.map((j) => {
          const continuous = j.jointType === 'continuous'
          // Limit-less revolute/prismatic joints yield NaN bounds — fall back to ±π.
          const min = continuous || !Number.isFinite(Number(j.limit.lower)) ? -Math.PI : Number(j.limit.lower)
          const max = continuous || !Number.isFinite(Number(j.limit.upper)) ? Math.PI : Number(j.limit.upper)
          const value = Number(j.angle)
          return (
            <label key={j.name} className="joint">
              <span>{j.name}</span>
              <div className="joint-row">
                <input
                  type="range"
                  min={min}
                  max={max}
                  step={(max - min) / 200 || 0.01}
                  value={value}
                  onChange={(e) => {
                    robot.setJointValue(j.name, Number(e.target.value))
                    force((n) => n + 1)
                  }}
                />
                <span className="val">{value.toFixed(2)}</span>
              </div>
            </label>
          )
        })}
    </div>
  )
}
