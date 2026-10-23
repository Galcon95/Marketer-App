/**
 * Typed client for the Marketer App API (server/server.py, models in server/app/core/schemas.py).
 * Called from the browser; the server allows http://localhost:3000 via CORS.
 */

/** Base URL of the FastAPI server; override with NEXT_PUBLIC_API_URL. */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

/** The one client (the API calls it a project) until several clients are supported. */
export const PROJECT_ID = "demo-campaign";

/* ---------- Types (mirror server/app/core/schemas.py) ---------- */
/** Kind of content a source holds; decides how it will be ingested (parsed vs. transcribed). */
export type SourceKind = "document" | "video" | "audio" | "text";
/** uploaded = stored on the server, not processed yet; queued … embedding = ingestion running. */
export type SourceStatus = "uploaded" | "queued" | "transcribing" | "chunking" | "embedding" | "ready" | "failed";
/** Statuses during which ingestion is still running and the UI should keep polling. */
export const PROCESSING_STATUSES: SourceStatus[] = ["queued", "transcribing", "chunking", "embedding"];

/** Mirrors server/app/core/storage.py. The server enforces these too; checking here gives instant feedback. */
export const UPLOAD_EXTENSIONS = [".pdf"];
export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
/** Kinds of marketing content the generator can produce. */
export type AssetType =
  | "blurb" | "social_post" | "social_reply" | "video_script" | "youtube_video"
  | "newsletter" | "ad_copy" | "lead_magnet" | "persona";
/** Writing style options for generated assets (mirror server/app/core/schemas.py). */
export type Tone = "neutral" | "inspiring" | "friendly" | "professional" | "punchy" | "literary";
export type Length = "short" | "standard" | "long"; // not used for social posts and replies (the platform decides)
export type Platform = "x" | "linkedin" | "instagram" | "facebook" | "tiktok" | "youtube"; // for posts, replies, video scripts

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
  token_count: number; // LLM tokens used by all generated assets of the project
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
  author: string; // from the PDF's metadata; "" if unknown
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
  tokens: number; // LLM tokens (prompt + completion) used to generate it
  tone: Tone;
  length: Length;
  audience: string;
  platform: Platform | null; // set for social posts and replies
  reply_to: string; // the post it replies to (social_reply only)
  search_query: string; // what was searched in the books ("" when zero-shot)
  edited: boolean; // true once the user changed the text
  humanize: number; // the "how human" setting it was generated with (0-100)
  ai_tells: string[]; // AI-typical phrases still found in the final text (empty = none)
  source_ids: string[]; // the book(s) it was generated for; empty = all books
  campaign_id: string; // set for assets of a campaign kit (POST /campaigns), "" otherwise
  persona: string; // campaign posts: the persona the post is written for
  angle: string; // campaign posts: hook, teaser, question, behind the scenes or call to action
}
/** Body of POST /generate. `k` = number of chunks to retrieve as context (server default 5). */
/**
 * Body of POST /generate. For "social_reply", reply_to (the post) is required and brief is an optional
 * angle; for all other types brief is required. Options not given use the server defaults.
 */
export interface GenerateRequest {
  asset_type: AssetType;
  brief: string;
  grounded: boolean;
  k?: number;
  tone?: Tone;
  length?: Length;
  audience?: string;
  platform?: Platform;
  reply_to?: string;
  humanize?: number; // 0-100: how human it should sound (default 60)
  source_ids?: string[]; // the book(s) to work on; omitted = all books
}

/** Body of POST /campaigns: a short book brief for a zero-shot campaign kit (the model sees only this). */
export interface CampaignRequest {
  title: string;
  author?: string;
  genre?: string;
  themes?: string[];
  premise: string; // hook / premise
  comparables?: string; // "for fans of ..."
  audience?: string; // optional audience focus for the personas
  humanize?: number; // 0-100 (default 60)
  source_id?: string | null; // the book in the library, if it is one
}
/** Response of POST /campaigns: the stored assets of one kit. */
export interface CampaignResponse { campaign_id: string; personas: Asset[]; posts: Asset[]; blurb: Asset; tokens: number }

/** Verification result for one claim (sentence); chunk_id/score are set only when verified. */
export interface VerifyItem { claim: string; status: "verified" | "not_found"; chunk_id: string | null; score: number | null }
/** Response of POST /verify: one item per claim, in text order. */
export interface VerifyResponse { items: VerifyItem[] }

/** Response of POST /ask: an answer written from the books, with its cited and all retrieved passages. */
export interface AskResponse {
  question: string;
  search_query: string; // what was searched: the question, or its standalone rewrite for a follow-up
  answer: string; // plain text with [n] markers matching `citations`
  citations: Citation[];
  passages: SearchHit[]; // all retrieved passages, best first
  model: string;
  tokens: number;
  conversation_id: string | null; // send it with the next question to continue the chat
  tool_calls: ToolCallRecord[]; // tools the model called for this answer, in call order
}
/** One tool call the chat model made (list_books, check_platform_fit, draft_social_post), with its result. */
export interface ToolCallRecord {
  name: string;
  arguments: Record<string, unknown>; // as the model wrote them
  ok: boolean;
  result: unknown; // the tool's JSON result, or the error message
  duration_ms: number;
}
/** One question and answer inside a conversation. */
export interface ChatTurn extends AskResponse { created_at: string }
/** An "Ask your book" chat with all its turns, oldest first. */
export interface Conversation { id: string; title: string; created_at: string; updated_at: string; turns: ChatTurn[] }
/** A conversation without its turns, for the list of past chats. */
export interface ConversationInfo { id: string; title: string; created_at: string; updated_at: string; turn_count: number }

/** One tool of an MCP server (GET /mcp-servers). */
export interface McpTool {
  name: string;
  title: string | null;
  description: string;
  input_schema: JsonSchema; // arguments; the console builds its form from it
  read_only: boolean | null;
}
/** The parts of a JSON Schema the console understands. */
export interface JsonSchema {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: string[];
  items?: JsonSchema;
  anyOf?: JsonSchema[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  minimum?: number;
  maximum?: number;
}
/** An MCP server with its live status and tools (GET /mcp-servers). */
export interface McpServer {
  name: string;
  title: string | null;
  description: string | null;
  url: string;
  audience: "external" | "internal"; // external: for outside clients only; internal: the app uses it too
  status: "active" | "offline";
  error: string | null;
  latency_ms: number | null;
  instructions: string | null;
  tools: McpTool[];
}
/** One tool call from the console, with its result (POST /mcp-servers/{name}/call, GET /mcp-calls). */
export interface McpCall {
  id: string;
  server: string;
  tool: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  structured: unknown; // the tool's structured (JSON) result, if any
  text: string; // text content or error message
  duration_ms: number;
  called_at: string;
}

/** One logged model call with its tokens and costs in USD (server/app/core/usage.py). */
export interface UsageRecord {
  timestamp: string; // ISO 8601 (UTC)
  operation: string; // e.g. "ask/answer", "generate_blurb/generate", "embed_chunks"
  kind: "chat" | "embedding";
  model: string;
  input_tokens: number; // sent to the model
  output_tokens: number; // received from the model
  input_cost: number;
  output_cost: number;
  cost: number;
  cost_source: "provider" | "estimate"; // provider = exact cost reported by OpenRouter
  project_id: string | null;
  source_id: string | null;
}
/** Sums over a set of model calls (costs in USD). */
export interface UsageTotals { calls: number; input_tokens: number; output_tokens: number; input_cost: number; output_cost: number; cost: number }
/** Response of GET /usage: totals so far, per operation (highest cost first), and the latest calls (newest first). */
export interface UsageReport { totals: UsageTotals; by_operation: Record<string, UsageTotals>; recent: UsageRecord[] }

/** Short summary of one chapter of a book. */
export interface ChapterSummary { chapter: string | null; first_page: number | null; last_page: number | null; summary: string }
/** Summary of a whole book (map-reduce over its chapters): overview, key themes and chapter summaries. */
export interface BookSummary {
  source_id: string;
  summary: string; // what the book is about, about two paragraphs
  themes: string[];
  chapters: ChapterSummary[]; // content chapters in reading order
  model: string; // chat model that wrote it
  tokens: number; // LLM tokens used to create it
  created_at: string; // ISO 8601 timestamp (UTC)
}

/** Error from a non-2xx API response; `status` lets callers handle e.g. 404 specially. */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

/** Asset types with their display labels, in the order shown in select boxes. */
export const ASSET_TYPES: { value: AssetType; label: string }[] = [
  { value: "blurb", label: "Blurb / product description" },
  { value: "social_post", label: "Social post" },
  { value: "social_reply", label: "Reply to a post" },
  { value: "video_script", label: "Short video script (Reels · TikTok · Shorts)" },
  { value: "youtube_video", label: "YouTube video page (titles · description · tags)" },
  { value: "newsletter", label: "Newsletter" },
  { value: "ad_copy", label: "Ad copy" },
  { value: "lead_magnet", label: "Lead magnet" },
  { value: "persona", label: "Audience persona" },
];
/** Planned formats, shown disabled after ASSET_TYPES ("coming soon"); the server cannot generate them yet. */
export const PLANNED_ASSET_TYPES: { value: string; label: string; disabled: true }[] = [
  { value: "carousel", label: "Carousel post – swipeable slides (coming soon)", disabled: true },
  { value: "carousel_ad", label: "Carousel ad – paid, cards with links (coming soon)", disabled: true },
  { value: "slides_gif", label: "GIF from slides (coming soon)", disabled: true },
  { value: "slides_video", label: "Short video from slides – MP4 (coming soon)", disabled: true },
];

/**
 * Human-readable label of an asset type, e.g. "social_post" → "Social post".
 * @param type The asset type value.
 * @returns Its label from ASSET_TYPES, or the raw value if it is unknown.
 */
/** Tone options with display labels. */
export const TONES: { value: Tone; label: string }[] = [
  { value: "neutral", label: "Neutral" },
  { value: "inspiring", label: "Inspiring" },
  { value: "friendly", label: "Friendly" },
  { value: "professional", label: "Professional" },
  { value: "punchy", label: "Punchy" },
  { value: "literary", label: "Literary" },
];
/** Length options with display labels (sizes depend on the asset type, see server/generation.py). */
export const LENGTHS: { value: Length; label: string }[] = [
  { value: "short", label: "Short" },
  { value: "standard", label: "Standard" },
  { value: "long", label: "Long" },
];
/** Social platforms with display labels and character limits of posts and replies. */
export const PLATFORMS: { value: Platform; label: string; postLimit: number; replyLimit: number }[] = [
  { value: "x", label: "X (Twitter)", postLimit: 280, replyLimit: 280 },
  { value: "linkedin", label: "LinkedIn", postLimit: 3000, replyLimit: 1250 },
  { value: "instagram", label: "Instagram", postLimit: 2200, replyLimit: 2200 },
  { value: "facebook", label: "Facebook", postLimit: 63206, replyLimit: 8000 },
  { value: "tiktok", label: "TikTok", postLimit: 4000, replyLimit: 150 },
  { value: "youtube", label: "YouTube", postLimit: 5000, replyLimit: 10000 },
];

/** True for asset types made for a platform (a platform is chosen instead of a length): posts, replies, video scripts. */
export function usesPlatform(type: AssetType) {
  return type === "social_post" || type === "social_reply" || type === "video_script";
}

/** True for asset types whose text is checked against the platform's character limit (posts and replies). */
export function hasCharLimit(type: AssetType) {
  return type === "social_post" || type === "social_reply";
}

/**
 * Publishable version of a generated text: the [n] citation markers removed, with no stray space left
 * before punctuation. Used for copying and for character counts.
 * @param text Generated text with markers.
 */
export function cleanText(text: string) {
  return text.replace(/[ \t]*\[\d+\]/g, "").replace(/[ \t]+([.,;:!?])/g, "$1").trim();
}

/**
 * Name of a "humanize" level (0-100), matching the style levels in server/generation.py.
 * @param value Humanize setting.
 */
export function humanizeLabel(value: number) {
  if (value < 25) return "Polished marketing";
  if (value < 50) return "Balanced";
  if (value < 75) return "Natural, human";
  return "Very human, casual";
}

/** Display label of an asset type, e.g. "social_post" → "Social post" (the type itself if unknown). */
export function assetTypeLabel(type: AssetType) {
  return ASSET_TYPES.find((t) => t.value === type)?.label ?? type;
}

/**
 * Short display text for a chunk location.
 * Media locations (start_time set) win; otherwise chapter and page are joined, skipping missing parts.
 * @param loc The chunk location.
 * @returns "ch_04 · p.112" for documents, "00:12:34–00:13:20" for media.
 */
/**
 * URL of a book's cover image (PNG, extracted from the PDF by the server on first request).
 * @param sourceId The book (source).
 */
export function coverUrl(sourceId: string) {
  return `${API_URL}/sources/${sourceId}/cover`;
}

/**
 * URL of a source's uploaded file (the PDF), opened in the browser's viewer; with a page, the viewer
 * jumps to it (#page=N is understood by the PDF viewers of Chrome, Edge, Firefox and Safari).
 * @param sourceId The source.
 * @param page Optional 1-based page to open at.
 */
export function fileUrl(sourceId: string, page?: number | null) {
  return `${API_URL}/sources/${sourceId}/file${page ? `#page=${page}` : ""}`;
}

/**
 * Readable book title from a file name, like the server's source_name:
 * "Garden-Cities-of-To-Morrow_Ebenezer-Howard.pdf" → "Garden Cities of To Morrow — Ebenezer Howard".
 * @param filename Stored file name of the source.
 */
export function bookTitle(filename: string) {
  return filename.replace(/\.[^.]+$/, "").replace(/_/g, " — ").replace(/-/g, " ").replace(/\s+/g, " ").trim();
}

/** Where a chunk is, for display: "CHAPTER IV. … · p.9" for books, "00:01:20–00:02:05" for media. */
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
 * @throws ApiError (non-2xx response, with its status) or Error (server unreachable), with a user-presentable message.
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
    throw new ApiError(typeof body?.detail === "string" ? body.detail : `API error ${res.status}`, res.status);
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
  /**
   * GET /usage: tokens and costs of all model calls so far.
   * @param limit Number of latest calls to include (default 50).
   */
  usage: (limit = 50) => request<UsageReport>(`/usage?limit=${limit}`),
  /** GET /projects/{id}: the current project with its counts. */
  getProject: () => request<Project>(`/projects/${PROJECT_ID}`),

  /** GET /projects/{id}/sources: all sources of the current project. */
  listSources: () => request<Source[]>(`/projects/${PROJECT_ID}/sources`),
  /** GET /sources/{sourceId}: one source, used to poll ingestion status. */
  getSource: (sourceId: string) => request<Source>(`/sources/${sourceId}`),
  /**
   * POST /projects/{id}/sources: upload a file as a new source; the server then processes it into chunks.
   * Multipart upload via XMLHttpRequest, because fetch() cannot report upload progress.
   * @param file The file to upload (sent as form field "file").
   * @param onProgress Optional callback receiving the sent percentage (0-100).
   * @returns The created Source (status "queued"); rejects with the server's error detail on failure.
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
  /**
   * POST /sources/{sourceId}/ingest: (re)build a source's chunks in the background (Process / Re-index / Retry).
   * @returns The source with status "queued"; poll it to follow the progress.
   */
  ingestSource: (sourceId: string) => request<Source>(`/sources/${sourceId}/ingest`, { method: "POST" }),
  /**
   * GET /sources/{sourceId}/summary: the saved book summary.
   * @returns The summary, or null if none has been created yet (404).
   */
  getSummary: async (sourceId: string): Promise<BookSummary | null> => {
    try {
      return await request<BookSummary>(`/sources/${sourceId}/summary`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }
  },
  /** POST /sources/{sourceId}/summary: create (or recreate) the book summary; takes some seconds. */
  createSummary: (sourceId: string) => request<BookSummary>(`/sources/${sourceId}/summary`, { method: "POST" }),
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
  /**
   * POST /projects/{id}/ask: answer a question from the books (NotebookLM-style), with citations, as a turn of a chat.
   * @param question Natural-language question (follow-ups like "and in chapter 3?" are fine inside a chat).
   * @param k Number of passages to retrieve as context (default 6).
   * @param sourceIds Optional: only use these books (omitted = all books).
   * @param conversationId Optional: continue this chat (omitted = start a new one; the response has its id).
   */
  ask: (question: string, k = 6, sourceIds?: string[], conversationId?: string) =>
    request<AskResponse>(`/projects/${PROJECT_ID}/ask`,
      postJson({ question, k, source_ids: sourceIds, conversation_id: conversationId })),
  /** GET /projects/{id}/conversations: past "Ask your book" chats without their turns, most recent first. */
  listConversations: () => request<ConversationInfo[]>(`/projects/${PROJECT_ID}/conversations`),
  /** GET /conversations/{id}: one chat with all its turns. */
  getConversation: (conversationId: string) => request<Conversation>(`/conversations/${conversationId}`),
  /** DELETE /conversations/{id}: delete a chat. */
  deleteConversation: (conversationId: string) => request<void>(`/conversations/${conversationId}`, { method: "DELETE" }),

  /** POST /projects/{id}/generate: generate and store a new asset from a brief. */
  generate: (body: GenerateRequest) => request<Asset>(`/projects/${PROJECT_ID}/generate`, postJson(body)),
  /** POST /projects/{id}/campaigns: generate a zero-shot campaign kit (3 personas, 5 posts, 1 blurb); takes some seconds. */
  createCampaign: (body: CampaignRequest) => request<CampaignResponse>(`/projects/${PROJECT_ID}/campaigns`, postJson(body)),
  /** GET /projects/{id}/assets: all generated assets of the current project, oldest first. */
  listAssets: () => request<Asset[]>(`/projects/${PROJECT_ID}/assets`),
  /** PATCH /assets/{assetId}: replace an asset's text with the user's edited version. */
  updateAsset: (assetId: string, text: string) =>
    request<Asset>(`/assets/${assetId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) }),
  /** DELETE /assets/{assetId}: delete a generated asset. */
  deleteAsset: (assetId: string) => request<void>(`/assets/${assetId}`, { method: "DELETE" }),

  /** GET /mcp-servers: our MCP servers with their live status and tools. */
  listMcpServers: () => request<McpServer[]>("/mcp-servers"),
  /**
   * POST /mcp-servers/{name}/call: run a tool over MCP; failures come back with ok=false, not as an error.
   * @param server Server name, e.g. "mcp-guardrails".
   * @param tool Tool name.
   * @param args The tool's arguments.
   */
  callMcpTool: (server: string, tool: string, args: Record<string, unknown>) =>
    request<McpCall>(`/mcp-servers/${server}/call`, postJson({ tool, arguments: args })),
  /** GET /mcp-calls: the most recent console calls, newest first. */
  listMcpCalls: () => request<McpCall[]>("/mcp-calls"),

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
