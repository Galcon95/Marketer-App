"use client";

/**
 * The "Facebook Page" page (sidebar, Integrations): connect the user's own Facebook Page with Facebook Login, choose
 * one when they manage several, see which Page is connected, disconnect it. With a Page, the user can publish posts
 * from the Content Studio and answer comments in Community → Facebook Page. The token stays on the server, encrypted.
 *
 * Facebook Login sends the browser back to the app with ?facebook=connected|choose|cancelled|error (AppShell opens
 * this page then and passes the result here); the query is removed from the address bar afterwards.
 */

import { useState } from "react";
import { Check, CircleHelp, ExternalLink, LogIn, ThumbsUp, Unplug } from "lucide-react";
import { api, errorMessage, type FacebookStatus } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import FacebookSetupGuide from "./FacebookSetupGuide";
import { Badge, Button, Card, ErrorNote, Placeholder } from "./ui";

/** What came back from Facebook Login (the ?facebook= query), shown once. */
export type LoginResult = { result: string; message: string } | null;

/** Messages for the results of Facebook Login. */
const RESULTS: Record<string, string> = {
  connected: "Your Facebook Page is connected.",
  choose: "You manage several Pages: choose the one for your book.",
  cancelled: "Facebook Login was cancelled; nothing was connected.",
};

/**
 * The page.
 * @param login The result of a Facebook Login that just sent the user back (null = none).
 * @param onChange Called after connecting or disconnecting, to refresh the app.
 */
export default function FacebookConnection({ login, onChange }: { login: LoginResult; onChange: () => void }) {
  const [nonce, setNonce] = useState(0);
  const status = useApi(`facebook-status:${nonce}`, api.facebookStatus);
  const choices = useApi(login?.result === "choose" ? `facebook-pages:${nonce}` : null, api.facebookPagesToChoose);
  const [pending, setPending] = useState<string | null>(null); // what is running: "connect", "disconnect" or a Page id
  const [error, setError] = useState<string | null>(login?.result === "error" ? login.message || "Facebook Login failed." : null);
  const [showGuide, setShowGuide] = useState(false); // the setup guide, opened by a button
  const [note, setNote] = useState<string | null>(login ? RESULTS[login.result] ?? null : null);

  /** After a change: reload the status here and refresh the app. */
  function changed() {
    setNonce((n) => n + 1);
    onChange();
  }

  /** Start Facebook Login: the browser goes to Facebook and comes back to this app. */
  async function connect() {
    setPending("connect");
    setError(null);
    try {
      const { url } = await api.facebookConnect(window.location.origin);
      window.location.assign(url);
    } catch (e) {
      setError(errorMessage(e));
      setPending(null);
    }
  }

  /** Connect one of several Pages found by the login. */
  async function choose(pageId: string) {
    setPending(pageId);
    setError(null);
    try {
      await api.facebookChoosePage(pageId);
      setNote(RESULTS.connected);
      changed();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setPending(null);
    }
  }

  /** Forget the Page (after a confirmation). */
  async function disconnect() {
    if (!window.confirm("Disconnect your Facebook Page? The app can no longer read or post on it until you connect it again.")) return;
    setPending("disconnect");
    setError(null);
    try {
      await api.facebookDisconnect();
      setNote(null);
      changed();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setPending(null);
    }
  }

  const s: FacebookStatus | undefined = status.data;
  const waiting = (choices.data ?? []).length > 0 && s?.source !== "user";

  return (
    <div className="bc-stack" style={{ maxWidth: 720 }}>
      <Card title="Your Facebook Page" icon={ThumbsUp}
        meta={s && (s.connected ? <Badge tone="success">connected</Badge> : <Badge>not connected</Badge>)}>
        <div className="bc-stack">
          <span className="bc-hint">
            Connect the Facebook Page of your book: the app can then publish posts you wrote in the Content Studio
            and answer readers&apos; comments in <strong>Community → Facebook Page</strong>. Nothing is posted without your
            click. The access stays on the server, encrypted; you can disconnect at any time.
          </span>
          {note && <span className="bc-hint" style={{ color: "var(--accent-text)" }}><Check size={14} aria-hidden /> {note}</span>}
          {status.error && <ErrorNote>{status.error}</ErrorNote>}
          {!s ? (
            <Placeholder icon={ThumbsUp}>{status.loading ? "Checking…" : "Status unknown."}</Placeholder>
          ) : (
            <>
              {s.page && (
                <div className="bc-row" style={{ gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                  <strong>{s.page.name}</strong>
                  {s.page.followers != null && <span className="bc-hint" style={{ margin: 0 }}>{s.page.followers.toLocaleString()} followers</span>}
                  {s.page.link && (
                    <a href={s.page.link} target="_blank" rel="noopener noreferrer" className="bc-hint" style={{ margin: 0 }}>
                      open on Facebook <ExternalLink size={12} aria-hidden />
                    </a>
                  )}
                </div>
              )}
              {s.source === "server" && (
                <span className="bc-hint">
                  This is the Page set in the server&apos;s configuration (server/.env, admin only). Connecting a Page
                  here replaces it for you.
                </span>
              )}
              {s.error && <ErrorNote>{s.error}</ErrorNote>}
              {waiting && (
                <div className="bc-stack" style={{ gap: 8 }}>
                  <strong>Which Page is for your book?</strong>
                  {choices.data!.map((p) => (
                    <div key={p.id} className="bc-row" style={{ gap: 8, alignItems: "center" }}>
                      <span style={{ flex: 1 }}>{p.name || p.id}</span>
                      <Button size="sm" loading={pending === p.id} disabled={pending !== null} onClick={() => choose(p.id)}>
                        Connect this Page
                      </Button>
                    </div>
                  ))}
                </div>
              )}
              <div className="bc-studio-actions">
                {s.source === "user" && (
                  <Button variant="ghost" icon={Unplug} loading={pending === "disconnect"} disabled={pending !== null}
                    onClick={disconnect}>Disconnect</Button>
                )}
                <Button icon={LogIn} loading={pending === "connect"} disabled={pending !== null || !s.login_available}
                  onClick={connect}>
                  {s.source === "user" ? "Connect another Page" : "Connect with Facebook"}
                </Button>
              </div>
              {!s.login_available && (
                <span className="bc-hint">
                  Facebook Login is not set up on this server yet (FACEBOOK_APP_ID, FACEBOOK_APP_SECRET and
                  TOKEN_ENCRYPTION_KEY in server/.env).
                </span>
              )}
            </>
          )}
          {error && <ErrorNote>{error}</ErrorNote>}
        </div>
      </Card>
      {s && s.source !== "user" && (
        <div>
          <Button size="sm" variant={showGuide ? "secondary" : "ghost"} icon={CircleHelp} aria-expanded={showGuide}
            onClick={() => setShowGuide((v) => !v)}>
            {showGuide ? "Hide the guide" : "How to connect your Page"}
          </Button>
        </div>
      )}
      {showGuide && s && s.source !== "user" && <Card><FacebookSetupGuide here /></Card>}
    </div>
  );
}
