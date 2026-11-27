"use client";

/**
 * "Ask the app" (top bar): a small chat that answers questions about using the app from the manual (POST /help/ask,
 * server/help/manual.md). It knows the screen the user has open. The chat lives only in this drawer: it is kept
 * while the drawer is closed and opened again, but not saved. Each answer links the manual's sections it used.
 */

import { useEffect, useRef, useState, type SubmitEvent } from "react";
import { BookOpen, MessageCircleQuestion, Send } from "lucide-react";
import { api, errorMessage, type HelpResponse } from "@/lib/api";
import Markdown from "./Markdown";
import { Button, Drawer, ErrorNote } from "./ui";

/** One question and its answer (or the error it got). */
export type AppChatTurn = { question: string; answer?: HelpResponse; error?: string };

const EXAMPLES = ["How do I upload my book?", "How do I connect my Facebook Page?", "What is this page for?"];

/**
 * @param page The view the user has open (AppShell's view id), so "what is this page for?" works.
 * @param turns The chat so far (owned by AppShell, so it survives closing the drawer).
 * @param setTurns Change the chat.
 * @param onClose Close the drawer.
 * @param onAnswer Called after each answer (to refresh the usage totals).
 */
export default function AskAppDrawer({ page, turns, setTurns, onClose, onAnswer }: {
  page: string; turns: AppChatTurn[]; setTurns: (t: AppChatTurn[]) => void; onClose: () => void; onAnswer: () => void;
}) {
  const [pending, setPending] = useState(false);
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [turns, pending]);

  /** Send a question with the earlier answered turns; the answer (or the error) is added to the chat. */
  async function ask(question: string) {
    const q = question.trim();
    if (!q || pending) return;
    const history = turns.filter((t) => t.answer).map((t) => ({ question: t.question, answer: t.answer!.answer }));
    setPending(true);
    setDraft("");
    try {
      setTurns([...turns, { question: q, answer: await api.askApp(q, page, history) }]);
      onAnswer();
    } catch (err) {
      setTurns([...turns, { question: q, error: errorMessage(err) }]);
      setDraft(q); // so it can be sent again
    } finally {
      setPending(false);
    }
  }

  function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    void ask(draft);
  }

  return (
    <Drawer icon={MessageCircleQuestion} title="Ask the app" label="Ask how to use the app" onClose={onClose}
      meta={turns.length > 0 ? <Button variant="ghost" size="sm" onClick={() => setTurns([])}>New chat</Button> : undefined}>
      <div className="bc-stack ask-app">
        {turns.length === 0 && (
          <div className="bc-stack" style={{ gap: 8 }}>
            <span className="bc-hint">
              Ask how to do anything in the app. The answers come from the{" "}
              <a href="/help" target="_blank" rel="noreferrer">manual</a> and are written by AI: if something does not
              match what you see, the manual is right.
            </span>
            <div className="bc-row" style={{ gap: 6 }}>
              {EXAMPLES.map((e) => <Button key={e} variant="secondary" size="sm" onClick={() => void ask(e)}>{e}</Button>)}
            </div>
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className="bc-stack ask-app-turn">
            <p className="ask-app-q">{t.question}</p>
            {t.error && <ErrorNote>{t.error}</ErrorNote>}
            {t.answer && (
              <div className="ask-app-a">
                <Markdown text={t.answer.answer} newTab />
                {t.answer.sections.length > 0 && (
                  <div className="ask-app-more">
                    <BookOpen size={14} aria-hidden />
                    <span>Read more:</span>
                    {t.answer.sections.map((s) => (
                      <a key={s.anchor} href={`/help#${s.anchor}`} target="_blank" rel="noreferrer">{s.title}</a>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {pending && <p className="bc-hint">Looking it up in the manual…</p>}
        <div ref={endRef} />
        <form className="ask-app-form" onSubmit={submit}>
          <textarea className="bc-input" rows={2} maxLength={1000} value={draft} placeholder="e.g. How do I make an ad picture?"
            aria-label="Your question about the app" onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void ask(draft); } }} />
          <Button type="submit" icon={Send} loading={pending} disabled={!draft.trim()}>Ask</Button>
        </form>
      </div>
    </Drawer>
  );
}
