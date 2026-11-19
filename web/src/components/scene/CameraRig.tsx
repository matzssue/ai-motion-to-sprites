"use client";

import { useThree } from "@react-three/fiber";
import { useEffect } from "react";
import { PerspectiveCamera, Vector3, type Box3 } from "three";
import { blenderToThree, DIRECTIONS, directionOffset } from "@/motion/coords";
import { useReview } from "@/state/store";

const MARGIN = 1.3;
/** Close-up framing as a share of the character height (motion_audit.py renders close-ups 0.45 m wide at 1.8 m). */
const CLOSE_UP = 0.25;

type Controls = { target: Vector3; update: () => void };

/** Moves the orbit camera to one of the 8 game directions whenever a view is requested. */
export function CameraRig({ bounds }: { bounds: Box3 }) {
  const view = useReview((s) => s.view);
  const camera = useThree((s) => s.camera);
  const controls = useThree((s) => s.controls) as Controls | null;

  useEffect(() => {
    const yaw = DIRECTIONS.find((d) => d.name === view.direction)?.yaw ?? 0;
    const size = bounds.getSize(new Vector3());
    const center = view.focus ? new Vector3(...blenderToThree(view.focus)) : bounds.getCenter(new Vector3());
    const framed = view.focus ? size.y * CLOSE_UP : size.y * MARGIN;
    const fov = camera instanceof PerspectiveCamera ? camera.fov : 35;
    const distance = framed / 2 / Math.tan((fov * Math.PI) / 360);
    const [x, y, z] = directionOffset(yaw);
    camera.position.set(center.x + x * distance, center.y + y * distance, center.z + z * distance);
    if (controls) {
      controls.target.copy(center);
      controls.update();
    } else {
      camera.lookAt(center);
    }
  }, [view, bounds, camera, controls]);

  return null;
}
