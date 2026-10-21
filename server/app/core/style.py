"""How generated text should sound: platform rules, tones and the "how human" (humanize) setting.

Shared by single-asset generation (rag/generation.py) and the campaign kit (campaign/kit.py).

    PLATFORM_*     length and style rules per social platform (posts, replies, short videos)
    TONES          wording of the tone options
    HUMAN_LEVELS   style guidance per humanize level (0-100), added to the system prompt
    AI_TELLS       AI-typical phrases ("AI slop"): avoided in the prompt from humanize 50 on,
                   detected after generation (find_ai_tells) and rewritten from REWRITE_FROM on
"""

import re

from langchain_core.prompts import ChatPromptTemplate

from app.core.schemas import Platform, Tone

# Social posts and replies: the platform decides length and style.
PLATFORM_POST: dict[Platform, str] = {
    "x": "for X (Twitter): at most 280 characters in total, a strong hook, 1-2 fitting hashtags",
    "linkedin": "for LinkedIn: 80-200 words, a strong first line, short paragraphs, professional and thoughtful, "
                "3-5 hashtags at the end",
    "instagram": "for Instagram: an engaging caption with line breaks and a few emojis, ending with 5-10 hashtags; "
                 "after the caption add one line starting with \"Image idea:\" that describes a fitting picture",
    "facebook": "for Facebook: conversational, 40-120 words, ending with a question that invites comments, "
                "0-2 hashtags",
    "tiktok": "as a TikTok caption: at most 150 characters, casual, a hook first, 3-5 hashtags",
    "youtube": "as a YouTube community post: 30-100 words, personal, ending with a question or a poll idea",
}
PLATFORM_REPLY: dict[Platform, str] = {
    "x": "on X (Twitter), at most 280 characters in total",
    "linkedin": "as a LinkedIn comment of 40-120 words, professional and constructive",
    "instagram": "as an Instagram comment of 1-3 short sentences, warm; an emoji is fine",
    "facebook": "as a Facebook comment of 30-100 words, conversational",
    "tiktok": "as a TikTok comment of at most 150 characters, casual",
    "youtube": "as a YouTube comment of 20-80 words, friendly and on topic",
}
# Short video scripts: where the video is published.
PLATFORM_VIDEO: dict[Platform, str] = {
    "x": "for X (Twitter) video",
    "linkedin": "for LinkedIn video (professional, subtitled because most people watch muted)",
    "instagram": "for Instagram Reels",
    "facebook": "for Facebook Reels",
    "tiktok": "for TikTok (fast cuts, trend-aware, casual)",
    "youtube": "for YouTube Shorts",
}
TONES: dict[Tone, str] = {
    "neutral": "",
    "inspiring": "inspiring and hopeful",
    "friendly": "warm and friendly",
    "professional": "professional and credible",
    "punchy": "punchy, bold and energetic",
    "literary": "elegant and literary",
}

# Style guidance per "humanize" level (lower bound → text added to the system prompt).
HUMAN_LEVELS: list[tuple[int, str]] = [
    (0, "Style: polished, persuasive marketing copy is fine."),
    (25, "Style: clear and engaging; avoid the most worn-out marketing clichés."),
    (50, "Style: write like a thoughtful human copywriter, not like an AI: vary sentence length, use contractions "
         "and concrete details, at most one exclamation mark, no clichés, no rhetorical-question opener, no "
         "'not just X, but Y', no lists of three adjectives."),
    (75, "Style: sound like a real person writing it themselves, e.g. a reader who loved the book: plain everyday "
         "words, first person where it fits, a genuine opinion, short and specific, slightly informal is fine. "
         "No marketing clichés, no hype words, no exclamation-mark chains, emojis and hashtags only as many as "
         "the platform strictly needs, no em dashes."),
]

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

REWRITE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You edit marketing text so that it sounds like a real person wrote it, not an AI. Rephrase or remove these "
     "AI-typical phrases and patterns: {tells}. Keep the meaning, the facts, any quotes, the format and roughly "
     "the length. Keep every citation marker like [2] exactly as it is, attached to the statement it supports. "
     "Reply with the edited text only.\n\n{style}"),
    ("human", "{text}"),
])



def style_guidance(humanize: int) -> str:
    """Style guidance for a "humanize" level (0-100), plus the list of AI clichés to avoid from level 50 on."""
    guidance = next(text for bound, text in reversed(HUMAN_LEVELS) if humanize >= bound)
    if humanize >= 50:
        guidance += " Never use these AI-typical phrases: " + ", ".join(f'"{t}"' for t in AI_TELLS) + "."
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
