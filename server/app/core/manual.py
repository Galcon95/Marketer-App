"""The user manual (server/help/manual.md): one Markdown file, the single source for the Help page in the app (GET
/help/manual) and, later, for "Ask the app".

Format: "# Title", then "## Section" and "### Subsection" headings; each heading's anchor is its slug (anchor()),
the same rule the client uses, so a link like /help#connect-your-youtube-channel opens that section.
Update the manual whenever a screen changes (AGENTS.md).
"""

import re
from pathlib import Path

MANUAL_PATH = Path(__file__).resolve().parents[2] / "help" / "manual.md"  # server/help/manual.md


def text() -> str:
    """The manual as Markdown (read on every call: it is small, and an edit shows without a restart).

    Raises:
        OSError: If the file is missing.
    """
    return MANUAL_PATH.read_text(encoding="utf-8")


def anchor(heading: str) -> str:
    """A heading's anchor: lower case, letters and digits joined by "-" ("Connect your YouTube channel" →
    "connect-your-youtube-channel")."""
    return "-".join(re.findall(r"[a-z0-9]+", heading.lower()))


def sections(markdown: str | None = None) -> list[tuple[int, str, str]]:
    """The manual's headings below the title: (level 2 or 3, heading, anchor), in order."""
    found = re.findall(r"^(#{2,3}) +(.+?) *$", text() if markdown is None else markdown, re.MULTILINE)
    return [(len(hashes), heading, anchor(heading)) for hashes, heading in found]
