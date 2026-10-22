"""Social platform rules as numbers, and check_platform_fit: does a text work as a post on a platform?

    PLATFORM_RULES   hard character limit (from the platform), plus the app's recommendations: words,
                     hashtags and how many characters show before "more" (the preview)
    check_platform_fit  counts characters, words and hashtags of a text (without [n] citation markers),
                     compares them with the rules and lists the issues; also flags AI clichés (style.py)

Pure Python, no model call. The recommendations match the platform rules the generators write by
(style.PLATFORM_POST); the hard limits match PLATFORMS in the client (lib/api.ts). Used as a tool of the
"Ask your book" chat (rag/chat_tools.py).
"""

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.core.schemas import Platform
from app.core.style import find_ai_tells


@dataclass(frozen=True)
class PlatformRules:
    """Limits and recommendations of one platform for a post."""

    label: str
    max_chars: int  # the platform's hard limit
    words: tuple[int, int] | None  # recommended word range; None = only the character limit matters
    max_recommended_chars: int | None  # recommended maximum length in characters (short-form platforms)
    hashtags: tuple[int, int]  # recommended number of hashtags
    preview_chars: int | None  # about how many characters show before "more"; None = whole text shows


PLATFORM_RULES: dict[Platform, PlatformRules] = {
    "x": PlatformRules("X (Twitter)", 280, None, None, (1, 2), None),
    "linkedin": PlatformRules("LinkedIn", 3000, (80, 200), None, (3, 5), 210),
    "instagram": PlatformRules("Instagram", 2200, None, None, (5, 10), 125),
    "facebook": PlatformRules("Facebook", 63206, (40, 120), None, (0, 2), None),
    "tiktok": PlatformRules("TikTok", 4000, None, 150, (3, 5), None),
    "youtube": PlatformRules("YouTube community post", 5000, (30, 100), None, (0, 3), None),
}


class PlatformFit(BaseModel):
    """Result of check_platform_fit."""

    platform: Platform
    fits: bool = Field(description="True if the text is within the platform's hard character limit.")
    characters: int
    max_characters: int
    words: int
    recommended_words: str = Field(description="e.g. '80-200', or '' if the platform has no word recommendation.")
    hashtags: int
    recommended_hashtags: str = Field(description="e.g. '3-5'.")
    preview: str = Field(description="The part readers see before 'more'; the whole text if it all shows.")
    issues: list[str] = Field(description="What to fix: problems first, then suggestions. Empty if all is fine.")


def check_platform_fit(text: str, platform: Platform) -> PlatformFit:
    """Check a post against a platform's rules: hard character limit (problem), recommended words, length and
    hashtags, whether the first sentence fits in the preview, and AI clichés (suggestions)."""
    rules = PLATFORM_RULES[platform]
    clean = _publishable(text)
    chars, words = len(clean), len(re.findall(r"\b\w[\w'’-]*\b", clean))
    hashtags = len(re.findall(r"(?<!\w)#\w+", clean))
    issues: list[str] = []
    if chars > rules.max_chars:
        issues.append(f"Too long for {rules.label}: {chars} characters, the limit is {rules.max_chars}.")
    if rules.max_recommended_chars and rules.max_recommended_chars < chars <= rules.max_chars:
        issues.append(f"Longer than recommended: {chars} characters, best at most {rules.max_recommended_chars}.")
    if rules.words and not rules.words[0] <= words <= rules.words[1]:
        issues.append(f"{words} words; {rules.label} posts work best with {rules.words[0]}-{rules.words[1]}.")
    if not rules.hashtags[0] <= hashtags <= rules.hashtags[1]:
        issues.append(f"{hashtags} hashtags; recommended for {rules.label}: {rules.hashtags[0]}-{rules.hashtags[1]}.")
    preview = clean if rules.preview_chars is None or chars <= rules.preview_chars else clean[:rules.preview_chars] + "…"
    first_sentence = re.split(r"(?<=[.!?])\s|\n", clean, maxsplit=1)[0]
    if rules.preview_chars and len(first_sentence) > rules.preview_chars:
        issues.append(f"The first sentence is cut off in the preview (about {rules.preview_chars} characters show "
                      "before 'more'); put the hook first and keep it short.")
    if tells := find_ai_tells(clean, emojis_expected=platform in ("instagram", "tiktok")):
        issues.append("Sounds AI-written: " + ", ".join(tells) + ".")
    return PlatformFit(
        platform=platform, fits=chars <= rules.max_chars, characters=chars, max_characters=rules.max_chars,
        words=words, recommended_words="-".join(map(str, rules.words)) if rules.words else "",
        hashtags=hashtags, recommended_hashtags="-".join(map(str, rules.hashtags)), preview=preview, issues=issues,
    )


def _publishable(text: str) -> str:
    """The text as it would be posted: [n] citation markers removed (no space left before punctuation), ends stripped."""
    text = re.sub(r"\s*\[\d+\]", "", text)
    return re.sub(r"[ \t]+([.,;:!?])", r"\1", text).strip()
