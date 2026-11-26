"""Guardrails: input validation and prompt-injection defence for text that reaches a language model.

    validate_input        clean user text (invisible/control characters, line endings) and check it
                          against the length limit of its kind (question, chat message, brief, ...)
    check_prompt_injection  rule-based scan for instructions aimed at the model ("ignore previous
                          instructions", fake role markers, prompt leaks, text that speaks to the AI, hidden
                          characters, ...), also in a few other languages and behind common disguises
                          (look-alike letters, "1gn0re", "i g n o r e", Base64, hex, ROT13, backwards)
    wrap_untrusted        put retrieved or pasted text into numbered <passage> tags, plus the system
                          prompt rule that says such text is data, never instructions
    scan_third_party      check_prompt_injection for other people's text (discussions, Reddit threads, Facebook
                          comments) as risk + short findings to show and save; such text is flagged, not blocked
    injection_note        the app's note for a prompt when quoted text contains a likely injection
    check_output          a model-written text that will be posted: injection patterns that got through, and
                          links that do not come from the allowed sources

Pure functions, no model calls: fast, free and deterministic, so they can run on every request. Used by the
mcp-guardrails MCP server (market/guard_server.py) and meant for the app's own endpoints too. The injection
check is a heuristic: it catches the common attack phrasings, not every possible one (free paraphrases mostly
get through; eval/run_guard_eval.py measures it against a red-team set), which is why wrap_untrusted (keeping
data apart from instructions) is the second line of defence.
"""

import base64
import codecs
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field

from app.core import prompt_files

InputKind = Literal["short_text", "question", "chat_message", "search_query", "brief", "social_post", "asset_text",
                    "discussion"]
Severity = Literal["low", "high"]

# Maximum length (characters) per kind of input.
MAX_LENGTH: dict[InputKind, int] = {
    "short_text": 300,  # a title, author, genre, audience or theme
    "question": 1000,
    "chat_message": 4000,  # may contain a pasted post to check (LinkedIn allows 3000 characters)
    "search_query": 500,
    "brief": 4000,
    "social_post": 3000,
    "asset_text": 12000,
    "discussion": 8000,  # a pasted post plus some of its replies (Discussion Relevance Agent)
}
MAX_SCAN_CHARS = 200_000  # longest text the checks accept at all (a whole chapter fits)

# Zero-width and bidi-control characters: invisible, used to hide or reorder text.
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿]")
# Control characters except tab and newline.
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# ---------- Results ----------
class Problem(BaseModel):
    """One finding of validate_input."""

    code: str = Field(description="Machine-readable code, e.g. 'too_long'.")
    severity: Literal["error", "warning"] = Field(description="'error' makes the input invalid; 'warning' does not.")
    message: str


class ValidationResult(BaseModel):
    """Result of validate_input."""

    ok: bool = Field(description="True if there is no error (warnings are allowed).")
    cleaned: str = Field(description="The cleaned text; use this instead of the original.")
    length: int = Field(description="Length of the cleaned text in characters.")
    max_length: int
    problems: list[Problem]


class InjectionFinding(BaseModel):
    """One suspicious pattern found by check_prompt_injection."""

    rule: str = Field(description="Which rule matched, e.g. 'override_instructions'.")
    severity: Severity
    excerpt: str = Field(description="The matching text with a little context.")


class InjectionReport(BaseModel):
    """Result of check_prompt_injection."""

    passed: bool = Field(description="True if the text may be used (risk none or low); false if it should be blocked.")
    risk: Literal["none", "low", "high"] = Field(
        description="'high': block or ask the user; 'low': allow but keep the text wrapped as data; 'none': nothing found.")
    findings: list[InjectionFinding]
    advice: str


class WrappedText(BaseModel):
    """Result of wrap_untrusted."""

    wrapped: str = Field(description="The passages in numbered <passage n=\"...\"> tags, ready for the prompt.")
    instruction: str = Field(description="The rule to put in the system prompt.")
    flagged: list[int] = Field(description="Numbers of passages with a high prompt-injection risk.")


# ---------- Injection rules ----------
# (rule, severity, pattern); matched case-insensitively on the normalized text. Phrases are kept specific so
# that ordinary book and marketing prose (e.g. "acts as a catalyst") does not match.
# A rule name may appear several times (e.g. one pattern per language); the first pattern that matches gives the finding.
# eval/run_guard_eval.py measures the rules against a red-team set (catch rate, false alarms); test_guard_redteam.py
# keeps both from getting worse.
_AI = r"(?:AIs?|LLMs?|(?:large )?language models?|chat ?bots?|bots?|(?:AI |automated |virtual )assistants?|AI agents?)"
_RULES: list[tuple[str, Severity, re.Pattern]] = [(rule, sev, re.compile(p, re.IGNORECASE)) for rule, sev, p in [
    # "ignore the previous / your / the system's ..." with any word for the instructions ...
    ("override_instructions", "high",
     r"\b(ignore|disregard|forget|override|bypass)\b.{0,30}\b(previous|prior|above|earlier|preceding|your|system)\b"
     r".{0,20}\b(instructions?|rules|prompts?|directions|guidelines|guardrails)\b"),
    # ... but after a plain "the / all / any" only the words that mean a model's instructions ("ignore the rules of
    # grammar" is ordinary prose).
    ("override_instructions", "high",
     r"\b(ignore|disregard|forget|override|bypass)\b.{0,15}\b(all|any|the)\b.{0,15}\b(instructions?|prompts?|guardrails)\b"),
    # The same in other languages: the verb plus the word for instructions or rules.
    ("override_instructions", "high",  # German
     r"\b(ignorier\w*|vergiss|vergesst|missachte\w*|übergeh\w*)\b.{0,40}"
     r"\b(anweisung(en)?|regeln|vorgaben|instruktionen|richtlinien|system-?prompt)\b"),
    ("override_instructions", "high",  # Spanish, Italian, Portuguese
     r"\b(ignora|ignorad|olvida|olvidad|dimentica|esque[cç]a)\b.{0,40}"
     r"\b(instrucciones|reglas|indicaciones|istruzioni|regole|instruções|regras)\b"),
    ("override_instructions", "high",  # French (with its article: "ignore ... instructions" alone is English prose)
     r"\b(ignore[zr]?|oublie[zr]?)\b.{0,25}\b(tes|toutes les|les|vos|ces)\s+(instructions|règles|consignes)\b"),
    ("override_instructions", "high",  # Lithuanian, Russian
     r"\b(ignoruok\w*|pamiršk\w*|nepaisyk\w*)\b.{0,40}\b(instrukcij\w*|taisykl\w*|nurodym\w*)\b"
     r"|\b(игнорируй\w*|забудь\w*|не обращай\w* внимания)\b.{0,40}\b(инструкци\w*|правил\w*|указани\w*)\b"),
    ("new_instructions", "high", r"\b(new|updated|real|actual) (system )?instructions?\s*[:\-]"),
    ("role_change", "high",
     r"\b(you are now|from now on,? you (are|will)|pretend (to be|you are)|roleplay as|act as (an? )?(unrestricted|unfiltered|jailbroken))\b"),
    ("role_change", "high",  # German, Spanish, French
     r"\b(du bist (jetzt|nun|ab jetzt|ab sofort)|ab (jetzt|sofort) bist du|ahora eres|tu es (maintenant|désormais)"
     r"|vous êtes (maintenant|désormais))\b"),
    ("jailbreak", "high",
     r"\b(jailbreak|developer mode|DAN mode|do anything now|you (now )?have no (restrictions|rules|limits|filters))\b"),
    ("prompt_leak", "high",
     r"\b(reveal|show|print|repeat|output|tell me|what (is|are))\b.{0,25}\b(system prompt|hidden prompt)\b"),
    # "your instructions / rules" too, unless a topic follows ("your instructions for planting tomatoes").
    ("prompt_leak", "high",
     r"\b(reveal|show|print|repeat|output|tell me|what (is|are))\b.{0,25}\byour (instructions|rules|prompt)\b"
     r"(?!\s+(for|on|about|regarding)\b)"),
    ("prompt_leak", "high",
     r"\b(repeat|print|output|quote|write out)\b.{0,15}\b(everything|all|the text|the words)\b.{0,15}\babove\b"
     r"|\b(beginning|top|start) of your context\b|\byour (initial|original|first) (instructions|prompt)\b"),
    ("prompt_leak", "high",  # German, Spanish, Italian
     r"\b(gib|zeig\w*|nenn\w*|verrat\w*|wiederhol\w*)\b.{0,30}\b(system-?prompt|deine[nr]? (anweisungen|regeln|instruktionen))\b"
     r"|\b(muestra|revela|repite|dime|rivela|mostra)\b.{0,30}\b(prompt de(l|i)? sistem[ao]|tus (instrucciones|reglas))\b"),
    ("fake_role_marker", "high",
     r"(<\|im_(start|end)\|>|<\|(system|assistant|user)\|>|\[/?INST\]|<<SYS>>|</?system>|^\s*(system|assistant)\s*:"
     r"|^\s*#{1,6}\s*(system|assistant)\b|\[(system|assistant)( message| prompt| note)?\]"
     r"|^\s*[-=*]{2,}\s*end of (the )?(post|message|text|document|input|context|thread)\b"
     r"|</(post|passage|background|tool_result)>)"),  # the app's own block tags: someone tries to close the quote
    # Text that speaks to the model that will read it: in a thread or a comment nobody writes that to a person.
    ("addressed_to_ai", "high",
     r"\bif you(?: are|'re) (?:an? )?" + _AI + r"\b"
     r"|\b(note|message|instructions?|reminder|memo|request)\b.{0,12}\b(to|for)\b (?:the |any |all |an? )?" + _AI + r"\b"
     r"|\b(dear|hey|attention|to any|to all|to the) " + _AI + r"\b"
     r"|\b" + _AI + r"\b.{0,12}\b(reading|processing|summari[sz]ing|answering|seeing) this\b"),
    ("hide_from_user", "high",
     r"\b(do not|don't|never) (tell|inform|show|mention (this|it) to) the user\b(?!\s+(what|how|to)\b)"),
    ("exfiltration", "high",
     r"(!\[[^\]]*\]\(https?://[^)]*[?&][^)]*=|\b(send|post|upload|forward)\b.{0,40}\bto\b.{0,10}https?://)"),
    ("tool_command", "low", r"\b(call|run|execute|invoke) (the )?(tool|function|command)\b"),
    ("encoded_blob", "low", r"[A-Za-z0-9+/]{200,}={0,2}"),
]]

# ---------- Disguises ----------
# Letters of other alphabets that look like Latin ones (Cyrillic, Greek): "ignоre" with a Cyrillic о.
_LOOKALIKES = str.maketrans("аеорсхуіјѕԁһАЕОРСХТНКМВІЈЅαεοιρτυνκΑΕΟΙΡΤΥΝΚΜΒΗΧΖ",
                            "aeopcxyijsdhAEOPCXTHKMBIJSaeoiptuvkAEOIPTYNKMBHXZ")
_LEET = str.maketrans("013457", "oieast")
_LEET_WORD = re.compile(r"\b(?=\w*[A-Za-z])(?=\w*[013457])\w+\b")  # a word with letters and digits: "1gn0re"
_SPELLED = re.compile(r"\b(?:[A-Za-z][ .\-_*]){3,}[A-Za-z]\b")  # "i g n o r e", "i.g.n.o.r.e"
_BASE64 = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")
_HEX = re.compile(r"\b(?:[0-9a-fA-F]{2}){12,}\b")
_MAX_BLOBS = 5  # encoded pieces decoded per text
_MAX_BLOB_CHARS = 8000


# ---------- Functions ----------
def clean_text(text: str) -> str:
    """Text with Unicode normalized (NFKC, e.g. ligatures and full-width letters become plain letters),
    invisible and control characters removed, line endings unified, blank-line runs shortened and the ends stripped."""
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def validate_input(text: str, kind: InputKind) -> ValidationResult:
    """Clean user text and check it against the rules of its kind.

    Errors (input invalid): empty, longer than MAX_LENGTH[kind]. Warnings: invisible or control characters
    were removed, long runs of one repeated character (spam / padding).
    """
    max_length = MAX_LENGTH[kind]
    cleaned = clean_text(text)
    problems: list[Problem] = []
    if not cleaned:
        problems.append(Problem(code="empty", severity="error", message="The text is empty."))
    if len(cleaned) > max_length:
        problems.append(Problem(code="too_long", severity="error",
                                message=f"The text has {len(cleaned)} characters; at most {max_length} are allowed for a {kind}."))
    if _INVISIBLE.search(text) or _CONTROL.search(text):
        problems.append(Problem(code="hidden_characters", severity="warning",
                                message="Invisible or control characters were removed."))
    if re.search(r"(.)\1{49,}", cleaned):
        problems.append(Problem(code="repetition", severity="warning",
                                message="The text contains a character repeated 50 or more times."))
    return ValidationResult(ok=not any(p.severity == "error" for p in problems), cleaned=cleaned, length=len(cleaned),
                            max_length=max_length, problems=problems)


def check_prompt_injection(text: str) -> InjectionReport:
    """Scan text for attempts to give the model instructions (rule-based, see _RULES).

    Works for user input and for document text (uploaded books, pasted posts, retrieved passages). Hidden
    characters count as a low-risk finding of their own, because they can hide instructions from a human reader.
    """
    findings: list[InjectionFinding] = []
    if _INVISIBLE.search(text):
        findings.append(InjectionFinding(rule="hidden_characters", severity="low",
                                         excerpt="(zero-width or text-direction characters)"))
    views = _views(clean_text(text))
    found: set[str] = set()
    for rule, severity, pattern in _RULES:
        if rule in found:  # an earlier pattern of this rule (e.g. another language) already matched
            continue
        finding = _first_match(rule, pattern, views)
        if finding:
            found.add(rule)
            findings.append(InjectionFinding(rule=rule, severity=severity, excerpt=finding))
    risk = "high" if any(f.severity == "high" for f in findings) else "low" if findings else "none"
    return InjectionReport(passed=risk != "high", risk=risk, findings=findings, advice=_ADVICE[risk])


def _first_match(rule: str, pattern: re.Pattern, views: list[tuple[str, str]]) -> str | None:
    """The excerpt of the first view the pattern matches (None for no match); a disguised view is named in it."""
    for label, view in views:
        for line in view.splitlines() if rule == "fake_role_marker" else [view]:
            match = pattern.search(line)
            if match:
                return (f"({label}) " if label else "") + _excerpt(line, match)
    return None


def _views(normalized: str) -> list[tuple[str, str]]:
    """The text as the rules read it: as it is, and with its disguises removed, each as (label, text).

    Attackers hide the phrases the rules look for; a model still reads them. So the rules also run on:
      - "unmasked": look-alike letters of other alphabets as Latin ones, digits in words as letters ("1gn0re"),
        spelled-out words joined ("i g n o r e", "i.g.n.o.r.e"), hyphens inside words removed, lines joined;
      - "base64" / "hex": encoded pieces decoded, when they are readable text;
      - "rot13" and "reversed": the whole text shifted or turned around.
    The first view is the plain text, so an ordinary finding quotes the text as written.
    """
    views = [("", normalized)]
    unmasked = normalized.translate(_LOOKALIKES)
    unmasked = _LEET_WORD.sub(lambda m: m.group(0).translate(_LEET), unmasked)
    unmasked = _SPELLED.sub(lambda m: re.sub(r"[ .\-_*]", "", m.group(0)), unmasked)
    unmasked = re.sub(r"(?<=[a-z])-(?=[a-z])", "", unmasked)
    unmasked = re.sub(r"\s+", " ", unmasked)
    if unmasked != normalized:
        views.append(("unmasked", unmasked))
    for label, pattern, decode in (("base64", _BASE64, _from_base64), ("hex", _HEX, bytes.fromhex)):
        for match in list(pattern.finditer(normalized))[:_MAX_BLOBS]:
            decoded = _readable(match.group(0)[:_MAX_BLOB_CHARS], decode)
            if decoded:
                views.append((label, decoded))
    views.append(("rot13", codecs.encode(normalized, "rot13")))
    views.append(("reversed", normalized[::-1]))
    return views


def _from_base64(blob: str) -> bytes:
    return base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True)


def _readable(blob: str, decode) -> str | None:
    """The decoded text of an encoded piece, or None if it is no text (a long word or a hash decodes to noise)."""
    try:
        decoded = decode(blob).decode("utf-8")
    except (ValueError, UnicodeDecodeError):  # binascii.Error is a ValueError
        return None
    letters = sum(c.isalpha() or c.isspace() for c in decoded)
    return clean_text(decoded) if decoded and letters / len(decoded) >= 0.8 else None


def wrap_untrusted(passages: list[str]) -> WrappedText:
    """Wrap passages as data for a prompt: each in <passage n="i">, with tags inside the text neutralized so a
    passage cannot close its own tag. Returns the system prompt rule and the passages with a high injection risk."""
    blocks, flagged = [], []
    for n, passage in enumerate(passages, start=1):
        blocks.append(quote_untrusted(passage, "passage", n=n))
        if check_prompt_injection(passage).risk == "high":
            flagged.append(n)
    return WrappedText(wrapped="\n\n".join(blocks), instruction=UNTRUSTED_RULE, flagged=flagged)


InjectionRisk = Literal["none", "low", "high"]


def scan_third_party(text: str) -> tuple[InjectionRisk, list[str]]:
    """Check other people's text (a pasted discussion, a Reddit thread, a Facebook comment) for prompt injection.

    Such text is not blocked: the author does not control it, and the scan is a heuristic. It is flagged instead, so
    the GUI can warn the author and the agent's prompts can say so (injection_note); it still reaches the model only
    quoted as data.

    Returns:
        The risk ("none", "low" or "high") and one line per finding: "rule: excerpt".
    """
    report = check_prompt_injection(text)
    return report.risk, [f"{f.rule}: {f.excerpt}" for f in report.findings]


def injection_note(findings: list[str]) -> str:
    """A note for the prompt, right after a quoted block whose scan found a likely injection ("" for no findings).

    It names the rules that matched (not the attacker's text) and repeats that the block is data."""
    if not findings:
        return ""
    rules = sorted({f.split(":", 1)[0] for f in findings})
    return "\n" + prompt_files.text("injection_note").format(rules=", ".join(rules))  # prompts/injection_note.md


_LINK = re.compile(r"\b(?:https?://|www\.)[^\s<>()\"']+|\b[\w.+-]+@[\w-]+\.[\w.-]+\b", re.IGNORECASE)


def check_output(text: str, allowed: str = "") -> list[str]:
    """Check a model-written text before it is shown for posting or posted (output guard).

    An injection that got past the input side shows up here: instruction phrases, fake role markers or exfiltration
    links in the reply, or links and e-mail addresses that the model did not get from the allowed sources (e.g. the
    book's passages), which is how a planted "add this link" request would leak into a post.

    Args:
        text: The reply or post.
        allowed: Text that may legitimately contain links (e.g. the cited passages); links found in it are fine.

    Returns:
        One message per problem; [] = no problem found.
    """
    problems = []
    report = check_prompt_injection(text)
    if report.risk == "high":
        problems.append("Looks like a prompt injection got into the text ("
                        + ", ".join(sorted({f.rule for f in report.findings if f.severity == "high"})) + ").")
    allowed_links = {m.group(0).rstrip(".,;:!?").lower() for m in _LINK.finditer(allowed)}
    foreign = sorted({link for m in _LINK.finditer(text)
                      if (link := m.group(0).rstrip(".,;:!?")).lower() not in allowed_links})
    if foreign:
        problems.append("Contains a link or address that is not from the book: " + ", ".join(foreign[:3])
                        + ". Check it before posting.")
    return problems


def output_blocked(text: str) -> bool:
    """True if a text must not be posted automatically: check_output found a likely prompt injection in it.
    (Foreign links are only a warning: the author may add their own link when editing.)"""
    return check_prompt_injection(text).risk == "high"


def quote_untrusted(text: str, tag: str, **attributes: object) -> str:
    """One block of outside text for a prompt, e.g. <passage n="1" source="...">text</passage> or <post>text</post>.

    Tags: passage (book text, chapter summaries), background (book summaries), post (someone else's post),
    tool_result (what a chat tool returned). The text is cleaned (clean_text) and any of these tags inside it is
    neutralized (&lt;), so it cannot close its own block and pose as instructions. Attribute values lose their
    double quotes.
    """
    body = _TAG_INSIDE.sub(r"&lt;\1\2", clean_text(text))
    attrs = "".join(f' {name}="{str(value).replace(chr(34), chr(39))}"' for name, value in attributes.items())
    return f"<{tag}{attrs}>\n{body}\n</{tag}>"


_TAG_INSIDE = re.compile(r"<(/?)(passage|post|background|tool_result)\b", re.IGNORECASE)

# The rule that quoted text is data (prompts/untrusted_rule.md; the prompt files include it as
# [[include: untrusted_rule]]).
UNTRUSTED_RULE = prompt_files.text("untrusted_rule")

_ADVICE = {
    "none": "No injection patterns found. Still keep untrusted text wrapped as data.",
    "low": "Weak signals only. Allow it, but pass the text to the model wrapped as data (wrap_untrusted).",
    "high": "Likely prompt injection. Block it, or ask the user to rephrase; never pass it on as instructions.",
}


def _excerpt(text: str, match: re.Match, context: int = 30) -> str:
    """The match with some context on both sides, shortened to one line."""
    start, end = max(0, match.start() - context), min(len(text), match.end() + context)
    excerpt = " ".join(text[start:end].split())
    if len(excerpt) > 160:
        excerpt = excerpt[:157] + "..."
    return ("…" if start else "") + excerpt + ("…" if end < len(text) else "")
