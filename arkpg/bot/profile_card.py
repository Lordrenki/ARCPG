from __future__ import annotations

from io import BytesIO

import discord
from PIL import Image, ImageDraw, ImageFont, ImageOps

from arkpg.game.profile_backgrounds import ProfileBackground

CARD_SIZE = 720


def _xp_progress(user_xp: int, level: int) -> tuple[int, int, float]:
    current_level_floor = 0 if level <= 1 else int((((level - 1) - 1) ** (1 / 0.62)) * 120)
    next_level_floor = int(((level - 1) ** (1 / 0.62)) * 120)
    needed_total = max(1, next_level_floor - current_level_floor)
    current_into_level = max(0, user_xp - current_level_floor)
    progress = max(0.0, min(current_into_level / needed_total, 1.0))
    return current_into_level, needed_total, progress


def _build_background(bg: ProfileBackground) -> Image.Image:
    image = Image.new("RGB", (CARD_SIZE, CARD_SIZE), bg.top_color)
    draw = ImageDraw.Draw(image)
    for y in range(CARD_SIZE):
        t = y / (CARD_SIZE - 1)
        r = int(bg.top_color[0] * (1 - t) + bg.bottom_color[0] * t)
        g = int(bg.top_color[1] * (1 - t) + bg.bottom_color[1] * t)
        b = int(bg.top_color[2] * (1 - t) + bg.bottom_color[2] * t)
        draw.line([(0, y), (CARD_SIZE, y)], fill=(r, g, b))
    return image


def _add_bottom_fade(image: Image.Image) -> None:
    overlay = Image.new("RGBA", (CARD_SIZE, CARD_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(CARD_SIZE):
        t = y / (CARD_SIZE - 1)
        alpha = int(220 * (t**1.8))
        draw.line([(0, y), (CARD_SIZE, y)], fill=(0, 0, 0, alpha))
    image.alpha_composite(overlay)


async def render_profile_card(
    interaction_user: discord.abc.User,
    callsign: str,
    title_name: str,
    bio: str,
    level: int,
    xp: int,
    credits: int,
    combat: int,
    tech: int,
    luck: int,
    equipped_weapons: list[str],
    equipped_gadget: str,
    equipped_healing: str,
    background: ProfileBackground,
) -> BytesIO:
    base = _build_background(background).convert("RGBA")
    _add_bottom_fade(base)

    avatar_bytes = await interaction_user.display_avatar.replace(size=256).read()
    avatar_image = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((150, 150))

    mask = Image.new("L", (150, 150), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 149, 149), fill=255)
    avatar_circle = ImageOps.fit(avatar_image, (150, 150))
    avatar_circle.putalpha(mask)
    base.paste(avatar_circle, (38, 56), avatar_circle)

    draw = ImageDraw.Draw(base)
    try:
        name_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 40)
        mid_font = ImageFont.truetype("DejaVuSans.ttf", 28)
        small_font = ImageFont.truetype("DejaVuSans.ttf", 22)
    except OSError:
        name_font = ImageFont.load_default()
        mid_font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    draw.text((38, 32), f"Lv {level}", fill=(255, 255, 255), font=mid_font)
    draw.text((210, 74), callsign, fill=(245, 245, 245), font=name_font)
    draw.text((210, 120), f"{title_name}", fill=(205, 205, 205), font=mid_font)

    current_xp, needed_xp, progress = _xp_progress(xp, level)
    bar_x, bar_y, bar_w, bar_h = 38, 274, CARD_SIZE - 76, 26
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=13, fill=(100, 100, 100, 180))
    filled_width = int(bar_w * progress)
    draw.rounded_rectangle((bar_x, bar_y, bar_x + filled_width, bar_y + bar_h), radius=13, fill=(214, 186, 120, 230))
    draw.text((bar_x + 12, bar_y + 2), "XP", fill=(255, 255, 255), font=small_font)
    draw.text((bar_x, bar_y + 34), f"{current_xp}/{needed_xp}", fill=(236, 236, 236), font=small_font)

    equipped_box = (470, 292, CARD_SIZE - 38, 418)
    draw.rounded_rectangle(equipped_box, radius=14, fill=(132, 149, 201, 210))
    draw.text((486, 300), "Equipment", fill=(255, 255, 255), font=small_font)
    weapon_text = "None"
    if equipped_weapons:
        weapon_text = equipped_weapons[0]
        if len(equipped_weapons) > 1:
            weapon_text = f"{weapon_text} +{len(equipped_weapons) - 1}"
    if len(weapon_text) > 17:
        weapon_text = f"{weapon_text[:14]}..."
    gadget_text = equipped_gadget[:12] + ("..." if len(equipped_gadget) > 12 else "")
    healing_text = equipped_healing[:14] + ("..." if len(equipped_healing) > 14 else "")
    draw.text((486, 328), f"Weapons: {weapon_text}", fill=(255, 255, 255), font=small_font)
    draw.text((486, 356), f"Gadget: {gadget_text}", fill=(255, 255, 255), font=small_font)
    draw.text((486, 384), f"Healing: {healing_text}", fill=(255, 255, 255), font=small_font)

    draw.text((38, 354), "⚔", fill=(255, 255, 255), font=mid_font)
    draw.text((74, 356), f"Combat {combat}", fill=(238, 238, 238), font=mid_font)
    draw.text((38, 396), "⌬", fill=(255, 255, 255), font=mid_font)
    draw.text((74, 398), f"Tech {tech}", fill=(238, 238, 238), font=mid_font)
    draw.text((38, 438), "★", fill=(255, 255, 255), font=mid_font)
    draw.text((74, 440), f"Luck {luck}", fill=(238, 238, 238), font=mid_font)
    draw.text((250, 354), "◈", fill=(255, 255, 255), font=mid_font)
    draw.text((286, 356), f"Scraps {credits}", fill=(238, 238, 238), font=mid_font)

    bio_text = bio[:160]
    draw.text((38, 506), "Bio", fill=(255, 255, 255), font=mid_font)
    draw.multiline_text((38, 540), bio_text, fill=(218, 218, 218), font=small_font, spacing=4)

    out = BytesIO()
    base.convert("RGB").save(out, format="PNG")
    out.seek(0)
    return out
