"use client";

import { OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { useReview } from "@/state/store";
import { Character } from "./Character";

/** The whole WebGL part. Loaded with next/dynamic and ssr: false, so it never runs on the server. */
export default function Scene() {
  const model = useReview((s) => s.model);
  return (
    <Canvas camera={{ fov: 35, near: 0.01, far: 200, position: [0, 1, 5] }} dpr={[1, 2]} gl={{ alpha: true }}>
      <hemisphereLight args={["#ffffff", "#50555c", 1.4]} />
      <directionalLight position={[2, 4, 3]} intensity={2.2} />
      <directionalLight position={[-3, 2, -2]} intensity={0.7} />
      <OrbitControls makeDefault />
      {model && <Character key={model.gltf.scene.uuid} model={model} />}
    </Canvas>
  );
}
