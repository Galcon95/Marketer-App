/**
 * The login page's background pictures (public/login-bg/), one picked at random on every visit.
 *
 * The pictures are imported, not read from the folder at run time: only pictures Next.js knows at build time get
 * resized for the screen and a blurred placeholder while they load. To add a picture, put it in public/login-bg/
 * (landscape, about 1400-1920 px wide) and add one import and one entry below.
 */

import type { StaticImageData } from "next/image";
import bg1 from "../public/login-bg/1.jpg";
import bg2 from "../public/login-bg/2.jpg";
import bg3 from "../public/login-bg/3.jpg";
import bg4 from "../public/login-bg/4.jpg";

export const LOGIN_BACKGROUNDS: StaticImageData[] = [bg1, bg2, bg3, bg4];

/** Where the browser remembers the last picture shown, so the next visit shows another one. */
const LAST_KEY = "login-bg-last";

/**
 * A random index of `count` pictures, never `last` (the one shown last time) when there is more than one.
 * `random` returns a number in [0, 1), like Math.random.
 */
export function pickBackground(count: number, last: number | null, random: () => number = Math.random): number {
  if (count <= 1) return 0;
  const avoid = last !== null && last >= 0 && last < count;
  const i = Math.floor(random() * (avoid ? count - 1 : count));
  return avoid && i >= last ? i + 1 : i;
}

/** Pick this visit's picture and remember it (the storage may be blocked: then it is simply random). */
export function nextLoginBackground(): StaticImageData {
  let last: number | null = null;
  try {
    const saved = localStorage.getItem(LAST_KEY);
    last = saved === null ? null : Number(saved);
  } catch { /* storage blocked: no memory of the last picture */ }
  const i = pickBackground(LOGIN_BACKGROUNDS.length, Number.isInteger(last) ? last : null);
  try { localStorage.setItem(LAST_KEY, String(i)); } catch { /* storage blocked */ }
  return LOGIN_BACKGROUNDS[i];
}
