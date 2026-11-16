"""Export of generated assets as a file (GET /projects/{id}/assets/export): CSV for spreadsheets and scheduling tools,
Markdown for reading and editing.

    to_csv       one row per asset; the text as it is posted (citation markers removed), the cited passages in a
                 "sources" column. delimiter "," (Google Sheets, Buffer, ...) or ";" (Excel with a German or other
                 locale that uses the comma as decimal separator). Starts with a BOM so Excel reads UTF-8.
    to_markdown  one section per asset, newest first: heading, details line, the text with its [n] markers and
                 the list of cited passages below it.
"""

import csv
import io
from datetime import datetime

from app.core.schemas import Asset, Citation
from app.rag.retrieval import source_name
from app.social.facebook import publishable_text

# Readable names of the asset types (like ASSET_TYPES in the client's lib/api.ts).
TYPE_LABELS = {
    "blurb": "Blurb", "social_post": "Social post", "social_reply": "Reply to a post", "video_script": "Short video script",
    "youtube_video": "YouTube video page", "newsletter": "Newsletter", "ad_copy": "Ad copy", "lead_magnet": "Lead magnet",
    "persona": "Audience persona", "reader_question": "Question for my readers",
}

# Readable platform names (like PLATFORMS in the client).
PLATFORM_LABELS = {"x": "X", "linkedin": "LinkedIn", "instagram": "Instagram", "facebook": "Facebook",
                   "tiktok": "TikTok", "youtube": "YouTube"}

CSV_COLUMNS = ["created", "type", "book", "platform", "campaign", "persona", "audience", "tone", "brief", "text",
               "words", "characters", "sources", "id"]


def to_csv(assets: list[Asset], delimiter: str = ",") -> str:
    """The assets as CSV text (with a BOM), one row per asset in the given order."""
    out = io.StringIO()
    out.write("﻿")  # BOM
    writer = csv.writer(out, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for a in assets:
        text = publishable_text(a.text)
        writer.writerow([
            _when(a.created_at), TYPE_LABELS.get(a.asset_type, a.asset_type), _books(a), PLATFORM_LABELS.get(a.platform or "", ""),
            a.campaign_id, a.persona, a.audience, a.tone, a.brief, text, len(text.split()), len(text),
            "; ".join(_citation(n, c) for n, c in enumerate(a.citations, start=1)), a.id,
        ])
    return out.getvalue()


def to_markdown(assets: list[Asset], title: str) -> str:
    """The assets as one Markdown document: a title, then one section per asset in the given order."""
    parts = [f"# {title}", f"{len(assets)} asset{'s' if len(assets) != 1 else ''}, exported {_when(datetime.now())}."]
    for a in assets:
        details = [_when(a.created_at), _books(a), PLATFORM_LABELS.get(a.platform or "", ""), a.persona and f"for {a.persona}",
                   a.audience and f"audience: {a.audience}", "zero-shot" if not a.grounded else ""]
        parts.append(f"## {TYPE_LABELS.get(a.asset_type, a.asset_type)}\n\n*{' · '.join(d for d in details if d)}*")
        if a.brief:
            parts.append(f"**Brief:** {a.brief.strip()}")
        parts.append(a.text.strip())
        if a.citations:
            parts.append("**Sources:**\n\n" + "\n".join(f"- {_citation(n, c)}" for n, c in enumerate(a.citations, start=1)))
    return "\n\n".join(parts) + "\n"


def _when(moment: datetime) -> str:
    """Date and time to the minute, e.g. "2026-11-16 13:25"."""
    return moment.strftime("%Y-%m-%d %H:%M")


def _books(asset: Asset) -> str:
    """The book(s) the asset was made for, by readable name; "All books" when it was made for all of them."""
    return ", ".join(source_name(s) or s for s in asset.source_ids) or "All books"


def _citation(number: int, c: Citation) -> str:
    """One cited passage, e.g. '[1] Garden Cities — Ebenezer Howard, Chapter 2, p. 14'."""
    where = [c.location.chapter, c.location.page is not None and f"p. {c.location.page}"]
    return ", ".join([f"[{number}] {source_name(c.source_id) or c.source_id}", *(w for w in where if w)])
