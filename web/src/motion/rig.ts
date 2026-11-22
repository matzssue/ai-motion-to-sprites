// Plays one action of a loaded GLB at an exact frame. Plain three.js, no React and no WebGL, so it is unit-tested.
import { AnimationMixer, Mesh, Object3D, Quaternion, SkinnedMesh, Vector3, type AnimationAction, type AnimationClip } from "three";
import { frameToSeconds } from "./time";

type LocalTransform = { position: Vector3; quaternion: Quaternion; scale: Vector3 };

export class MotionRig {
  readonly mixer: AnimationMixer;
  private readonly restPose = new Map<Object3D, LocalTransform>();
  private action: AnimationAction | null = null;

  constructor(
    readonly root: Object3D,
    readonly clips: AnimationClip[],
  ) {
    root.traverse((node) => {
      this.restPose.set(node, {
        position: node.position.clone(),
        quaternion: node.quaternion.clone(),
        scale: node.scale.clone(),
      });
    });
    this.mixer = new AnimationMixer(root);
  }

  get clip(): AnimationClip | null {
    return this.action?.getClip() ?? null;
  }

  /** A bone without tracks in the new clip would keep the pose of the previous one, so every node goes back to its
   *  rest transform first (motion_audit.py and preview_8.py reset `matrix_basis` for the same reason). */
  setAction(name: string): void {
    const clip = this.clips.find((c) => c.name === name);
    if (!clip) throw new Error(`no animation named "${name}" in this GLB`);
    this.mixer.stopAllAction();
    this.resetToRest();
    this.action = this.mixer.clipAction(clip);
    this.action.play();
    this.action.paused = true;
  }

  /** Pose at a Blender frame (fractions allowed); the playhead, not the mixer clock, owns time. */
  setFrame(frame: number): void {
    if (!this.action) return;
    this.action.time = frameToSeconds(frame);
    this.mixer.update(0);
  }

  resetToRest(): void {
    for (const [node, rest] of this.restPose) {
      node.position.copy(rest.position);
      node.quaternion.copy(rest.quaternion);
      node.scale.copy(rest.scale);
    }
  }

  dispose(): void {
    this.mixer.stopAllAction();
    this.mixer.uncacheRoot(this.root);
  }
}

/** The body is the skinned mesh with the most vertices; every other mesh is a prop. motion_audit.py picks the same way. */
export function splitBodyAndProps(root: Object3D): { body: Mesh | null; props: Mesh[] } {
  const meshes: Mesh[] = [];
  root.traverse((node) => {
    if (node instanceof Mesh) meshes.push(node);
  });
  const skinned = meshes.filter((m) => m instanceof SkinnedMesh);
  const candidates = skinned.length ? skinned : meshes;
  const body = candidates.reduce<Mesh | null>(
    (best, m) => (!best || vertexCount(m) > vertexCount(best) ? m : best),
    null,
  );
  return { body, props: meshes.filter((m) => m !== body) };
}

function vertexCount(mesh: Mesh): number {
  return mesh.geometry.getAttribute("position")?.count ?? 0;
}
