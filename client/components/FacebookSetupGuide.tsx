/**
 * Step-by-step guide: how a user attaches their own Facebook Page to the app. Shown in Community → Facebook Page
 * while no Page is connected, and on the "Facebook Page" page (sidebar, Integrations). Static text, no API calls.
 * The permissions listed match SCOPES in server/app/social/page_connections.py.
 */

import { ExternalLink } from "lucide-react";

/** A link that opens on Facebook / Meta in a new tab. */
function Out({ href, children }: { href: string; children: string }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children} <ExternalLink size={12} aria-hidden />
    </a>
  );
}

/**
 * The guide.
 * @param here True on the "Facebook Page" page itself (step 3 then says "below" instead of pointing to the sidebar).
 */
export default function FacebookSetupGuide({ here = false }: { here?: boolean }) {
  return (
    <div className="bc-stack" style={{ gap: 8 }}>
      <strong>How to connect your Facebook Page</strong>
      <ol className="bc-hint" style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 6 }}>
        <li>
          <strong>Have a Page for your book.</strong> It must be a Facebook <em>Page</em> (not your personal profile
          or a group), and your Facebook account must manage it with full control. No Page yet?{" "}
          <Out href="https://www.facebook.com/pages/create">Create one</Out>.
        </li>
        <li>
          <strong>Get access to the app on Facebook&apos;s side.</strong> While the app is in development mode, only
          testers can connect: ask the app owner to add your Facebook account as a tester, then accept the
          invitation under <Out href="https://developers.facebook.com/requests">developers.facebook.com/requests</Out>.
        </li>
        <li>
          {here
            ? <>Click <strong>Connect with Facebook</strong> above.</>
            : <>In the sidebar, open <strong>Integrations → Facebook Page</strong> and click <strong>Connect with Facebook</strong>.</>}
        </li>
        <li>
          <strong>Log in to Facebook and allow access.</strong> Select your book&apos;s Page and keep all
          permissions switched on: list your Pages, read posts and comments, publish posts, and reply to comments.
          If one is switched off, publishing or reading comments will fail.
        </li>
        <li>
          <strong>Back in the app:</strong> if you manage several Pages, choose the one for your book. The Page then
          shows as <em>connected</em>.
        </li>
        <li>
          Open <strong>Community → Facebook Page</strong> (click <strong>Check again</strong> if it was already open):
          write posts from your book and answer readers&apos; comments. Nothing is posted without your click.
        </li>
      </ol>
      <span className="bc-hint">
        To revoke access later: <strong>Disconnect</strong> on the Facebook Page screen, or remove the app in Facebook
        under Settings → Business integrations.
      </span>
    </div>
  );
}
