import { describe, expect, it } from "vitest";
import { sampleIndex } from "./samples";

describe("sampleIndex", () => {
  it("reads the index character.py --sample takes", () => {
    expect(sampleIndex("body_s2")).toBe(2);
    expect(sampleIndex("kf_s10")).toBe(10);
    expect(sampleIndex("approved")).toBeNull();
  });
});
