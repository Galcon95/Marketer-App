"""How generated text should sound: platform rules, tones and the "how human" (humanize) setting.

Shared by single-asset generation (rag/generation.py) and the campaign kit (campaign/kit.py).

    PLATFORM_*     length and style rules per social platform (posts, replies, short videos)
    TONES          wording of the tone options
    HUMAN_LEVELS   style guidance per humanize level (0-100), added to the system prompt
    AI_TELLS       AI-typical phrases ("AI slop"): avoided in the prompt from humanize 50 on,
                   detected after generation (find_ai_tells) and rewritten from REWRITE_FROM on

Listing banned phrases verbatim can prime some models to use them. Measured for this app's model instead of assumed
(2026-10-29, gpt-4o-mini, 10 grounded LinkedIn post drafts per variant at humanize 75, before the rewrite step):
with the list 8/10 drafts had no AI tells (2 tells in total), with positive guidance only 2/10 (9 tells). So the
list stays; re-check it when the chat model changes (see style_guidance).
"""

import re


from app.core import prompt_files
from app.core.schemas import Platform, Tone

# Social posts and replies: the platform decides length and style.
PLATFORM_POST: dict[Platform, str] = prompt_files.table("platform_posts")
PLATFORM_REPLY: dict[Platform, str] = prompt_files.table("platform_replies")
# Short video scripts: where the video is published.
PLATFORM_VIDEO: dict[Platform, str] = prompt_files.table("platform_videos")
TONES: dict[Tone, str] = prompt_files.table("tones")  # prompts/tones.md; neutral = ""

# Style guidance per "humanize" level (lower bound → text added to the system prompt).
HUMAN_LEVELS: list[tuple[int, str]] = [(int(bound), text) for bound, text in
                                      prompt_files.table("style_levels").items()]

# Phrases and patterns that make text sound AI-generated ("AI slop"); avoided in the prompt from
# humanize 50 on, detected after generation, and rewritten from humanize 60 on.
AI_TELLS: list[str] = [
    "imagine a world", "in today's fast-paced world", "in a world where", "dive into", "delve into", "unlock",
    "unleash", "embark on", "journey", "game-changer", "game changer", "revolutionary", "transformative",
    "groundbreaking", "join the movement", "are you ready", "ready to explore", "look no further",
    "harmonious", "vibrant", "tapestry", "elevate", "embrace", "testament to", "a must-read", "timeless",
    "discover how", "the future is", "let's dive", "buckle up", "not just", "seamlessly", "synergy",
]
REWRITE_FROM = 60  # humanize level from which found AI clichés are rewritten (one extra model call)

REWRITE_PROMPT = prompt_files.chat_prompt("style_rewrite")  # prompts/style_rewrite.md



def style_guidance(humanize: int) -> str:
    """Style guidance for a "humanize" level (0-100): the voice to aim for (HUMAN_LEVELS), plus from level 50 on the
    list of AI clichés to avoid. The list is kept because it measurably helps gpt-4o-mini (module docstring)."""
    guidance = next(text for bound, text in reversed(HUMAN_LEVELS) if humanize >= bound)
    if humanize >= 50:
        phrases = ", ".join(f'"{t}"' for t in AI_TELLS)
        guidance += " " + prompt_files.text("style_avoid_phrases").format(phrases=phrases)  # prompts/style_avoid_phrases.md
    return guidance


def find_ai_tells(text: str, emojis_expected: bool = False) -> list[str]:
    """AI-typical phrases and patterns in a text: listed clichés, many exclamation marks, emojis or em dashes.

    Args:
        text: The text to check.
        emojis_expected: Skip the emoji count for formats where emojis are normal (see emojis_are_normal).
    """
    lower = text.lower()
    found = [t for t in AI_TELLS if re.search(rf"\b{re.escape(t)}\b", lower)]
    if text.count("!") > 2:
        found.append("many exclamation marks")
    if not emojis_expected and len(re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", text)) > 3:
        found.append("many emojis")
    if text.count("—") > 2:
        found.append("many em dashes")
    return found


def temperature_for(humanize: int) -> float:
    """Model temperature for a humanize level: 0.5 (polished) to 1.0 (very human), in steps of 0.1."""
    return round(0.5 + 0.5 * humanize / 100, 1)
