import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Canvas, useFrame, type ThreeEvent } from '@react-three/fiber'
import { OrbitControls, Grid, Bounds, useBounds } from '@react-three/drei'
import URDFLoader, { type URDFRobot, type URDFJoint } from 'urdf-loader'
import {
  Box3,
  DoubleSide,
  FrontSide,
  LoadingManager,
  Mesh,
  MeshPhysicalMaterial,
  Vector3,
  type Material,
  type Object3D,
} from 'three'
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js'
import { urdfUrl, fileUrl, turnUrdfUrl, turnFileUrl, getRecord } from './api'
import { JointControls } from './JointControls'
import { JointOverlay } from './JointOverlay'
import { PartLegend } from './PartLegend'
import { Playback } from './Playback'
import { RenderOptions } from './RenderOptions'
import { useRenderOptions, type RenderOptions as Opts } from './useRenderOptions'

// Scene colors mirror the CSS palette (--bg / grid greys). three.js can't read
// CSS vars without per-frame getComputedStyle, so the few it needs live here.
const SCENE = { bg: '#f4f5f7', gridCell: '#d2d4da', gridSection: '#b0b3bc' }

// Models rarely declare URDF materials, so paint each link a distinct palette
// colour by default so parts read apart.
// ponytail: fixed 12-colour cycle, swap for a hash if links ever collide visibly.
const PALETTE = [
  '#e8927c', '#6fb3c4', '#9cc5a1', '#d9b26b', '#b79ed1', '#7c9fd9',
  '#d98ab5', '#8fcabf', '#c9a27c', '#a3b86b', '#cf8f8f', '#7fb0a0',
]

// Named URDF materials → physical-render params. Keyed by substring of the
// material name; unmatched names fall back to a plain matte preset.
function presetFor(name: string): { metalness: number; roughness: number; transmission: number } {
  const n = name.toLowerCase()
  if (/glass|clear|transparent|acrylic/.test(n)) return { metalness: 0, roughness: 0.1, transmission: 0.9 }
  if (/metal|steel|alumin|chrome|iron|brass|copper/.test(n)) return { metalness: 1, roughness: 0.3, transmission: 0 }
  if (/felt|rubber|matte/.test(n)) return { metalness: 0, roughness: 0.95, transmission: 0 }
  if (/bakelite|plastic|abs|nylon/.test(n)) return { metalness: 0, roughness: 0.5, transmission: 0 }
  return { metalness: 0.1, roughness: 0.55, transmission: 0 }
}

type UrdfMat = { name: string; hex: number | null; opacity: number }

// Recolour every link mesh from source each call — no material-snapshot/restore
// system. The original URDF material (name/colour/opacity) is captured once into
// userData so we can re-derive on any option/selection change.
function applyMaterials(
  robot: URDFRobot,
  options: Opts,
  selectedPart: string | null,
  linkColors: Record<string, string>,
): void {
  for (const [name, link] of Object.entries(robot.links)) {
    const dim = selectedPart != null && selectedPart !== name
    const selected = selectedPart === name
    link.traverse((c) => {
      if (!(c instanceof Mesh)) return
      const cur = (Array.isArray(c.material) ? c.material[0] : c.material) as
        | (Material & { name?: string; color?: { getHex(): number }; opacity?: number })
        | undefined
      if (!c.userData.urdfMat) {
        c.userData.urdfMat = {
          name: cur?.name ?? '',
          hex: cur?.color?.getHex?.() ?? null,
          opacity: cur?.opacity ?? 1,
        } satisfies UrdfMat
      }
      const u = c.userData.urdfMat as UrdfMat
      // segmentColors → plain matte, ignore the URDF material preset
      const p = options.segmentColors
        ? { metalness: 0, roughness: 1, transmission: 0 }
        : presetFor(u.name)
      const mat = new MeshPhysicalMaterial({
        metalness: p.metalness,
        roughness: p.roughness,
        transmission: p.transmission,
        thickness: p.transmission ? 0.4 : 0,
        side: options.doubleSided ? DoubleSide : FrontSide,
      })
      if (options.segmentColors) mat.color.set(linkColors[name])
      else if (u.hex != null) mat.color.setHex(u.hex)
      else mat.color.set('#b8bcc4')
      if (dim) {
        mat.transparent = true
        mat.opacity = 0.12
      } else if (u.opacity < 1) {
        mat.transparent = true
        mat.opacity = u.opacity
      }
      if (selected) mat.emissive.set('#2a2a2a')
      const old = c.material
      c.material = mat
      ;(Array.isArray(old) ? old : [old]).forEach((m) => m?.dispose?.())
      c.castShadow = true
      c.receiveShadow = true
    })
  }
}

// Free GPU resources for a robot no longer shown. Without key={selected} the
// Canvas persists across switches, so we own the old robot's lifecycle.
function disposeRobot(root: Object3D): void {
  root.traverse((o) => {
    const m = o as Mesh
    m.geometry?.dispose?.()
    const mat = m.material
    if (mat) {
      ;(Array.isArray(mat) ? mat : [mat]).forEach((x) => {
        // Drop any textures the material references, then the material itself.
        for (const v of Object.values(x)) if ((v as { isTexture?: boolean } | null)?.isTexture) (v as { dispose?(): void }).dispose?.()
        x.dispose?.()
      })
    }
  })
}

// urdf-loader tags visual vs collision subtrees; flip visibility between them.
function setCollisionVisible(robot: URDFRobot, showCollisions: boolean): void {
  robot.traverse((o) => {
    const t = o as { isURDFVisual?: boolean; isURDFCollider?: boolean }
    if (t.isURDFVisual) o.visible = !showCollisions
    if (t.isURDFCollider) o.visible = showCollisions
  })
}

function useRobot(href: string | null, fileBase: (p: string) => string, onReady: () => void) {
  const [robot, setRobot] = useState<URDFRobot | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setRobot(null)
    setError(null)
    if (!href) return
    let loaded: URDFRobot | null = null
    const manager = new LoadingManager()
    const loader = new URDFLoader(manager)
    loader.parseCollision = true // load collisions too; toggled by visibility, not reload
    loader.packages = (pkg) => fileBase(pkg)
    // urdf-loader only handles .stl/.dae out of the box; the compiler emits .obj.
    // Runtime passes (path, manager, material, done); the .d.ts omits `material`.
    const loadObj = (
      path: string,
      mgr: LoadingManager,
      material: Material,
      done: (mesh: object | null, err?: Error) => void,
    ) => {
      new OBJLoader(mgr).load(
        path,
        (obj) => {
          obj.traverse((c) => {
            if (c instanceof Mesh) c.material = material
          })
          done(obj)
        },
        undefined,
        (err) => done(null, err as Error),
      )
    }
    loader.loadMeshCb = loadObj as unknown as typeof loader.loadMeshCb
    loader.load(
      href,
      (r) => {
        loaded = r
        // Meshes (.obj) load async via the manager; signal ready once they arrive.
        // Fire now too for primitive-only models that queue no mesh loads.
        manager.onLoad = () => {
          setRobot(r)
          onReady()
        }
        setRobot(r)
        onReady()
      },
      undefined,
      (e) => setError(String(e)),
    )
    // Switching records / unmounting: free the previous robot's GPU resources.
    return () => {
      if (loaded) disposeRobot(loaded)
    }
  }, [href, fileBase, onReady])

  return { robot, error }
}

// Expose the Bounds api (refresh/fit) to the parent so load + reset can re-frame.
function BoundsApi({ apiRef }: { apiRef: React.MutableRefObject<ReturnType<typeof useBounds> | null> }) {
  const api = useBounds()
  useEffect(() => {
    apiRef.current = api
  }, [api, apiRef])
  return null
}

// Sweep each independent joint min→max so range-of-motion reads at a glance.
function JointAnimator({ robot, joints }: { robot: URDFRobot; joints: URDFJoint[] }) {
  useFrame((state) => {
    const t = state.clock.elapsedTime
    joints.forEach((j, i) => {
      const cont = j.jointType === 'continuous'
      const lo = cont || !Number.isFinite(Number(j.limit.lower)) ? -Math.PI : Number(j.limit.lower)
      const hi = cont || !Number.isFinite(Number(j.limit.upper)) ? Math.PI : Number(j.limit.upper)
      robot.setJointValue(j.name, lo + (hi - lo) * (0.5 + 0.5 * Math.sin(t + i * 0.6)))
    })
  })
  return null
}

function Lighting({ fancy }: { fancy: boolean }) {
  // Fancy = a fuller rig (key+fill+rim+front) for nicer reads; plain = cheap.
  // ponytail: local light rig, no remote HDRI env map — keeps it offline.
  return (
    <>
      <hemisphereLight intensity={fancy ? 0.55 : 0.8} />
      <directionalLight position={[3, 5, 2]} intensity={fancy ? 1.0 : 1.2} castShadow shadow-mapSize={[1024, 1024]} />
      <directionalLight position={[-3, 2, -2]} intensity={0.4} />
      {fancy && <directionalLight position={[0, 2, -4]} intensity={0.5} />}
      {fancy && <directionalLight position={[0, 1, 5]} intensity={0.35} />}
    </>
  )
}

// Fixed options for headless thumbnail renders (see viewer/thumbnail.py).
// Real URDF material colours (not segment palette) so thumbnails read true-to-model.
const SNAPSHOT_OPTS: Opts = {
  segmentColors: false,
  showCollisions: false,
  doubleSided: false,
  fancyLighting: true,
  jointOverlay: false,
  animate: false,
}

export function Viewer3D({
  recordId,
  snapshot = false,
  viewedMeta = null,
  setViewedMeta = () => {},
}: {
  recordId: string
  snapshot?: boolean
  viewedMeta?: number | null
  setViewedMeta?: (m: number | null) => void
}) {
  const { data: record } = useQuery({ queryKey: ['record', recordId], queryFn: () => getRecord(recordId) })
  const live = useRenderOptions()
  const options = snapshot ? SNAPSHOT_OPTS : live.options
  const toggle = live.toggle
  const [selectedPart, setSelectedPart] = useState<string | null>(null)
  const [ready, setReady] = useState(0)
  const [gizmoScale, setGizmoScale] = useState(0.2)
  const bounds = useRef<ReturnType<typeof useBounds> | null>(null)

  // Playback: which compiled snapshot to render. null = the final model. In a played-back
  // meta-turn, render its geometry_turn, walking back to an earlier one if nothing built yet.
  const metas = useMemo(() => record?.meta_turns ?? [], [record])
  const playback = viewedMeta != null && !snapshot
  const geoTurn = useMemo(() => {
    if (!playback || viewedMeta == null) return null
    for (let i = viewedMeta; i >= 0; i--) {
      const g = metas[i]?.geometry_turn
      if (g != null) return g
    }
    return null
  }, [playback, viewedMeta, metas])
  const href = playback
    ? geoTurn != null
      ? turnUrdfUrl(recordId, geoTurn)
      : null
    : record?.has_urdf
      ? urdfUrl(recordId)
      : null
  const fileBase = useMemo(
    () =>
      geoTurn != null
        ? (p: string) => turnFileUrl(recordId, geoTurn, p)
        : (p: string) => fileUrl(recordId, p),
    [recordId, geoTurn],
  )

  const onReady = useMemo(() => () => setReady((n) => n + 1), [])
  const { robot, error } = useRobot(href, fileBase, onReady)

  useEffect(() => setSelectedPart(null), [recordId])

  // Deterministic per-link colour (same iteration order as applyMaterials).
  const linkColors = useMemo(() => {
    const m: Record<string, string> = {}
    if (robot) Object.keys(robot.links).forEach((n, i) => (m[n] = PALETTE[i % PALETTE.length]))
    return m
  }, [robot])

  // Independent (non-fixed, non-mimic) joints drive sliders, overlay and animation.
  const movableJoints = useMemo(
    () =>
      robot
        ? Object.values(robot.joints).filter(
            (j) => j.jointType !== 'fixed' && !(j as { mimicJoint?: string }).mimicJoint,
          )
        : [],
    [robot],
  )

  // Recolour on any change to robot/options/selection. (`options` is a stable
  // ref between toggles, so this only fires when something actually changes.)
  useEffect(() => {
    if (robot) applyMaterials(robot, options, selectedPart, linkColors)
  }, [robot, ready, options, selectedPart, linkColors])

  useEffect(() => {
    if (robot) setCollisionVisible(robot, options.showCollisions)
  }, [robot, ready, options.showCollisions])

  // On every load (incl. async meshes) re-frame and size gizmos. OrbitControls
  // stays mounted across record switches, so Bounds.fit preserves the view angle.
  useEffect(() => {
    if (!robot || !ready) return
    const size = new Box3().setFromObject(robot).getSize(new Vector3())
    setGizmoScale(Math.max(size.x, size.y, size.z) * 0.25 || 0.2)
    bounds.current?.refresh().clip().fit()
    // Headless thumbnail: flag readiness after a frame settles so Playwright shoots.
    if (snapshot)
      requestAnimationFrame(() => requestAnimationFrame(() => (document.body.dataset.ready = '1')))
  }, [robot, ready, snapshot])

  const pick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation()
    let o: Object3D | null = e.object
    while (o && !(o as { isURDFLink?: boolean }).isURDFLink) o = o.parent
    const name = (o as { urdfName?: string } | null)?.urdfName ?? null
    setSelectedPart((prev) => (prev === name ? null : name))
  }

  return (
    <div className="viewport">
      <Canvas
        camera={{ position: [0.5, 0.5, 0.5], fov: 50 }}
        shadows
        onPointerMissed={() => setSelectedPart(null)}
      >
        <color attach="background" args={[snapshot ? '#ffffff' : SCENE.bg]} />
        <Lighting fancy={options.fancyLighting} />
        {!snapshot && (
          <Grid args={[2, 2]} cellColor={SCENE.gridCell} sectionColor={SCENE.gridSection} infiniteGrid fadeDistance={6} />
        )}
        {robot && (
          <Bounds fit clip margin={1.2}>
            <BoundsApi apiRef={bounds} />
            {/* URDF uses Z-up; rotate to three's Y-up. */}
            <group rotation={[-Math.PI / 2, 0, 0]}>
              <primitive object={robot} onClick={pick} dispose={null} />
              {options.jointOverlay && <JointOverlay joints={movableJoints} scale={gizmoScale} />}
            </group>
            {options.animate && <JointAnimator robot={robot} joints={movableJoints} />}
          </Bounds>
        )}
        <OrbitControls makeDefault />
      </Canvas>

      {!snapshot && <RenderOptions options={options} toggle={toggle} />}
      {!snapshot && robot && (
        <PartLegend
          links={Object.keys(robot.links).map((n) => ({ name: n, color: linkColors[n] }))}
          selected={selectedPart}
          onSelect={setSelectedPart}
        />
      )}
      {!snapshot && metas.length > 0 && (
        <Playback metas={metas} viewedMeta={viewedMeta} setViewedMeta={setViewedMeta} />
      )}
      {!snapshot && (
        <div className="controls">
          <button onClick={() => bounds.current?.refresh().clip().fit()}>reset camera</button>
        </div>
      )}

      {/* Final-model status (hidden during playback, which has its own messages). */}
      {!playback && record && !record.has_urdf && (
        <div className="overlay">compile failed — no geometry to show</div>
      )}
      {!playback && record?.has_urdf && !record.compile_ok && robot && (
        <div className="overlay error">QC failed — showing geometry only</div>
      )}
      {/* Playback status. */}
      {playback && geoTurn == null && <div className="overlay info">no geometry built yet at this meta-turn</div>}
      {playback && geoTurn != null && (
        <div className="overlay info">meta-turn {viewedMeta} · geometry from turn {geoTurn}</div>
      )}
      {error && <div className="overlay error">URDF failed: {error}</div>}
      {href && !robot && !error && (
        <div className="overlay loading">
          <span className="spinner" />
          <span>loading…</span>
        </div>
      )}
      {!snapshot && robot && !options.animate && <JointControls robot={robot} joints={movableJoints} />}
    </div>
  )
}
