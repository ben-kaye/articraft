import { useState, useCallback, useRef, useEffect } from 'react';
import * as THREE from 'three';
import type { UrdfSpec, UrdfJoint } from './urdf-parser';

export interface JointControllerState {
  jointValues: Map<string, number>;
  setJointValue: (name: string, value: number) => void;
  applyJointValues: (values: Map<string, number>, options?: { commit?: boolean }) => void;
  resetAll: () => void;
}

interface JointRuntime {
  spec: UrdfJoint;
  axis: THREE.Vector3;
}

const DEFAULT_AXIS: [number, number, number] = [0, 0, 1];
const tempQuaternion = new THREE.Quaternion();
const tempOffset = new THREE.Vector3();

/**
 * Hook for managing joint values and applying them to the Three.js scene graph.
 *
 * Maintains a Map<string, number> of joint name to current value.
 * setJointValue applies the appropriate rotation (revolute/continuous) or
 * translation (prismatic) to the joint node based on the URDF axis definition.
 */
export function useJointController(
  jointNodes: Map<string, THREE.Object3D> | null,
  urdfSpec: UrdfSpec | null,
): JointControllerState {
  const [jointValues, setJointValues] = useState<Map<string, number>>(new Map());

  // Cache the normalized joint axis and spec so animation does not allocate per frame.
  const jointRuntimeMap = useRef<Map<string, JointRuntime>>(new Map());

  // Rebuild the runtime cache whenever the urdfSpec changes.
  useEffect(() => {
    const map = new Map<string, JointRuntime>();
    if (urdfSpec) {
      for (const joint of urdfSpec.joints) {
        map.set(joint.name, {
          spec: joint,
          axis: new THREE.Vector3(...(joint.axis ?? DEFAULT_AXIS)).normalize(),
        });
      }
    }
    jointRuntimeMap.current = map;

    // Reset values when the spec changes (new model loaded).
    setJointValues(new Map());
  }, [urdfSpec]);

  const setJointValue = useCallback(
    (name: string, value: number) => {
      if (!jointNodes) return;

      const node = jointNodes.get(name);
      const runtime = jointRuntimeMap.current.get(name);
      if (!node || !runtime) return;

      applyJointValue(node, runtime.spec, runtime.axis, value);

      setJointValues((prev) => {
        const next = new Map(prev);
        next.set(name, value);
        return next;
      });
    },
    [jointNodes],
  );

  const applyJointValues = useCallback(
    (values: Map<string, number>, options?: { commit?: boolean }) => {
      if (!jointNodes) return;

      for (const [name, node] of jointNodes) {
        const runtime = jointRuntimeMap.current.get(name);
        if (!runtime) {
          continue;
        }

        applyJointValue(node, runtime.spec, runtime.axis, values.get(name) ?? 0);
      }

      if (options?.commit) {
        setJointValues(new Map(values));
      }
    },
    [jointNodes],
  );

  const resetAll = useCallback(() => {
    applyJointValues(new Map(), { commit: true });
  }, [applyJointValues]);

  return { jointValues, setJointValue, applyJointValues, resetAll };
}

/**
 * Apply a joint value to a Three.js node.
 *
 * For revolute/continuous joints, a quaternion rotation around the joint axis is applied.
 * For prismatic joints, a translation along the joint axis is applied.
 */
function applyJointValue(
  node: THREE.Object3D,
  spec: UrdfJoint,
  axis: THREE.Vector3,
  value: number,
): void {
  switch (spec.type) {
    case 'revolute':
    case 'continuous': {
      tempQuaternion.setFromAxisAngle(axis, value);
      node.quaternion.copy(tempQuaternion);
      break;
    }
    case 'prismatic': {
      // Reset to origin translation then apply offset along axis.
      tempOffset.copy(axis).multiplyScalar(value);
      node.position.copy(tempOffset);
      break;
    }
    default:
      // Fixed/floating/planar joints are not user-controllable.
      break;
  }
}
