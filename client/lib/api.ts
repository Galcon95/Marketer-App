/**
 * Typed client for the Marketer App API (server/server.py, models in server/schemas.py).
 * Called from the browser; the server allows http://localhost:3000 via CORS.
 */

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

/** Single hard-coded project until project switching is built. */
export const PROJECT_ID = "demo-campaign";

/* ---------- Types (mirror server/schemas.py) ---------- */
export type SourceKind = "document" | "video" | "audio" | "text";
export type SourceStatus = "queued" | "transcribing" | "chunking" | "embedding" | "ready" | "failed";
export type AssetType = "blurb" | "social_post" | "newsletter" | "ad_copy" | "lead_magnet" | "persona";

export interface ServiceStatus { name: string; ok: boolean; detail: string }
export interface Health { ok: boolean; services: ServiceStatus[] }

export interface Project {
  id: string;
  name: string;
  description: string;
  created_at: string;
  source_count: number;
  chunk_count: number;
  asset_count: number;
}

export interface Source {
  id: string;
  project_id: string;
  filename: string;
  kind: SourceKind;
  size_bytes: number;
  status: SourceStatus;
  progress: number;
  chunk_count: number;
  created_at: string;
  error: string | null;
}

export interface ChunkLocation { chapter: string | null; page: number | null; start_time: string | null; end_time: string | null }
export interface Chunk { id: string; source_id: string; text: string; location: ChunkLocation; token_count: number }
export interface ChunkPage { items: Chunk[]; total: number; offset: number; limit: number }
export interface SearchHit { chunk: Chunk; score: number }
export interface SearchResponse { query: string; hits: SearchHit[] }

export interface Citation { chunk_id: string; source_id: string; location: ChunkLocation; quote: string; score: number }
export interface Asset {
  id: string;
  project_id: string;
  asset_type: AssetType;
  grounded: boolean;
  brief: string;
  text: string;
  citations: Citation[];
  created_at: string;
}
export interface GenerateRequest { asset_type: AssetType; brief: string; grounded: boolean; k?: number }

export interface VerifyItem { claim: string; status: "verified" | "not_found"; chunk_id: string | null; score: number | null }
export interface VerifyResponse { items: VerifyItem[] }

export const ASSET_TYPES: { value: AssetType; label: string }[] = [
  { value: "blurb", label: "Blurb / product description" },
  { value: "social_post", label: "Social post" },
  { value: "newsletter", label: "Newsletter" },
  { value: "ad_copy", label: "Ad copy" },
  { value: "lead_magnet", label: "Lead magnet" },
  { value: "persona", label: "Audience persona" },
];

export function assetTypeLabel(type: AssetType) {
  return ASSET_TYPES.find((t) => t.value === type)?.label ?? type;
}

/** "ch_04 · p.112" for documents, "00:12:34–00:13:20" for media. */
export function locationLabel(loc: ChunkLocation) {
  if (loc.start_time) return loc.end_time ? `${loc.start_time}–${loc.end_time}` : loc.start_time;
  return [loc.chapter, loc.page != null && `p.${loc.page}`].filter(Boolean).join(" · ");
}

/* ---------- Requests ---------- */
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

function postJson(body: unknown): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export const api = {
  health: () => request<Health>("/health"),
  getProject: () => request<Project>(`/projects/${PROJECT_ID}`),

  listSources: () => request<Source[]>(`/projects/${PROJECT_ID}/sources`),
  getSource: (sourceId: string) => request<Source>(`/sources/${sourceId}`),
  uploadSource: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Source>(`/projects/${PROJECT_ID}/sources`, { method: "POST", body: form });
  },
  deleteSource: (sourceId: string) => request<void>(`/sources/${sourceId}`, { method: "DELETE" }),

  listChunks: (sourceId: string, offset = 0, limit = 20) =>
    request<ChunkPage>(`/sources/${sourceId}/chunks?offset=${offset}&limit=${limit}`),
  search: (query: string, k = 5) => request<SearchResponse>(`/projects/${PROJECT_ID}/search`, postJson({ query, k })),

  generate: (body: GenerateRequest) => request<Asset>(`/projects/${PROJECT_ID}/generate`, postJson(body)),
  listAssets: () => request<Asset[]>(`/projects/${PROJECT_ID}/assets`),

  verify: (text: string) => request<VerifyResponse>(`/projects/${PROJECT_ID}/verify`, postJson({ text })),
};

export function errorMessage(e: unknown) {
  return e instanceof Error ? e.message : String(e);
}
