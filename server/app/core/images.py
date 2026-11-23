"""Ad images: one advertising picture for a book, made by an image model, with the book's cover in it.

    generate_ad_image(book="...", about="...", cover=<png bytes>, headline="...", fmt="square")  →  GeneratedImage

Who makes the image is set by IMAGE_PROVIDER (config.py):
  - "openrouter" (default): IMAGE_MODEL through OpenRouter's chat endpoint, with LangChain's ChatOpenAI. OpenRouter
    returns the picture in a field of the reply ("images") that langchain-openai drops, so ImageChatOpenAI keeps it.
    Because it is the usual LangChain chat model, usage.handler logs each call with OpenRouter's exact cost, so the
    images count against the same budgets as every other model call (limits.toml, api/deps.llm_limits), and LangSmith
    traces it in debug mode.
  - "comfyui" (planned): a local image model on the author's own computer, free per image.

The prompt is prompts/ad_image.md with its parts in prompts/ad_image_parts.md. The model's reply is not trusted as a
picture: it must be base64 data of a PNG or JPEG image (checked by its first bytes) of at most MAX_IMAGE_BYTES. (WebP is not
accepted: PyMuPDF, which turns every picture into the PNG that is stored, cannot read it.)
"""

import base64
import binascii
import logging
from dataclasses import dataclass
from functools import cache
from typing import Any, Literal

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI

from app.core import config, prompt_files, prompts, usage
from app.core.guard import quote_untrusted
from app.core.llm import GenerationError, model_failure

logger = logging.getLogger(__name__)

ImageFormat = Literal["square", "portrait", "story", "landscape"]

# Ad format → (aspect ratio the model is asked for, the format in words for the prompt). Ratios the image models on
# OpenRouter accept; landscape is 16:9 because 1.91:1 (Facebook link ads) is not among them, and is cropped by little.
FORMATS: dict[str, tuple[str, str]] = {
    "square": ("1:1", "square, for a Facebook or Instagram feed"),
    "portrait": ("4:5", "portrait, for a Facebook or Instagram feed"),
    "story": ("9:16", "tall, for Instagram or Facebook stories and reels"),
    "landscape": ("16:9", "wide, for a link ad or a post with a link"),
}
MAX_HEADLINE_CHARS = 80
MAX_SCENE_CHARS = 300
MAX_IMAGE_BYTES = 12 * 1024 * 1024  # a 2K PNG is about 4 MB; anything far larger is not what was asked for
IMAGE_RETRIES = 1  # each attempt is charged, so a failed request is repeated only once

# The first bytes of the picture formats accepted from the model, and their media types.
SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)

PROMPT = prompt_files.chat_prompt("ad_image")
PARTS = prompt_files.table("ad_image_parts")
PROMPT_VERSION = prompts.register("ad_image", PROMPT, PARTS, {k: v[1] for k, v in FORMATS.items()})


@dataclass(frozen=True)
class GeneratedImage:
    """A generated picture: its bytes, media type ("image/png" or "image/jpeg"), the model that made it, the prompt
    version and its cost in USD as OpenRouter reported it (None if not reported)."""

    data: bytes
    media_type: str
    model: str
    prompt_version: str
    cost: float | None = None


class ImageChatOpenAI(ChatOpenAI):
    """ChatOpenAI that keeps the pictures of the reply: OpenRouter sends them as `images` next to the text of the
    message (a list of {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}); they are put into
    the message's additional_kwargs["images"]."""

    def _create_chat_result(self, response: Any, generation_info: dict | None = None):
        result = super()._create_chat_result(response, generation_info)
        data = response if isinstance(response, dict) else response.model_dump(warnings=False)
        for generation, choice in zip(result.generations, data.get("choices") or []):
            if images := (choice.get("message") or {}).get("images"):
                generation.message.additional_kwargs["images"] = images
        return result


def is_configured() -> bool:
    """True if ad images can be made: a known provider and, for OpenRouter, its API key."""
    return config.IMAGE_PROVIDER == "openrouter" and config.PROVIDER == "openrouter" and bool(config.API_KEY)


@cache
def _model(aspect_ratio: str) -> Runnable:
    """The image model via OpenRouter, asked for pictures of `aspect_ratio` (one cached instance per ratio)."""
    return ImageChatOpenAI(
        model=config.IMAGE_MODEL, api_key=config.API_KEY, base_url=config.BASE_URL,
        timeout=config.IMAGE_TIMEOUT_SECONDS, max_retries=IMAGE_RETRIES, callbacks=[usage.handler],
        extra_body={"modalities": ["image", "text"], "image_config": {"aspect_ratio": aspect_ratio},
                    "usage": {"include": True}})


def build_messages(*, book: str, about: str, headline: str | None, scene: str | None, fmt: str,
                   cover: bytes | None, cover_type: str = "image/png") -> list[BaseMessage]:
    """The prompt for one ad image: the text of prompts/ad_image.md and, if given, the cover as an attached image.

    Raises:
        ValueError: An unknown format, or a headline or scene that is too long.
    """
    if fmt not in FORMATS:
        raise ValueError(f"Unknown image format {fmt!r}; use one of {', '.join(FORMATS)}")
    headline, scene = _one_line(headline), _one_line(scene)
    if len(headline) > MAX_HEADLINE_CHARS:
        raise ValueError(f"The headline is longer than {MAX_HEADLINE_CHARS} characters")
    if len(scene) > MAX_SCENE_CHARS:
        raise ValueError(f"The scene is longer than {MAX_SCENE_CHARS} characters")
    messages = PROMPT.format_messages(
        format=FORMATS[fmt][1], book=_one_line(book) or "(untitled)",
        about=quote_untrusted(about, "background") if about.strip() else "(no summary)",
        cover=PARTS["with_cover" if cover else "without_cover"],
        # The headline's own quotes are replaced, so it cannot end the quoted text early.
        text=PARTS["headline"].replace("{headline}", headline.replace('"', "'")) if headline else PARTS["no_text"],
        scene=PARTS["scene"].replace("{scene}", scene) if scene else "")
    if cover:
        last = messages[-1]
        encoded = base64.b64encode(cover).decode("ascii")
        messages[-1] = HumanMessage(content=[
            {"type": "text", "text": last.content},
            {"type": "image_url", "image_url": {"url": f"data:{cover_type};base64,{encoded}"}},
        ])
    return messages


def generate_ad_image(*, book: str, about: str, headline: str | None = None, scene: str | None = None,
                      fmt: str = "square", cover: bytes | None = None, cover_type: str = "image/png",
                      project_id: str | None = None, source_id: str | None = None) -> GeneratedImage:
    """Make one ad image for a book.

    Args:
        book: The book's title.
        about: What the book is about (its summary and themes); quoted to the model as data.
        headline: Text to draw into the image; None or empty for an image without text.
        scene: The author's own wish for the scene, if any.
        fmt: One of FORMATS.
        cover: The book's cover image, shown in the ad; None if the book has none.
        cover_type: The cover's media type.
        project_id, source_id: For the usage log.

    Raises:
        ValueError: An unknown format, or a headline or scene that is too long (the API checks these first).
        GenerationError: 503 if no image provider is configured, 504 if it timed out, 502 if it failed or sent no
            usable picture.
    """
    messages = build_messages(book=book, about=about, headline=headline, scene=scene, fmt=fmt, cover=cover,
                              cover_type=cover_type)
    if config.IMAGE_PROVIDER != "openrouter":
        raise GenerationError(503, f"Image provider {config.IMAGE_PROVIDER!r} is not available. "
                                   "Set IMAGE_PROVIDER=openrouter in server/.env and restart the server.")
    if not is_configured():
        raise GenerationError(503, "Ad images need OpenRouter. Add OPENROUTER_API_KEY to server/.env and restart.")
    run = {"run_name": "ad_image", "tags": ["ad_image"],
           "metadata": {"operation": "ad_image", "prompt_version": PROMPT_VERSION, "model": config.IMAGE_MODEL,
                        "format": fmt, "project_id": project_id, "source_id": source_id}}
    try:
        reply = _model(FORMATS[fmt][0]).invoke(messages, config=run)
    except Exception as e:  # noqa: BLE001 - every failure of the call becomes a GenerationError
        raise model_failure(e, "The image model call failed") from e
    data, media_type = decode_image(reply.additional_kwargs.get("images") or [])
    cost = (reply.response_metadata.get("token_usage") or {}).get("cost")
    logger.info("ad image: %s, %s, %d KB, $%s", config.IMAGE_MODEL, fmt, len(data) // 1024, cost)
    return GeneratedImage(data=data, media_type=media_type, model=config.IMAGE_MODEL, prompt_version=PROMPT_VERSION,
                          cost=float(cost) if cost is not None else None)


def decode_image(images: list[dict]) -> tuple[bytes, str]:
    """The first picture of a reply's `images` as bytes and media type.

    Raises:
        GenerationError: 502 if there is none, it is not base64 data, not a PNG or JPEG image, or too large.
    """
    for image in images:
        url = ((image or {}).get("image_url") or {}).get("url") or ""
        if not url.startswith("data:") or "," not in url:
            continue
        if len(url) > MAX_IMAGE_BYTES * 4 // 3 + 100:
            raise GenerationError(502, "The image model sent a picture that is too large.")
        try:
            data = base64.b64decode(url.split(",", 1)[1], validate=True)
        except (binascii.Error, ValueError):
            continue
        if len(data) > MAX_IMAGE_BYTES:
            raise GenerationError(502, "The image model sent a picture that is too large.")
        if media_type := image_type(data):
            return data, media_type
    raise GenerationError(502, "The image model sent no picture. Please try again, or change the headline or scene.")


def image_type(data: bytes) -> str | None:
    """The media type of a PNG or JPEG image from its first bytes; None for anything else."""
    for signature, media_type in SIGNATURES:
        if data.startswith(signature):
            return media_type
    return None


# JPEG "start of frame" markers, which carry the picture's size (all SOFn except DHT C4, JPG C8 and DAC CC).
_JPEG_FRAMES = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def image_size(data: bytes) -> tuple[int, int] | None:
    """Width and height of a PNG or JPEG picture, read from its header without decoding it; None if unreadable."""
    if data.startswith(SIGNATURES[0][0]):
        if len(data) >= 24 and data[12:16] == b"IHDR":
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        return None
    if not data.startswith(SIGNATURES[1][0]):
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # padding
            i += 1
            continue
        if marker in _JPEG_FRAMES:
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # markers without a length
            i += 2
            continue
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return None


def _one_line(text: str | None) -> str:
    """The text with all whitespace (line breaks, tabs) as single spaces, trimmed; "" for None."""
    return " ".join((text or "").split())
