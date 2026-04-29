"""Generate banner_social.png at GitHub-social-preview dimensions (1280x640).

Takes the original pixel-art wordmark (assets/banner.png, 584x250),
upscales it 2x with nearest-neighbor to preserve the chunky pixel
aesthetic, and places it centered on a 1280x640 dark canvas matching
the benchmark chart's background color so the README header + social
preview + Star History icon all read as one visual system.

The README still references the original `banner.png` for inline display.
This script writes a SEPARATE file so the original is never overwritten.

Output: assets/banner_social.png (for repo Settings → Social preview)
"""

from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).parent
SRC = ASSETS / "banner.png"
OUT = ASSETS / "banner_social.png"

# Match the chart's dark background so the README header + chart + social
# preview share one visual treatment.
BG = (14, 17, 22, 255)  # #0E1116
TARGET_W, TARGET_H = 1280, 640

src = Image.open(SRC).convert("RGBA")

# Upscale the wordmark 2x with nearest-neighbor — preserves the pixel-art
# chunky letterforms instead of blurring them.
upscaled = src.resize((src.width * 2, src.height * 2), Image.NEAREST)

# Wordmark should DOMINATE the social card, not float in a sea of dark
# padding. Fill ~92% of the canvas width — leaves a thin margin so the
# letterforms breathe but the content reads clearly when platforms
# crop to tighter aspect ratios than GitHub's native 2:1.
max_w = int(TARGET_W * 0.92)
if upscaled.width != max_w:
    ratio = max_w / upscaled.width
    upscaled = upscaled.resize(
        (max_w, int(upscaled.height * ratio)),
        Image.NEAREST,
    )

# Sanity cap at 88% of canvas height (mostly defensive — the source
# wordmark's 2.34:1 aspect ratio means width usually constrains first).
max_h = int(TARGET_H * 0.88)
if upscaled.height > max_h:
    ratio = max_h / upscaled.height
    upscaled = upscaled.resize(
        (int(upscaled.width * ratio), max_h),
        Image.NEAREST,
    )

# Compose onto target canvas, centered
canvas = Image.new("RGBA", (TARGET_W, TARGET_H), BG)
x = (TARGET_W - upscaled.width) // 2
y = (TARGET_H - upscaled.height) // 2
canvas.paste(upscaled, (x, y), upscaled)

canvas.convert("RGB").save(OUT, "PNG", optimize=True)
print(f"wrote {OUT}  ({TARGET_W}x{TARGET_H})")
