import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage } from "./api";

/**
 * Loads data whenever `key` changes (pass null to skip). Keeps the previous data while reloading.
 * Put everything the request depends on into `key`, e.g. `chunks:${sourceId}`.
 *
 * How it works: the request runs in an effect keyed by `key#nonce`. `reload()` bumps the nonce to
 * re-run the same request. Each result is stored together with the key it was loaded for, so a
 * result is only "current" when its key matches; responses that arrive after the key changed or the
 * component unmounted are ignored. The latest `load` is kept in a ref, so callers can pass inline
 * functions without triggering extra requests.
 *
 * @param key Cache key describing the request, or null to load nothing.
 * @param load Function that performs the request.
 * @returns `data` (last loaded value, kept while reloading), `error` (message of the current
 *   request's failure), `loading` (current key not loaded yet) and `reload()` (fetch again).
 */
export function useApi<T>(key: string | null, load: () => Promise<T>) {
  const [nonce, setNonce] = useState(0);
  const [result, setResult] = useState<{ key: string; data?: T; error?: string } | null>(null);
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  });

  const fullKey = key === null ? null : `${key}#${nonce}`;
  useEffect(() => {
    if (fullKey === null) return;
    let cancelled = false;
    loadRef.current().then(
      (data) => !cancelled && setResult({ key: fullKey, data }),
      (e: unknown) => !cancelled && setResult({ key: fullKey, data: undefined, error: errorMessage(e) }),
    );
    return () => {
      cancelled = true;
    };
  }, [fullKey]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const current = result?.key === fullKey;
  return {
    data: key === null ? undefined : result?.data,
    error: current ? result?.error : undefined,
    loading: fullKey !== null && !current,
    reload,
  };
}
