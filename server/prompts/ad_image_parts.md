<!--
The variable parts of the ad image prompt (ad_image.md), one is chosen per section kind by core/images.py:
  with_cover / without_cover   whether the book's cover is attached as an image
  headline / no_text           draw the ad's headline into the image, or no text at all
  scene                        the author's own wish for the scene (left out when they gave none)
Placeholders: {headline} in "headline", {scene} in "scene".
-->

## with_cover

The attached image is the book's cover. Show the book as a physical book with exactly this cover, clearly visible and unchanged: same title, author name, colours and artwork. Do not redesign or re-letter the cover.

## without_cover

There is no cover image: do not show a book cover with invented title text. Show a scene that makes people curious about the book's subject instead.

## headline

Put this headline into the image, spelled exactly as written, in large, clean, easily readable letters with good contrast, away from the cover: "{headline}"
No other text, apart from what is printed on the cover itself.

## no_text

Do not add any text, letters or words to the image, apart from what is printed on the cover itself.

## scene

The author's wish for the scene: {scene}
