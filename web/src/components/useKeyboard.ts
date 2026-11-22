import { useEffect } from "react";
import { QUARTER_FRAME } from "@/motion/time";
import { stepBy, togglePlaying, useReview } from "@/state/store";

/** Space plays or pauses; Left/Right step one frame, with Shift a quarter frame (Space not on a focused button). */
export function useKeyboard(): void {
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      if (target?.closest("select, textarea, input:not([type=range]):not([type=checkbox])")) return;
      // Space activates a focused button, link or summary (the verdict and run controls): leave it to them
      if (e.key === " " && target?.closest("button, a, summary")) return;
      if (!useReview.getState().model) return;
      if (e.key === " ") {
        e.preventDefault();
        togglePlaying();
      } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        const amount = e.shiftKey ? QUARTER_FRAME : 1;
        stepBy(e.key === "ArrowLeft" ? -amount : amount);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}
