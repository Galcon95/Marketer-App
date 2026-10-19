import { clsx, type ClassValue } from "clsx";
/** Join class names (clsx). */
export const cn = (...c: ClassValue[]) => clsx(c);
