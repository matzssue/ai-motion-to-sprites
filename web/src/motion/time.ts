// Audit time is in Blender frames: motion_audit.py imports the GLB after read_factory_settings, so the scene runs
// at 24 fps and a glTF key at t seconds lands on frame t * 24. three.js clips are in seconds. Evidence: web/README.md.

export const BLENDER_FPS = 24;
export const QUARTER_FRAME = 0.25;

export function frameToSeconds(frame: number): number {
  return frame / BLENDER_FPS;
}

export function secondsToFrame(seconds: number): number {
  return seconds * BLENDER_FPS;
}

export function snapToQuarter(frame: number): number {
  return Math.round(frame / QUARTER_FRAME) * QUARTER_FRAME;
}

export function clampFrame(frame: number, endFrame: number): number {
  return Math.min(Math.max(frame, 0), endFrame);
}

/** Playback wraps around the clip end. */
export function wrapFrame(frame: number, endFrame: number): number {
  if (endFrame <= 0) return 0;
  return ((frame % endFrame) + endFrame) % endFrame;
}

/** Arrow-key step: onto the quarter-frame grid, then clamped to the clip. */
export function stepFrame(frame: number, step: number, endFrame: number): number {
  return clampFrame(snapToQuarter(frame + step), endFrame);
}

/** The audit samples from frame 0 to int(last key frame) every 1/4 frame, so its last `t` is floor(duration * 24).
 *  Returns the first clip with that length, or null. */
export function clipMatchingAudit(clips: { name: string; duration: number }[], lastSampleFrame: number): string | null {
  const match = clips.find((clip) => Math.floor(secondsToFrame(clip.duration) + 1e-6) === lastSampleFrame);
  return match ? match.name : null;
}
