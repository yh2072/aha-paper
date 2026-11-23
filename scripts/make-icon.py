"""Draw build/icon.png, the source electron-builder turns into .icns and .ico.

The mark is the one already in the sidebar: a white eight-spoked asterisk on the
app's green. It is drawn rather than typeset because ✳ (U+2733) is not in every
font, and an icon that depends on which fonts the build machine has is an icon
that silently changes.

    python3 scripts/make-icon.py

1024px, with the ~10% margin macOS expects around the rounded square.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
MARGIN = round(SIZE * 0.094)          # Apple's icon grid leaves the square inset
RADIUS = round((SIZE - 2 * MARGIN) * 0.225)
GREEN = (31, 111, 79, 255)            # --accent in web/refine.css
WHITE = (255, 255, 255, 255)

SPOKES = 8
SPOKE_LENGTH = 0.30 * SIZE
SPOKE_WIDTH = round(0.052 * SIZE)


def main() -> Path:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([MARGIN, MARGIN, SIZE - MARGIN, SIZE - MARGIN],
                           radius=RADIUS, fill=GREEN)

    centre = SIZE / 2
    for index in range(SPOKES):
        # Start at 12 o'clock so the mark reads upright rather than tilted.
        angle = math.pi / 2 + index * 2 * math.pi / SPOKES
        tip = (centre + SPOKE_LENGTH * math.cos(angle),
               centre - SPOKE_LENGTH * math.sin(angle))
        draw.line([(centre, centre), tip], fill=WHITE, width=SPOKE_WIDTH)
    # A round cap at the centre, so eight separately-capped lines do not leave a
    # notch where they meet.
    draw.ellipse([centre - SPOKE_WIDTH / 2, centre - SPOKE_WIDTH / 2,
                  centre + SPOKE_WIDTH / 2, centre + SPOKE_WIDTH / 2], fill=WHITE)

    out = Path(__file__).resolve().parent.parent / "build" / "icon.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    return out


if __name__ == "__main__":
    print(main())
