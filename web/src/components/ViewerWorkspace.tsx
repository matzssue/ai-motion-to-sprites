"use client";

import dynamic from "next/dynamic";
import type { ReactNode } from "react";
import { useReview } from "@/state/store";
import { MetricTable } from "./MetricTable";
import { PlaybackBar } from "./PlaybackBar";
import { Timeline } from "./Timeline";
import styles from "./ViewerWorkspace.module.css";

const Scene = dynamic(() => import("./scene/Scene"), {
  ssr: false,
  loading: () => <p className={styles.stageNote}>Starting the 3D view…</p>,
});

/** 3D view, playback bar and timeline, with the metric table (and optionally a panel above it) at the side. */
export function ViewerWorkspace({ side }: { side?: ReactNode }) {
  const model = useReview((s) => s.model);
  return (
    <main className={styles.workspace}>
      <section className={styles.stage} aria-label="Motion">
        <div className={styles.viewport}>
          {model ? <Scene /> : <p className={styles.stageNote}>Drop the GLB to see the motion.</p>}
        </div>
        <PlaybackBar />
        <Timeline />
      </section>
      <aside className={styles.side}>
        {side}
        <MetricTable />
      </aside>
    </main>
  );
}
