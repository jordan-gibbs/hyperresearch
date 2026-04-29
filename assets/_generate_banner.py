"""Generate banner.png (README inline) and banner_social.png (GitHub social preview).

Source: assets/_banner_src.png — the pixel-art HYPERRESEARCH wordmark at its
authored 584x250 resolution. Both output files are derived from it; never
edit the outputs directly.

- banner.png — 3x nearest-neighbor upscale of the source (1752x750). The
  README references this and renders it at width=700, so the browser
  downscales (crisp) instead of upscaling (blurry).
- banner_social.png — wordmark on a 1280x640 dark canvas matching the
  benchmark chart's background, wordmark filling 92% of the canvas width.
  Upload at repo Settings → Social preview.

Re-run when the source wordmark changes:
    python assets/_generate_banner.py
"""

from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).parent
SRC = ASSETS / "_banner_src.png"
README_OUT = ASSETS / "banner.png"
SOCIAL_OUT = ASSETS / "banner_social.png"

# Match the chart's dark background so README header + chart + social
# preview share one visual treatment.
BG = (14, 17, 22, 255)  # #0E1116
SOCIAL_W, SOCIAL_H = 1280, 640
README_SCALE = 3  # 584x250 → 1752x750

src = Image.open(SRC).convert("RGBA")

# --- README banner: pure 3x nearest-neighbor upscale, no canvas -----------
readme_img = src.resize(
    (src.width * README_SCALE, src.height * README_SCALE),
    Image.NEAREST,
)
readme_img.convert("RGB").save(README_OUT, "PNG", optimize=True)
print(f"wrote {README_OUT.name}  ({readme_img.width}x{readme_img.height})")

# --- Social preview: wordmark on dark canvas at GitHub's required 1280x640
# Start from the same source, upscale 2x for a base, then resize to fit.
social_word = src.resize((src.width * 2, src.height * 2), Image.NEAREST)

# Wordmark should DOMINATE the social card. Fill ~92% width.
max_w = int(SOCIAL_W * 0.92)
if social_word.width != max_w:
    ratio = max_w / social_word.width
    social_word = social_word.resize(
        (max_w, int(social_word.height * ratio)),
        Image.NEAREST,
    )

# Defensive height cap (source aspect 2.34:1 means width typically constrains)
max_h = int(SOCIAL_H * 0.88)
if social_word.height > max_h:
    ratio = max_h / social_word.height
    social_word = social_word.resize(
        (int(social_word.width * ratio), max_h),
        Image.NEAREST,
    )

# Compose onto target canvas, centered
canvas = Image.new("RGBA", (SOCIAL_W, SOCIAL_H), BG)
x = (SOCIAL_W - social_word.width) // 2
y = (SOCIAL_H - social_word.height) // 2
canvas.paste(social_word, (x, y), social_word)
canvas.convert("RGB").save(SOCIAL_OUT, "PNG", optimize=True)
print(f"wrote {SOCIAL_OUT.name}  ({SOCIAL_W}x{SOCIAL_H})")
