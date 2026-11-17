"use client";

/**
 * The "YouTube channel" page (sidebar, Integrations): connect the user's own YouTube channel with Google sign-in, see
 * which channel is connected, disconnect it. With a channel, the user can answer comments under their videos in
 * Community. The access stays on the server, encrypted.
 *
 * Google sends the browser back to the app with ?youtube=connected|cancelled|error (AppShell opens this page then and
 * passes the result here); the query is removed from the address bar afterwards.
 */

import { useState } from "react";
import { Check, ExternalLink, LogIn, SquarePlay, Unplug } from "lucide-react";
import { api, errorMessage, type YouTubeStatus } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { LoginResult } from "./FacebookConnection";
import { Badge, Button, Card, ErrorNote, Placeholder } from "./ui";

/** Messages for the results of Google sign-in. */
const RESULTS: Record<string, string> = {
  connected: "Your YouTube channel is connected.",
  cancelled: "The Google sign-in was cancelled; nothing was connected.",
};

/**
 * The page.
 * @param login The result of a Google sign-in that just sent the user back (null = none).
 * @param onChange Called after connecting or disconnecting, to refresh the app.
 */
export default function YouTubeConnection({ login, onChange }: { login: LoginResult; onChange: () => void }) {
  const [nonce, setNonce] = useState(0);
  const status = useApi(`youtube-status:${nonce}`, api.youtubeStatus);
  const [pending, setPending] = useState<string | null>(null); // what is running: "connect" or "disconnect"
  const [error, setError] = useState<string | null>(login?.result === "error" ? login.message || "Google sign-in failed." : null);
  const [note, setNote] = useState<string | null>(login ? RESULTS[login.result] ?? null : null);

  /** Start Google sign-in: the browser goes to Google and comes back to this app. */
  async function connect() {
    setPending("connect");
    setError(null);
    try {
      const { url } = await api.youtubeConnect(window.location.origin);
      window.location.assign(url);
    } catch (e) {
      setError(errorMessage(e));
      setPending(null);
    }
  }

  /** Forget the channel (after a confirmation). */
  async function disconnect() {
    if (!window.confirm("Disconnect your YouTube channel? The app can no longer read or answer its comments until you connect it again.")) return;
    setPending("disconnect");
    setError(null);
    try {
      await api.youtubeDisconnect();
      setNote(null);
      setNonce((n) => n + 1);
      onChange();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setPending(null);
    }
  }

  const s: YouTubeStatus | undefined = status.data;
  // Connected, or saved but no longer accepted by Google (then the error says to connect again).
  const saved = !!s && (s.connected || !!s.error);

  return (
    <div className="bc-stack" style={{ maxWidth: 720 }}>
      <Card title="Your YouTube channel" icon={SquarePlay}
        meta={s && (s.connected ? <Badge tone="success">connected</Badge> : <Badge>not connected</Badge>)}>
        <div className="bc-stack">
          <span className="bc-hint">
            Connect the YouTube channel of your book with your Google account: the app can then read the comments under
            your videos and answer them as your channel. Nothing is posted without your click. The access stays on the
            server, encrypted; you can disconnect at any time.
          </span>
          {note && <span className="bc-hint" style={{ color: "var(--accent-text)" }}><Check size={14} aria-hidden /> {note}</span>}
          {status.error && <ErrorNote>{status.error}</ErrorNote>}
          {!s ? (
            <Placeholder icon={SquarePlay}>{status.loading ? "Checking…" : "Status unknown."}</Placeholder>
          ) : (
            <>
              {s.channel && (
                <div className="bc-row" style={{ gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                  <strong>{s.channel.name}</strong>
                  {s.channel.subscribers != null && <span className="bc-hint" style={{ margin: 0 }}>{s.channel.subscribers.toLocaleString()} subscribers</span>}
                  {s.channel.link && (
                    <a href={s.channel.link} target="_blank" rel="noopener noreferrer" className="bc-hint" style={{ margin: 0 }}>
                      open on YouTube <ExternalLink size={12} aria-hidden />
                    </a>
                  )}
                </div>
              )}
              {s.error && <ErrorNote>{s.error}</ErrorNote>}
              <div className="bc-studio-actions">
                {saved && (
                  <Button variant="ghost" icon={Unplug} loading={pending === "disconnect"} disabled={pending !== null}
                    onClick={disconnect}>Disconnect</Button>
                )}
                <Button icon={LogIn} loading={pending === "connect"} disabled={pending !== null || !s.login_available}
                  onClick={connect}>
                  {saved ? "Connect again / another channel" : "Connect with Google"}
                </Button>
              </div>
              {!s.connected && s.login_available && (
                <span className="bc-hint">
                  Google asks which account to use: pick the one that owns your channel (or its brand account) and allow
                  the app to see and manage your YouTube comments.
                </span>
              )}
              {!s.login_available && (
                <span className="bc-hint">
                  Google sign-in is not set up on this server yet (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and
                  TOKEN_ENCRYPTION_KEY in server/.env).
                </span>
              )}
            </>
          )}
          {error && <ErrorNote>{error}</ErrorNote>}
        </div>
      </Card>
    </div>
  );
}
