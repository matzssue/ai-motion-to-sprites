import { useEffect, useRef } from "react";
import { usePlayhead } from "./store";

/** Runs `onFrame` now and on every playhead change, outside React rendering: for readouts that write to the DOM
 *  through refs (a cursor's position, a frame number). `onFrame` may change between renders. */
export function usePlayheadEffect(onFrame: (frame: number) => void): void {
  const callback = useRef(onFrame);
  useEffect(() => {
    callback.current = onFrame;
    callback.current(usePlayhead.getState().frame);
  });
  useEffect(() => usePlayhead.subscribe((state) => callback.current(state.frame)), []);
}
