"""
Overlay module: subtitle banners and transition frames for video recording.
Uses Pillow for text rendering with Cyrillic support (Segoe UI / Arial).
"""

import os
from PIL import Image, ImageDraw, ImageFont

# Cyrillic-capable fonts on Windows
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
]

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _find_font_path() -> str:
    for path in _FONT_CANDIDATES:
        if os.path.isfile(path):
            return path
    return "arial.ttf"  # fallback to Pillow default search


def get_font(size: int = 28) -> ImageFont.FreeTypeFont:
    """Load a Cyrillic-capable TrueType font, with caching."""
    key = (_find_font_path(), size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(key[0], size)
    return _font_cache[key]


def apply_subtitle(
    image: Image.Image,
    text: str,
    font_size: int = 30,
    banner_height: int = 64,
    banner_opacity: int = 180,
    padding_bottom: int = 0,
) -> Image.Image:
    """
    Draw a semi-transparent dark banner at the bottom of the image
    with centered white Cyrillic text (subtitle style).

    Returns a new image (original is not modified).
    """
    if not text:
        return image

    w, h = image.size
    result = image.copy().convert("RGBA")

    # Create semi-transparent banner
    banner = Image.new("RGBA", (w, banner_height), (0, 0, 0, 0))
    draw_banner = ImageDraw.Draw(banner)
    draw_banner.rectangle(
        [(0, 0), (w, banner_height)],
        fill=(30, 30, 30, banner_opacity),
    )

    # Draw text centered in the banner
    font = get_font(font_size)
    bbox = draw_banner.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = (w - text_w) // 2
    text_y = (banner_height - text_h) // 2 - bbox[1]
    draw_banner.text((text_x, text_y), text, fill=(255, 255, 255, 255), font=font)

    # Paste banner at the bottom
    y_pos = h - banner_height - padding_bottom
    result.alpha_composite(banner, dest=(0, y_pos))

    return result.convert("RGB")


def create_transition_frame(
    width: int,
    height: int,
    title: str,
    subtitle: str = "",
    bg_color: tuple[int, int, int] = (44, 62, 80),
    title_font_size: int = 44,
    subtitle_font_size: int = 26,
) -> Image.Image:
    """
    Create a full-frame transition slide with centered title and optional subtitle.
    Used between scenes as a visual separator.
    """
    image = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(image)

    # Title
    title_font = get_font(title_font_size)
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    title_h = title_bbox[3] - title_bbox[1]

    total_h = title_h
    if subtitle:
        sub_font = get_font(subtitle_font_size)
        sub_bbox = draw.textbbox((0, 0), subtitle, font=sub_font)
        sub_h = sub_bbox[3] - sub_bbox[1]
        total_h += 20 + sub_h  # 20px gap

    # Center vertically
    start_y = (height - total_h) // 2

    # Draw title
    title_x = (width - title_w) // 2
    draw.text(
        (title_x, start_y - title_bbox[1]),
        title,
        fill=(255, 255, 255),
        font=title_font,
    )

    # Draw subtitle
    if subtitle:
        sub_font = get_font(subtitle_font_size)
        sub_bbox = draw.textbbox((0, 0), subtitle, font=sub_font)
        sub_w = sub_bbox[2] - sub_bbox[0]
        sub_x = (width - sub_w) // 2
        sub_y = start_y + title_h + 20
        draw.text(
            (sub_x, sub_y - sub_bbox[1]),
            subtitle,
            fill=(200, 200, 200),
            font=sub_font,
        )

    return image
