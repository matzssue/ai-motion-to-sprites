// Blender world (Z up, the character faces -Y) <-> three.js world (Y up, the character faces +Z).
// Blender's glTF importer maps glTF (x, y, z) to Blender (x, -z, y); this is the inverse. Evidence: web/README.md.
import type { BlenderPoint } from "@/audit/schema";

export type Vec3 = [number, number, number];

export function blenderToThree([x, y, z]: BlenderPoint | Vec3): Vec3 {
  return [x, z, -y];
}

export function threeToBlender([x, y, z]: Vec3): Vec3 {
  return [x, -z, y];
}

export const DIRECTIONS = [
  { name: "s", yaw: 0 },
  { name: "sw", yaw: 45 },
  { name: "w", yaw: 90 },
  { name: "nw", yaw: 135 },
  { name: "n", yaw: 180 },
  { name: "ne", yaw: 225 },
  { name: "e", yaw: 270 },
  { name: "se", yaw: 315 },
] as const;

export type DirectionName = (typeof DIRECTIONS)[number]["name"];

/** Game camera pitch, as the default `--pitch` of pipeline/review/preview_8.py. */
export const CAMERA_PITCH_DEG = 30;

/** Unit vector from the character to the camera for a preset view, three.js axes.
 *  preview_8.py puts the camera at center + d * 6 with d = (sin yaw, -cos yaw, tan pitch) in Blender axes. */
export function directionOffset(yawDeg: number, pitchDeg = CAMERA_PITCH_DEG): Vec3 {
  const yaw = (yawDeg * Math.PI) / 180;
  const pitch = (pitchDeg * Math.PI) / 180;
  const [x, y, z] = blenderToThree([Math.sin(yaw), -Math.cos(yaw), Math.tan(pitch)]);
  const length = Math.hypot(x, y, z);
  return [x / length, y / length, z / length];
}
