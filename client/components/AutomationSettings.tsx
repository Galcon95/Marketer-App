"use client";

/**
 * Phase 4 · Agent Workspace: the marketing agent, which looks at the Facebook Page and the YouTube channel and proposes
 * replies in Telegram; its schedule and its recent cycles. Manual (only /next in Telegram or "Run now" here), or
 * scheduled: at times of day or every few hours, on chosen days, in the user's time zone. Nothing is posted without
 * the author's "Make it so" in Telegram.
 */

import { useMemo, useState } from "react";
import { Bot, Check, Clock, ExternalLink, History, Pause, Play, Plus, RefreshCw, Save, X } from "lucide-react";
import {
  api, errorMessage, type AutomationCycle, type AutomationSchedule, type AutomationStatus, type CycleOutcome,
} from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Badge, Button, Card, ErrorNote, Placeholder } from "./ui";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
/** Interval choices in minutes. */
const EVERY = [30, 60, 120, 180, 240, 360, 480, 720];

/** The browser's time zone, e.g. "Europe/Berlin" (the default for a schedule never saved). */
function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** All IANA time zones the browser knows (with the given one, in case it is missing). */
function zones(current: string): string[] {
  let all: string[] = [];
  try {
    all = Intl.supportedValuesOf("timeZone");
  } catch {
    all = [];
  }
  return all.includes(current) ? all : [current, ...all];
}

/** "every 3 h" / "every 30 min". */
function everyLabel(minutes: number): string {
  return minutes % 60 === 0 ? `every ${minutes / 60} h` : `every ${minutes} min`;
}

/** A time from the server, shown in the schedule's time zone. */
function when(iso: string | null, zone: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      timeZone: zone, weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return new Date(iso).toLocaleString();
  }
}

/** How each outcome is shown in the cycle list. */
const OUTCOMES: Record<CycleOutcome, { label: string; tone: "success" | "neutral" | "warning" | "danger" }> = {
  waiting: { label: "waiting", tone: "warning" },
  posted: { label: "posted", tone: "success" },
  skipped: { label: "skipped", tone: "neutral" },
  answered: { label: "answered elsewhere", tone: "neutral" },
  blocked: { label: "blocked by guard", tone: "danger" },
  failed: { label: "failed", tone: "danger" },
  gave_up: { label: "finish in app", tone: "warning" },
};
const TRIGGERS: Record<AutomationCycle["trigger"], string> = { schedule: "schedule", app: "Run now", telegram: "Telegram" };
const STATUSES: Record<AutomationCycle["status"], string> = {
  running: "running", done: "done", error: "error", interrupted: "interrupted (server restart)",
};

/** The latest cycles: when, what started them, what was proposed and decided. */
function RecentCycles({ refresh, zone }: { refresh: number; zone: string }) {
  const cycles = useApi(`automation-cycles:${refresh}`, () => api.automationCycles(20));
  return (
    <Card title="Recent cycles" icon={History} actions={
      <Button variant="success" size="sm" icon={RefreshCw} loading={cycles.loading} onClick={cycles.reload}>
        Refresh
      </Button>}>
      <div className="bc-stack">
        {cycles.error && <ErrorNote>{cycles.error}</ErrorNote>}
        {!cycles.data?.length ? (
          <Placeholder icon={History}>
            {cycles.loading ? "Loading…" : "No cycles yet. Scheduled looks that found nothing new are not listed."}
          </Placeholder>
        ) : cycles.data.map((c) => (
          <div key={c.id} className="bc-stack" style={{ gap: 6, borderTop: "1px solid var(--border)", paddingTop: 8 }}>
            <div className="bc-row" style={{ gap: 8 }}>
              <strong>{when(c.started_at, zone)}</strong>
              <span className="bc-hint" style={{ margin: 0 }}>via {TRIGGERS[c.trigger]}</span>
              <Badge tone={c.status === "done" ? "success" : c.status === "running" ? "warning" : c.status === "error" ? "danger" : "neutral"}>
                {STATUSES[c.status]}
              </Badge>
            </div>
            {c.note && <span className="bc-hint" style={{ margin: 0 }}>{c.note}</span>}
            {c.entries.map((e) => (
              <div key={e.thread_id} className="bc-row" style={{ gap: 8, alignItems: "baseline" }}>
                <Badge tone={OUTCOMES[e.outcome].tone}>{OUTCOMES[e.outcome].label}</Badge>
                <span className="bc-hint" style={{ margin: 0, flex: 1, minWidth: 200 }}>
                  {e.kind === "comment" ? "💡 Question under your post: "
                    : `${e.platform === "youtube" ? "▶️ " : ""}${e.author || "A reader"}: `}“{e.excerpt}”
                  {e.revisions > 0 && ` · rewritten ${e.revisions}×`}
                </span>
                {e.url && (
                  <a href={e.url} target="_blank" rel="noopener noreferrer" className="bc-hint" style={{ margin: 0 }}>
                    open <ExternalLink size={12} aria-hidden />
                  </a>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </Card>
  );
}

/** The page. */
export default function AutomationSettings() {
  const [nonce, setNonce] = useState(0);
  const status = useApi(`automation:${nonce}`, api.automationStatus);
  const [edited, setEdited] = useState<AutomationSchedule | null>(null); // the form, once the user changed it
  const [saved, setSaved] = useState<AutomationStatus | null>(null); // the answer of the last save
  const [pending, setPending] = useState<"save" | "run" | "pause" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const s: AutomationStatus | undefined = saved ?? status.data;
  // The form starts from the saved schedule; a schedule never saved gets the browser's time zone and 09:00.
  const draft: AutomationSchedule | null = edited ?? (s ? (s.saved ? s.schedule : {
    ...s.schedule, timezone: browserZone(), times: s.schedule.times.length ? s.schedule.times : ["09:00"],
  }) : null);

  const zoneList = useMemo(() => zones(draft?.timezone ?? "UTC"), [draft?.timezone]);

  /** Change part of the draft. */
  function edit(change: Partial<AutomationSchedule>) {
    if (draft) setEdited({ ...draft, ...change });
    setNote(null);
  }

  function setTime(index: number, value: string) {
    if (!draft) return;
    edit({ times: draft.times.map((t, i) => (i === index ? value : t)) });
  }

  function toggleDay(day: number) {
    if (!draft) return;
    const days = draft.days.includes(day) ? draft.days.filter((d) => d !== day) : [...draft.days, day].sort();
    edit({ days });
  }

  async function save() {
    if (!draft) return;
    setPending("save");
    setError(null);
    try {
      const answer = await api.automationSave({ ...draft, times: draft.times.filter(Boolean) });
      setSaved(answer);
      setEdited(null);
      setNote("Schedule saved.");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setPending(null);
    }
  }

  /** Pause the schedule or resume it (the schedule itself is kept). */
  async function togglePause() {
    if (!s) return;
    setPending("pause");
    setError(null);
    try {
      const answer = await api.automationPause(!s.paused);
      setSaved(answer);
      setNote(answer.paused ? "Paused: the agent runs only when you ask." : "Resumed.");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setPending(null);
    }
  }

  async function runNow() {
    setPending("run");
    setError(null);
    try {
      const { status: message } = await api.automationRun();
      setNote(message);
      window.setTimeout(() => { setSaved(null); setNonce((n) => n + 1); }, 30_000); // show the new "last run"
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setPending(null);
    }
  }

  const scheduled = draft?.mode === "scheduled";
  const useInterval = !!draft && draft.every_minutes > 0;
  const zone = s?.schedule.timezone ?? "UTC";

  return (
    <div className="bc-stack" style={{ maxWidth: 720 }}>
      <Card title="Marketing agent schedule" icon={Clock}
        meta={s && (!s.active ? <Badge>not running</Badge> : s.paused ? <Badge tone="warning">paused</Badge>
          : <Badge tone="success">running</Badge>)}>
        <div className="bc-stack">
          <span className="bc-hint">
            The agent looks at your Facebook Page and your YouTube channel, drafts replies to new comments from your
            books and sends them to you in Telegram. Nothing is posted until you answer “Make it so”. Choose when it
            looks on its own, or keep it manual and ask with /next in Telegram or “Run now” here.
          </span>
          {status.error && <ErrorNote>{status.error}</ErrorNote>}
          {!draft || !s ? (
            <Placeholder icon={Clock}>{status.loading ? "Loading…" : "Schedule unknown."}</Placeholder>
          ) : (
            <>
              {s.note && <span className="bc-hint" style={{ color: "var(--warning-text, var(--ink-muted))" }}>{s.note}</span>}

              <fieldset className="bc-seg-field">
                <legend className="bc-label">Mode</legend>
                <div className="bc-seg" role="radiogroup">
                  {(["scheduled", "manual"] as const).map((mode) => (
                    <label key={mode} className="bc-seg-opt">
                      <input type="radio" name="mode" checked={draft.mode === mode} onChange={() => edit({ mode })} />
                      <span>{mode === "scheduled" ? "On a schedule" : "Manual only"}</span>
                    </label>
                  ))}
                </div>
              </fieldset>

              {scheduled && (
                <>
                  <fieldset className="bc-seg-field">
                    <legend className="bc-label">When</legend>
                    <div className="bc-seg" role="radiogroup">
                      <label className="bc-seg-opt">
                        <input type="radio" name="kind" checked={!useInterval}
                          onChange={() => edit({ every_minutes: 0, times: draft.times.length ? draft.times : ["09:00"] })} />
                        <span>At times of day</span>
                      </label>
                      <label className="bc-seg-opt">
                        <input type="radio" name="kind" checked={useInterval} onChange={() => edit({ every_minutes: 180 })} />
                        <span>Every few hours</span>
                      </label>
                    </div>
                  </fieldset>

                  {useInterval ? (
                    <div className="bc-field">
                      <label className="bc-label" htmlFor="automation-every">Interval</label>
                      <select id="automation-every" className="bc-select" value={draft.every_minutes}
                        onChange={(e) => edit({ every_minutes: Number(e.target.value) })}>
                        {(EVERY.includes(draft.every_minutes) ? EVERY : [draft.every_minutes, ...EVERY]).map((m) => (
                          <option key={m} value={m}>{everyLabel(m)}</option>
                        ))}
                      </select>
                    </div>
                  ) : (
                    <div className="bc-field">
                      <span className="bc-label">Times of day</span>
                      <div className="bc-row">
                        {draft.times.map((t, i) => (
                          <span key={i} className="bc-row" style={{ gap: 4, flexWrap: "nowrap" }}>
                            <input type="time" className="bc-input" style={{ width: 120 }} value={t}
                              aria-label={`Time ${i + 1}`} onChange={(e) => setTime(i, e.target.value)} />
                            {draft.times.length > 1 && (
                              <Button variant="ghost" size="sm" icon={X} aria-label={`Remove ${t}`}
                                onClick={() => edit({ times: draft.times.filter((_, j) => j !== i) })} />
                            )}
                          </span>
                        ))}
                        {draft.times.length < 6 && (
                          <Button variant="ghost" size="sm" icon={Plus}
                            onClick={() => edit({ times: [...draft.times, "18:00"] })}>Add time</Button>
                        )}
                      </div>
                    </div>
                  )}

                  <fieldset className="bc-seg-field">
                    <legend className="bc-label">Days</legend>
                    <div className="bc-seg">
                      {DAYS.map((name, day) => (
                        <label key={day} className="bc-seg-opt">
                          <input type="checkbox" checked={draft.days.includes(day)} onChange={() => toggleDay(day)} />
                          <span>{name}</span>
                        </label>
                      ))}
                    </div>
                  </fieldset>

                  <div className="bc-field">
                    <label className="bc-label" htmlFor="automation-zone">Time zone</label>
                    <select id="automation-zone" className="bc-select" value={draft.timezone}
                      onChange={(e) => edit({ timezone: e.target.value })}>
                      {zoneList.map((z) => <option key={z} value={z}>{z}</option>)}
                    </select>
                  </div>

                  <div className="bc-field">
                    <label className="bc-label" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <input type="checkbox" checked={!!draft.quiet_from}
                        onChange={(e) => edit(e.target.checked ? { quiet_from: "22:00", quiet_to: "07:00" }
                          : { quiet_from: "", quiet_to: "" })} />
                      Quiet hours
                    </label>
                    {draft.quiet_from ? (
                      <div className="bc-row" style={{ gap: 8 }}>
                        <span className="bc-hint" style={{ margin: 0 }}>from</span>
                        <input type="time" className="bc-input" style={{ width: 120 }} value={draft.quiet_from}
                          aria-label="Quiet hours from" onChange={(e) => edit({ quiet_from: e.target.value })} />
                        <span className="bc-hint" style={{ margin: 0 }}>to</span>
                        <input type="time" className="bc-input" style={{ width: 120 }} value={draft.quiet_to}
                          aria-label="Quiet hours to" onChange={(e) => edit({ quiet_to: e.target.value })} />
                        <span className="bc-hint" style={{ margin: 0 }}>no scheduled runs; a run due then waits until they end</span>
                      </div>
                    ) : <span className="bc-hint">The schedule may run at any time of day.</span>}
                  </div>
                </>
              )}

              <fieldset className="bc-seg-field" style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }}>
                <legend className="bc-label">When there are no new comments</legend>
                <div className="bc-stack" style={{ gap: 8 }}>
                  <label className="bc-row" style={{ gap: 8, flexWrap: "nowrap" }}>
                    <input type="checkbox" checked={draft.engage} onChange={(e) => edit({ engage: e.target.checked })} />
                    <span>Propose a question under one of my recent posts that has no comments yet, to start a discussion</span>
                  </label>
                  {draft.engage && (
                    <div className="bc-row" style={{ gap: 16 }}>
                      <label className="bc-row" style={{ gap: 6 }}>
                        <span className="bc-hint" style={{ margin: 0 }}>Posts from the last</span>
                        <select className="bc-select" style={{ width: 90 }} value={draft.engage_days}
                          onChange={(e) => edit({ engage_days: Number(e.target.value) })}>
                          {[3, 7, 14, 30, 60].map((d) => <option key={d} value={d}>{d} days</option>)}
                        </select>
                      </label>
                      <label className="bc-row" style={{ gap: 6 }}>
                        <span className="bc-hint" style={{ margin: 0 }}>At most</span>
                        <select className="bc-select" style={{ width: 70 }} value={draft.daily_limit}
                          onChange={(e) => edit({ daily_limit: Number(e.target.value) })}>
                          {[0, 1, 2, 3, 5, 10].map((n) => <option key={n} value={n}>{n}</option>)}
                        </select>
                        <span className="bc-hint" style={{ margin: 0 }}>own comments or posts per day</span>
                      </label>
                    </div>
                  )}
                  <span className="bc-hint">Each post gets at most one such question. Replies to readers are not limited.</span>
                </div>
              </fieldset>

              <div className="bc-row" style={{ gap: 16 }}>
                <span className="bc-hint" style={{ margin: 0 }}><strong>Next run:</strong> {s.paused ? "paused" : s.schedule.mode === "scheduled" ? when(s.next_run, zone) : "only when you ask"}</span>
                <span className="bc-hint" style={{ margin: 0 }}><strong>Last run:</strong> {when(s.last_run, zone)}</span>
                {!s.saved && <span className="bc-hint" style={{ margin: 0 }}>(not saved yet: the server default)</span>}
              </div>

              <div className="bc-studio-actions">
                {s.schedule.mode === "scheduled" && (
                  <Button variant="ghost" icon={s.paused ? Play : Pause} loading={pending === "pause"}
                    disabled={pending !== null} onClick={togglePause}>{s.paused ? "Resume schedule" : "Pause schedule"}</Button>
                )}
                <Button variant="ghost" icon={Play} loading={pending === "run"} disabled={pending !== null || !s.active}
                  onClick={runNow}>Run now</Button>
                <Button icon={Save} loading={pending === "save"} disabled={pending !== null || (scheduled && draft.days.length === 0)}
                  onClick={save}>Save schedule</Button>
              </div>
              {note && <span className="bc-hint" style={{ color: "var(--accent-text)" }}><Check size={14} aria-hidden /> {note}</span>}
            </>
          )}
          {error && <ErrorNote>{error}</ErrorNote>}
        </div>
      </Card>
      <RecentCycles refresh={nonce} zone={zone} />
      <Card title="In Telegram" icon={Bot}>
        <span className="bc-hint">
          /next – run a cycle now · /status – the schedule and the running cycle · /pause, /resume – stop or restart
          the schedule · under a proposal: ✅ Make it so, Skip, or write what to change. A proposal waits until you
          answer it; the next one follows your answer, and the cycle ends with a summary.
        </span>
      </Card>
    </div>
  );
}
