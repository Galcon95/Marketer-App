/**
 * Typed client for the Marketer App API (server/server.py, models in server/schemas.py).
 * Called from the browser; the server allows http://localhost:3000 via CORS.
 */

/** Base URL of the FastAPI server; override with NEXT_PUBLIC_API_URL. */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

/** Single hard-coded project until project switching is built. */
export const PROJECT_ID = "demo-campaign";

/* ---------- Types (mirror server/schemas.py) ---------- */
/** Kind of content a source holds; decides how it will be ingested (parsed vs. transcribed). */
export type SourceKind = "document" | "video" | "audio" | "text";
/** uploaded = stored on the server, not processed yet; queued … embedding = ingestion running. */
export type SourceStatus = "uploaded" | "queued" | "transcribing" | "chunking" | "embedding" | "ready" | "failed";
/** Statuses during which ingestion is still running and the UI should keep polling. */
export const PROCESSING_STATUSES: SourceStatus[] = ["queued", "transcribing", "chunking", "embedding"];

/** Mirrors server/storage.py. The server enforces these too; checking here gives instant feedback. */
export const UPLOAD_EXTENSIONS = [".pdf"];
export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
/** Kinds of marketing content the generator can produce. */
export type AssetType = "blurb" | "social_post" | "newsletter" | "ad_copy" | "lead_magnet" | "persona";

/** Status of one backend dependency (API, vector DB, LLM); `detail` is a human-readable note. */
export interface ServiceStatus { name: string; ok: boolean; detail: string }
/** Response of GET /health: overall API status plus one entry per dependency. */
export interface Health { ok: boolean; services: ServiceStatus[] }

/** A project (marketing campaign) grouping sources, chunks and generated assets. */
export interface Project {
  id: string;
  name: string;
  description: string;
  created_at: string; // ISO 8601 timestamp (UTC)
  source_count: number; // computed by the server on every read
  chunk_count: number;
  asset_count: number;
}

/** One uploaded file in a project, plus its ingestion state. */
export interface Source {
  id: string;
  project_id: string;
  filename: string; // sanitized original file name
  kind: SourceKind;
  size_bytes: number;
  status: SourceStatus;
  progress: number; // progress of the current status step, 0-100
  chunk_count: number;
  created_at: string; // ISO 8601 timestamp (UTC)
  error: string | null; // set when status is "failed"
}

/** Where a chunk came from: chapter/page for documents, start/end time ("HH:MM:SS") for media. */
export interface ChunkLocation { chapter: string | null; page: number | null; start_time: string | null; end_time: string | null }
/** A piece of text cut from a source; the unit that is embedded and retrieved. */
export interface Chunk { id: string; source_id: string; text: string; location: ChunkLocation; token_count: number }
/** One page of a source's chunks (offset/limit pagination); `total` counts all chunks of the source. */
export interface ChunkPage { items: Chunk[]; total: number; offset: number; limit: number }
/** One search result: a chunk and its similarity score (0-1, higher is better). */
export interface SearchHit { chunk: Chunk; score: number }
/** Response of POST /search: the query and its hits, best first. */
export interface SearchResponse { query: string; hits: SearchHit[] }

/** Reference from a generated asset back to a supporting chunk; `quote` is an excerpt of it. */
export interface Citation { chunk_id: string; source_id: string; location: ChunkLocation; quote: string; score: number }
/** A generated piece of marketing content; `citations` is empty when not grounded. */
export interface Asset {
  id: string;
  project_id: string;
  asset_type: AssetType;
  grounded: boolean; // true = generated with RAG over the project's sources
  brief: string; // the instructions it was generated from
  text: string;
  citations: Citation[];
  created_at: string; // ISO 8601 timestamp (UTC)
}
/** Body of POST /generate. `k` = number of chunks to retrieve as context (server default 5). */
export interface GenerateRequest { asset_type: AssetType; brief: string; grounded: boolean; k?: number }

/** Verification result for one claim (sentence); chunk_id/score are set only when verified. */
export interface VerifyItem { claim: string; status: "verified" | "not_found"; chunk_id: string | null; score: number | null }
/** Response of POST /verify: one item per claim, in text order. */
export interface VerifyResponse { items: VerifyItem[] }

/** Asset types with their display labels, in the order shown in select boxes. */
export const ASSET_TYPES: { value: AssetType; label: string }[] = [
  { value: "blurb", label: "Blurb / product description" },
  { value: "social_post", label: "Social post" },
  { value: "newsletter", label: "Newsletter" },
  { value: "ad_copy", label: "Ad copy" },
  { value: "lead_magnet", label: "Lead magnet" },
  { value: "persona", label: "Audience persona" },
];

/**
 * Human-readable label of an asset type, e.g. "social_post" → "Social post".
 * @param type The asset type value.
 * @returns Its label from ASSET_TYPES, or the raw value if it is unknown.
 */
export function assetTypeLabel(type: AssetType) {
  return ASSET_TYPES.find((t) => t.value === type)?.label ?? type;
}

/**
 * Short display text for a chunk location.
 * Media locations (start_time set) win; otherwise chapter and page are joined, skipping missing parts.
 * @param loc The chunk location.
 * @returns "ch_04 · p.112" for documents, "00:12:34–00:13:20" for media.
 */
export function locationLabel(loc: ChunkLocation) {
  if (loc.start_time) return loc.end_time ? `${loc.start_time}–${loc.end_time}` : loc.start_time;
  return [loc.chapter, loc.page != null && `p.${loc.page}`].filter(Boolean).join(" · ");
}

/* ---------- Requests ---------- */
/**
 * Send a request to the API and parse the JSON response.
 * Network failures become "Could not reach the API"; non-2xx responses throw the server's
 * `detail` message (FastAPI's error format) or "API error <status>". 204 responses resolve to undefined.
 * @param path API path starting with "/", appended to API_URL.
 * @param init Optional fetch options (method, headers, body).
 * @returns The parsed response body typed as T.
 * @throws Error with a user-presentable message.
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new Error(`Could not reach the API at ${API_URL}`);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `API error ${res.status}`);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

/**
 * Build fetch options for a JSON POST request.
 * @param body Value to serialize as the JSON request body.
 */
function postJson(body: unknown): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

/** One typed function per API endpoint. Project-scoped calls use PROJECT_ID. All reject with an Error on failure. */
export const api = {
  /** GET /health: status of the API and its services. */
  health: () => request<Health>("/health"),
  /** GET /projects/{id}: the current project with its counts. */
  getProject: () => request<Project>(`/projects/${PROJECT_ID}`),

  /** GET /projects/{id}/sources: all sources of the current project. */
  listSources: () => request<Source[]>(`/projects/${PROJECT_ID}/sources`),
  /** GET /sources/{sourceId}: one source, used to poll ingestion status. */
  getSource: (sourceId: string) => request<Source>(`/sources/${sourceId}`),
  /**
   * POST /projects/{id}/sources: upload a file as a new source.
   * Multipart upload via XMLHttpRequest, because fetch() cannot report upload progress.
   * @param file The file to upload (sent as form field "file").
   * @param onProgress Optional callback receiving the sent percentage (0-100).
   * @returns The created Source; rejects with the server's error detail on failure.
   */
  uploadSource: (file: File, onProgress?: (percent: number) => void) =>
    new Promise<Source>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_URL}/projects/${PROJECT_ID}/sources`);
      xhr.responseType = "json";
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress?.(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as Source);
        else {
          const detail = xhr.response?.detail;
          reject(new Error(typeof detail === "string" ? detail : `Upload failed (HTTP ${xhr.status})`));
        }
      };
      xhr.onerror = () => reject(new Error(`Could not reach the API at ${API_URL}`));
      const form = new FormData();
      form.append("file", file);
      xhr.send(form);
    }),
  /** DELETE /sources/{sourceId}: remove a source, its stored file and its chunks. */
  deleteSource: (sourceId: string) => request<void>(`/sources/${sourceId}`, { method: "DELETE" }),

  /**
   * GET /sources/{sourceId}/chunks: one page of a source's chunks.
   * @param sourceId Source whose chunks to list.
   * @param offset Index of the first chunk (default 0).
   * @param limit Page size, 1-100 (default 20).
   */
  listChunks: (sourceId: string, offset = 0, limit = 20) =>
    request<ChunkPage>(`/sources/${sourceId}/chunks?offset=${offset}&limit=${limit}`),
  /**
   * POST /projects/{id}/search: find the chunks that best match a query.
   * @param query Natural-language search text.
   * @param k Number of hits to return (default 5).
   */
  search: (query: string, k = 5) => request<SearchResponse>(`/projects/${PROJECT_ID}/search`, postJson({ query, k })),

  /** POST /projects/{id}/generate: generate and store a new asset from a brief. */
  generate: (body: GenerateRequest) => request<Asset>(`/projects/${PROJECT_ID}/generate`, postJson(body)),
  /** GET /projects/{id}/assets: all generated assets of the current project, oldest first. */
  listAssets: () => request<Asset[]>(`/projects/${PROJECT_ID}/assets`),

  /** POST /projects/{id}/verify: check each claim of `text` against the project's sources. */
  verify: (text: string) => request<VerifyResponse>(`/projects/${PROJECT_ID}/verify`, postJson({ text })),
};

/**
 * Turn any caught value into a message string for display.
 * @param e The value thrown (usually an Error).
 * @returns The error's message, or the value converted to a string.
 */
export function errorMessage(e: unknown) {
  return e instanceof Error ? e.message : String(e);
}
