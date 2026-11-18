"use client";

/**
 * The "Automation" page (sidebar, Integrations): when the marketing agent looks at the Facebook Page and the YouTube
 * channel on its own and proposes replies in Telegram. Manual (only /next in Telegram or "Run now" here), or
 * scheduled: at times of day or every few hours, on chosen days, in the user's time zone. Nothing is posted without
 * the author's "Make it so" in Telegram.
 */

import { useMemo, useState } from "react";
import { Bot, Check, Clock, Play, Plus, Save, X } from "lucide-react";
import { api, errorMessage, type AutomationSchedule, type AutomationStatus } from "@/lib/api";
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

/** The page. */
export default function AutomationSettings() {
  const [nonce, setNonce] = useState(0);
  const status = useApi(`automation:${nonce}`, api.automationStatus);
  const [edited, setEdited] = useState<AutomationSchedule | null>(null); // the form, once the user changed it
  const [saved, setSaved] = useState<AutomationStatus | null>(null); // the answer of the last save
  const [pending, setPending] = useState<"save" | "run" | null>(null);
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
        meta={s && (s.active ? <Badge tone="success">running</Badge> : <Badge>not running</Badge>)}>
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
                </>
              )}

              <div className="bc-row" style={{ gap: 16 }}>
                <span className="bc-hint" style={{ margin: 0 }}><strong>Next run:</strong> {s.schedule.mode === "scheduled" ? when(s.next_run, zone) : "only when you ask"}</span>
                <span className="bc-hint" style={{ margin: 0 }}><strong>Last run:</strong> {when(s.last_run, zone)}</span>
                {!s.saved && <span className="bc-hint" style={{ margin: 0 }}>(not saved yet: the server default)</span>}
              </div>

              <div className="bc-studio-actions">
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
      <Card title="In Telegram" icon={Bot}>
        <span className="bc-hint">
          /next – look now · /status – the schedule and the next run · under a proposal: ✅ Make it so, Skip, or write
          what to change. A proposal waits until you answer it.
        </span>
      </Card>
    </div>
  );
}
