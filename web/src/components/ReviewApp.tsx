"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState, type DragEvent } from "react";
import { loadFiles, loadFromUrl } from "@/loading/load";
import { applyLoad, useReview } from "@/state/store";
import { AuditHeader } from "./AuditHeader";
import { EmptyState } from "./EmptyState";
import { MetricTable } from "./MetricTable";
import { PlaybackBar } from "./PlaybackBar";
import styles from "./ReviewApp.module.css";
import { Timeline } from "./Timeline";
import { useKeyboard } from "./useKeyboard";

const Scene = dynamic(() => import("./scene/Scene"), {
  ssr: false,
  loading: () => <p className={styles.stageNote}>Starting the 3D view…</p>,
});

async function load(task: Promise<Parameters<typeof applyLoad>[0]>) {
  useReview.setState({ loading: true });
  applyLoad(await task);
}

export function ReviewApp() {
  const model = useReview((s) => s.model);
  const audit = useReview((s) => s.audit);
  const loading = useReview((s) => s.loading);
  const problems = useReview((s) => s.problems);
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);
  useKeyboard();

  useEffect(() => {
    const data = new URLSearchParams(window.location.search).get("data");
    if (data) void load(loadFromUrl(data));
  }, []);

  function onDragEnter(e: DragEvent) {
    e.preventDefault();
    dragDepth.current += 1;
    setDragging(true);
  }

  function onDragLeave() {
    dragDepth.current -= 1;
    if (dragDepth.current <= 0) setDragging(false);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    const files = [...e.dataTransfer.files];
    if (files.length) void load(loadFiles(files));
  }

  function onPick(files: FileList | null) {
    if (files?.length) void load(loadFiles([...files]));
    if (fileInput.current) fileInput.current.value = "";
  }

  return (
    <div
      className={styles.app}
      onDragEnter={onDragEnter}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <header className={styles.top}>
        <AuditHeader />
        <button type="button" onClick={() => fileInput.current?.click()}>
          Open files…
        </button>
        <input
          ref={fileInput}
          type="file"
          multiple
          accept=".glb,.json"
          hidden
          onChange={(e) => onPick(e.target.files)}
        />
      </header>

      {loading && <p className={styles.status}>Loading…</p>}
      {problems.length > 0 && (
        <ul className={styles.problems} role="alert">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}

      {model || audit ? (
        <main className={styles.workspace}>
          <section className={styles.stage} aria-label="Motion">
            <div className={styles.viewport}>
              {model ? <Scene /> : <p className={styles.stageNote}>Drop the GLB to see the motion.</p>}
            </div>
            <PlaybackBar />
            <Timeline />
          </section>
          <aside className={styles.side}>
            <MetricTable />
          </aside>
        </main>
      ) : (
        <EmptyState onOpen={() => fileInput.current?.click()} />
      )}

      {dragging && <div className={styles.dropOverlay}>Drop the GLB and audit files</div>}
    </div>
  );
}
