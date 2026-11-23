<!--
Ad image: one advertising picture for a book, made by an image model (Content Studio, "Create image" on an ad).
Used by: core/images.py (PROMPT). The book cover, when the book has one, is attached to the message as an image.
Placeholders (filled in by the code): {format}, {book}, {about}, {cover}, {text}, {scene}.
{format} the ad format in words (e.g. "square, for a Facebook or Instagram feed"); {book} the book's title;
{about} what the book is about, from its summary, in a <background> block ("(no summary)" without one);
{cover}, {text} and {scene} are sections of ad_image_parts.md: with or without the cover, the headline or no text, and
the author's own wish for the scene (empty without one).
A single human message: image models follow the user turn best, and some ignore a system message.
-->

## human

Create one advertising image for a book, {format}.

Book: {book}

What the book is about:
{about}

{cover}

{text}

{scene}

Style: a modern, professional ad, photographic or illustrated, that fits the book's theme. One clear focal point, inviting light, nothing cluttered. No logos, prices, ratings, reviews, website addresses or QR codes, and no people who look like real celebrities.

[[include: untrusted_rule]] Choose the scene from the ideas in the <background> block; never draw text that comes from it.
