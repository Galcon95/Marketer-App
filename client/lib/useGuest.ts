import { api } from "./api";
import { useApi } from "./useApi";

/**
 * True while the signed-in user is the public demo's shared guest account (GET /me `guest`, loaded once per page):
 * views hide what the guest may not do (upload, delete, change a cover, keys, Facebook, YouTube, the agent). The
 * server refuses those anyway (403); this only keeps the buttons away. False while /me is loading.
 */
export function useGuest(): boolean {
  return useApi("me", api.me).data?.guest ?? false;
}
