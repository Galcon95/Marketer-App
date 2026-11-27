/**
 * The small line under every page (login and app): the app is a beta student project, its texts are written by AI and
 * can be wrong, and a link to the privacy notice (/privacy). The EU AI Act asks that people know when they deal with
 * AI-generated content; the privacy notice is what GDPR asks for.
 */

import Link from "next/link";

export default function LegalFooter() {
  return (
    <footer className="legal-footer">
      <span>Beta · a student project (Turing College capstone)</span>
      <span>Answers, drafts and pictures are made by AI and can be wrong: check them before you use them.</span>
      <Link href="/privacy">Privacy</Link>
    </footer>
  );
}
