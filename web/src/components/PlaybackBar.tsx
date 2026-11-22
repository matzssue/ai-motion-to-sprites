"use client";

import { useRef } from "react";
import { DIRECTIONS } from "@/motion/coords";
import { QUARTER_FRAME, secondsToFrame } from "@/motion/time";
import {
  currentEndFrame,
  frameWholeBody,
  requestView,
  seek,
  selectAction,
  stepBy,
  togglePlaying,
  useReview,
  type Speed,
} from "@/state/store";
import { usePlayheadEffect } from "@/state/usePlayheadEffect";
import styles from "./PlaybackBar.module.css";

const SPEEDS: { value: Speed; label: string }[] = [
  { value: 1, label: "1×" },
  { value: 0.5, label: "½×" },
  { value: 0.25, label: "¼×" },
];

export function PlaybackBar() {
  const model = useReview((s) => s.model);
  const actionName = useReview((s) => s.actionName);
  const playing = useReview((s) => s.playing);
  const speed = useReview((s) => s.speed);
  const showProp = useReview((s) => s.showProp);
  const showSkeleton = useReview((s) => s.showSkeleton);
  const view = useReview((s) => s.view.direction);
  const closeUp = useReview((s) => s.view.focus !== null);
  const endFrame = useReview(currentEndFrame);
  const slider = useRef<HTMLInputElement>(null);
  const readout = useRef<HTMLOutputElement>(null);

  usePlayheadEffect((frame) => {
    if (slider.current) slider.current.value = String(frame);
    if (readout.current) readout.current.textContent = `fr. ${frame.toFixed(2)} / ${endFrame.toFixed(2)}`;
  });

  if (!model) return null;
  return (
    <div className={styles.bar}>
      <div className={styles.row}>
        <label className={styles.field}>
          <span className="muted">action</span>
          <select value={actionName ?? ""} onChange={(e) => {
              selectAction(e.target.value);
              e.currentTarget.blur();
            }}>
            {model.clips.map((clip) => (
              <option key={clip.name} value={clip.name}>
                {clip.name} ({secondsToFrame(clip.duration).toFixed(1)} fr.)
              </option>
            ))}
          </select>
        </label>
        <button type="button" className={styles.play} onClick={togglePlaying} aria-keyshortcuts="Space">
          {playing ? "Pause" : "Play"}
        </button>
        <div className={styles.group} role="group" aria-label="Step">
          <button type="button" onClick={() => stepBy(-1)} aria-label="Back one frame" title="Left arrow">
            −1
          </button>
          <button type="button" onClick={() => stepBy(-QUARTER_FRAME)} aria-label="Back a quarter frame" title="Shift+Left">
            −¼
          </button>
          <button type="button" onClick={() => stepBy(QUARTER_FRAME)} aria-label="Forward a quarter frame" title="Shift+Right">
            +¼
          </button>
          <button type="button" onClick={() => stepBy(1)} aria-label="Forward one frame" title="Right arrow">
            +1
          </button>
        </div>
        <div className={styles.group} role="group" aria-label="Speed">
          {SPEEDS.map((s) => (
            <button
              key={s.value}
              type="button"
              aria-pressed={speed === s.value}
              onClick={() => useReview.setState({ speed: s.value })}
            >
              {s.label}
            </button>
          ))}
        </div>
        <output ref={readout} className={styles.readout} />
      </div>
      <input
        ref={slider}
        className={styles.slider}
        type="range"
        min={0}
        max={endFrame}
        step={QUARTER_FRAME}
        defaultValue={0}
        aria-label="Frame"
        onInput={(e) => {
          useReview.setState({ playing: false });
          seek(Number(e.currentTarget.value));
        }}
      />
      <div className={styles.row}>
        <div className={styles.group} role="group" aria-label="Camera direction">
          {DIRECTIONS.map((d) => (
            <button key={d.name} type="button" aria-pressed={view === d.name} onClick={() => requestView(d.name)}>
              {d.name.toUpperCase()}
            </button>
          ))}
          <button type="button" aria-pressed={!closeUp} onClick={frameWholeBody} title="Frame the whole character">
            whole body
          </button>
        </div>
        <label className={styles.check}>
          <input type="checkbox" checked={showProp} onChange={(e) => useReview.setState({ showProp: e.target.checked })} />
          prop
        </label>
        <label className={styles.check}>
          <input
            type="checkbox"
            checked={showSkeleton}
            onChange={(e) => useReview.setState({ showSkeleton: e.target.checked })}
          />
          skeleton
        </label>
      </div>
    </div>
  );
}
