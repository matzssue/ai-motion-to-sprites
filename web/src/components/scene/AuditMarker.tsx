"use client";

import { Billboard, Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import type { Group } from "three";
import { markerAt } from "@/audit/marker";
import { formatLimit, formatSide, formatValue } from "@/audit/metrics";
import { blenderToThree } from "@/motion/coords";
import { isAuditedAction, useReview, usePlayhead } from "@/state/store";
import styles from "./AuditMarker.module.css";

const RADIUS = 0.005;

/** A dot at the audit point of the selected metric, drawn through the body (the point is often inside it). */
export function AuditMarker() {
  const audit = useReview((s) => s.audit);
  const metric = useReview((s) => s.selectedMetric);
  const onAuditedAction = useReview(isAuditedAction);
  const group = useRef<Group>(null);
  const label = useRef<HTMLDivElement>(null);
  const shownText = useRef("");
  const track = audit?.tracks.find((t) => t.key === metric) ?? null;

  useFrame(() => {
    if (!group.current || !audit || !track) return;
    const frame = usePlayhead.getState().frame;
    const point = onAuditedAction ? markerAt(audit.report, audit.samples, track.times, track.key, frame) : null;
    group.current.visible = point !== null;
    // drei's Html is a DOM overlay: it does not follow the group's `visible`
    if (label.current) label.current.style.display = point ? "" : "none";
    if (!point) return;
    group.current.position.set(...blenderToThree(point.where));
    const side = formatSide(point.side);
    const limit = track.limit === null ? formatLimit(track) : `limit ${formatLimit(track)}`;
    const text = `${track.label}${side ? ` (${side})` : ""}: ${formatValue(track.key, point.value)}, ${limit}, fr. ${point.frame.toFixed(2)}`;
    if (label.current && text !== shownText.current) {
      label.current.textContent = text;
      shownText.current = text;
    }
  });

  if (!track) return null;
  const failing = track.error !== null;
  return (
    <group ref={group} visible={false}>
      <mesh renderOrder={10}>
        <sphereGeometry args={[RADIUS, 20, 20]} />
        <meshBasicMaterial color={failing ? "#ff4d3a" : "#3aa0ff"} depthTest={false} transparent opacity={0.9} />
      </mesh>
      <Billboard>
        <mesh renderOrder={10}>
          <ringGeometry args={[RADIUS * 3, RADIUS * 3.8, 32]} />
          <meshBasicMaterial color={failing ? "#ff4d3a" : "#3aa0ff"} depthTest={false} transparent opacity={0.8} />
        </mesh>
      </Billboard>
      <Html style={{ pointerEvents: "none" }} zIndexRange={[20, 0]}>
        <div ref={label} className={failing ? `${styles.label} ${styles.failing}` : styles.label} />
      </Html>
    </group>
  );
}
