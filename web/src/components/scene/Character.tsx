"use client";

import { Grid } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import { Box3, Mesh, SkeletonHelper } from "three";
import { MotionRig, splitBodyAndProps } from "@/motion/rig";
import { BLENDER_FPS, wrapFrame } from "@/motion/time";
import { currentEndFrame, seek, useReview, usePlayhead, type LoadedModel } from "@/state/store";
import { AuditMarker } from "./AuditMarker";
import { CameraRig } from "./CameraRig";

const MAX_STEP_SECONDS = 0.1;

export function Character({ model }: { model: LoadedModel }) {
  const actionName = useReview((s) => s.actionName);
  const showProp = useReview((s) => s.showProp);
  const showSkeleton = useReview((s) => s.showSkeleton);

  const root = model.gltf.scene;
  const rig = useMemo(() => new MotionRig(root, model.clips), [root, model.clips]);
  const props = useMemo(() => splitBodyAndProps(root).props, [root]);
  const skeleton = useMemo(() => new SkeletonHelper(root), [root]);
  const restBounds = useMemo(() => {
    rig.resetToRest();
    root.updateMatrixWorld(true);
    return new Box3().setFromObject(root, true);
  }, [rig, root]);

  useEffect(() => {
    // bounding volumes are computed for the bind pose; an animated limb may leave them
    root.traverse((node) => {
      if (node instanceof Mesh) node.frustumCulled = false;
    });
    return () => rig.dispose();
  }, [root, rig]);

  useEffect(() => {
    if (actionName) rig.setAction(actionName);
  }, [rig, actionName]);

  useEffect(() => {
    props.forEach((prop) => (prop.visible = showProp));
  }, [props, showProp]);

  useFrame((_, delta) => {
    const state = useReview.getState();
    let frame = usePlayhead.getState().frame;
    if (state.playing) {
      frame = wrapFrame(frame + Math.min(delta, MAX_STEP_SECONDS) * BLENDER_FPS * state.speed, currentEndFrame(state));
      seek(frame);
    }
    rig.setFrame(frame);
  });

  return (
    <>
      <primitive object={root} />
      <primitive object={skeleton} visible={showSkeleton} />
      <Grid
        position={[0, restBounds.min.y, 0]}
        infiniteGrid
        cellSize={0.1}
        sectionSize={1}
        cellColor="#8a9198"
        sectionColor="#5d6670"
        fadeDistance={12}
      />
      <CameraRig bounds={restBounds} />
      <AuditMarker />
    </>
  );
}
