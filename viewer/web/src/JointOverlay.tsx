import { createPortal } from '@react-three/fiber'
import { Html, Line } from '@react-three/drei'
import { Quaternion, Vector3 } from 'three'
import type { URDFJoint } from 'urdf-loader'

// Gizmos are portalled INTO each joint's Object3D so they inherit its world
// transform for free — no per-frame matrix copying.
const COLOR: Record<string, string> = {
  revolute: '#4a90d9',
  continuous: '#2fb6a3',
  prismatic: '#e08a3c',
}
const ABBR: Record<string, string> = { revolute: 'REV', continuous: 'CONT', prismatic: 'PRI' }
const UP = new Vector3(0, 1, 0)

function axisLabel(a: Vector3): string {
  const v = a.clone().normalize()
  for (const [k, n] of [['X', new Vector3(1, 0, 0)], ['Y', new Vector3(0, 1, 0)], ['Z', new Vector3(0, 0, 1)]] as const) {
    if (Math.abs(Math.abs(v.dot(n)) - 1) < 1e-3) return k
  }
  return `${v.x.toFixed(1)} ${v.y.toFixed(1)} ${v.z.toFixed(1)}`
}

function Gizmo({ joint, scale }: { joint: URDFJoint; scale: number }) {
  const axis = joint.axis.clone().normalize()
  const tip = axis.clone().multiplyScalar(scale)
  const color = COLOR[joint.jointType] ?? '#888'
  const quat = new Quaternion().setFromUnitVectors(UP, axis)
  return (
    <group>
      <Line points={[[0, 0, 0], [tip.x, tip.y, tip.z]]} color={color} lineWidth={2} />
      <mesh position={tip} quaternion={quat}>
        <coneGeometry args={[scale * 0.08, scale * 0.22, 12]} />
        <meshBasicMaterial color={color} />
      </mesh>
      <Html position={[tip.x, tip.y, tip.z]} center>
        <div className="joint-tag" style={{ borderColor: color, color }}>
          {ABBR[joint.jointType] ?? joint.jointType} {axisLabel(axis)}
        </div>
      </Html>
    </group>
  )
}

export function JointOverlay({ joints, scale }: { joints: URDFJoint[]; scale: number }) {
  return <>{joints.map((j) => createPortal(<Gizmo joint={j} scale={scale} />, j))}</>
}
