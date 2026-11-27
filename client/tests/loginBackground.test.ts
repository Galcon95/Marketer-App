import { describe, expect, it } from "vitest";
import { pickBackground } from "../lib/loginBackground";

describe("pickBackground", () => {
  it("never picks the picture shown last time", () => {
    for (let last = 0; last < 4; last++) {
      for (const r of [0, 0.3, 0.5, 0.74, 0.99]) {
        expect(pickBackground(4, last, () => r)).not.toBe(last);
      }
    }
  });

  it("reaches every other picture", () => {
    const seen = new Set([0, 0.34, 0.67].map((r) => pickBackground(4, 1, () => r)));
    expect(seen).toEqual(new Set([0, 2, 3]));
  });

  it("picks from all pictures on a first visit or with a stale memory", () => {
    expect(pickBackground(4, null, () => 0.99)).toBe(3);
    expect(pickBackground(4, 7, () => 0.99)).toBe(3);
  });

  it("handles a single picture", () => {
    expect(pickBackground(1, 0, () => 0.5)).toBe(0);
  });
});
