import { describe, expect, it } from "vitest";
import { blenderToThree, DIRECTIONS, directionOffset, threeToBlender } from "./coords";

describe("Blender -> three.js coordinates", () => {
  it("maps Z up to Y up and Blender -Y (the character's front) to +Z", () => {
    expect(blenderToThree([1, 2, 3])).toEqual([1, 3, -2]);
    expect(blenderToThree([0, -1, 0])).toEqual([0, 0, 1]);
  });

  it("round-trips", () => {
    expect(threeToBlender(blenderToThree([0.1, -0.2, 0.3]))).toEqual([0.1, -0.2, 0.3]);
  });

  it("puts the s camera in front of the character, 30 degrees up, like preview_8.py", () => {
    const [x, y, z] = directionOffset(0);
    expect(x).toBeCloseTo(0);
    expect(z).toBeGreaterThan(0);
    expect((Math.atan2(y, Math.hypot(x, z)) * 180) / Math.PI).toBeCloseTo(30);
  });

  it("turns w to Blender +X, the character's left", () => {
    const [x, , z] = directionOffset(90);
    expect(x).toBeCloseTo(Math.cos(Math.PI / 6));
    expect(z).toBeCloseTo(0);
    expect(DIRECTIONS.map((d) => d.name)).toEqual(["s", "sw", "w", "nw", "n", "ne", "e", "se"]);
  });
});
