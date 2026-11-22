import {
  AnimationClip,
  Bone,
  BufferGeometry,
  Float32BufferAttribute,
  Group,
  Mesh,
  QuaternionKeyframeTrack,
  Skeleton,
  SkinnedMesh,
  VectorKeyframeTrack,
} from "three";
import { describe, expect, it } from "vitest";
import { MotionRig, splitBodyAndProps } from "./rig";

function character() {
  const root = new Group();
  const hips = new Bone();
  hips.name = "hips";
  const hand = new Bone();
  hand.name = "hand";
  hand.position.set(0, 1, 0);
  hips.add(hand);
  root.add(hips);
  return { root, hips, hand };
}

const QUARTER_TURN = [0, 0, Math.SQRT1_2, Math.SQRT1_2];

describe("MotionRig", () => {
  it("samples a clip at a Blender frame", () => {
    const { root, hips } = character();
    const move = new AnimationClip("move", 2, [new VectorKeyframeTrack("hips.position", [0, 2], [0, 0, 0, 0, 48, 0])]);
    const rig = new MotionRig(root, [move]);
    rig.setAction("move");
    rig.setFrame(24);
    expect(hips.position.y).toBeCloseTo(24);
  });

  it("resets bones the new action does not animate (no pose bleed)", () => {
    const { root, hand } = character();
    const wave = new AnimationClip("wave", 1, [
      new QuaternionKeyframeTrack("hand.quaternion", [0, 1], [...QUARTER_TURN, ...QUARTER_TURN]),
      new VectorKeyframeTrack("hand.position", [0, 1], [0, 2, 0, 0, 2, 0]),
    ]);
    const walk = new AnimationClip("walk", 1, [new VectorKeyframeTrack("hips.position", [0, 1], [0, 0, 0, 1, 0, 0])]);
    const rig = new MotionRig(root, [wave, walk]);
    rig.setAction("wave");
    rig.setFrame(12);
    expect(hand.position.y).toBeCloseTo(2);
    rig.setAction("walk");
    rig.setFrame(12);
    expect(hand.position.y).toBeCloseTo(1);
    expect(hand.quaternion.w).toBeCloseTo(1);
  });

  it("refuses an unknown action", () => {
    const { root } = character();
    expect(() => new MotionRig(root, []).setAction("attack")).toThrow(/no animation named "attack"/);
  });
});

describe("splitBodyAndProps", () => {
  function skinned(vertices: number) {
    const geometry = new BufferGeometry();
    geometry.setAttribute("position", new Float32BufferAttribute(new Float32Array(vertices * 3), 3));
    const mesh = new SkinnedMesh(geometry);
    mesh.bind(new Skeleton([]));
    return mesh;
  }

  it("takes the skinned mesh with most vertices as the body", () => {
    const root = new Group();
    const body = skinned(30);
    const prop = skinned(10);
    const plain = new Mesh(new BufferGeometry());
    root.add(prop, body, plain);
    const split = splitBodyAndProps(root);
    expect(split.body).toBe(body);
    expect(split.props).toEqual([prop, plain]);
  });
});
