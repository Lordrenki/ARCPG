from __future__ import annotations

from io import BytesIO

import discord
from PIL import Image, ImageDraw, ImageFont, ImageOps

from arkpg.game.economy import xp_for_level
from arkpg.game.profile_backgrounds import ProfileBackground

CARD_SIZE = 720


def _xp_progress(user_xp: int, level: int) -> tuple[int, int, float]:
    current_level_floor = xp_for_level(level)
    next_level_floor = xp_for_level(level + 1)
    needed_total = max(1, next_level_floor - current_level_floor)
    current_into_level = max(0, min(user_xp - current_level_floor, needed_total))
    progress = max(0.0, min(current_into_level / needed_total, 1.0))
    return current_into_level, needed_total, progress


def _build_background(bg: ProfileBackground) -> Image.Image:
    if bg.image_path:
        try:
            return Image.open(bg.image_path).convert("RGB").resize((CARD_SIZE, CARD_SIZE))
        except OSError:
            pass
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
    equipped_shield: str,
    health: int,
    max_health: int,
    background: ProfileBackground,
    admin_background_path: str | None = None,
) -> BytesIO:
    base = _build_background(background).convert("RGBA")
    if admin_background_path:
        try:
            admin_bg = Image.open(admin_background_path).convert("RGBA").resize((CARD_SIZE, CARD_SIZE))
            base = admin_bg
        except OSError:
            pass
    _add_bottom_fade(base)

    card_mask = Image.new("L", (CARD_SIZE, CARD_SIZE), 0)
    ImageDraw.Draw(card_mask).rounded_rectangle((0, 0, CARD_SIZE - 1, CARD_SIZE - 1), radius=34, fill=255)
    rounded = Image.new("RGBA", (CARD_SIZE, CARD_SIZE), (0, 0, 0, 0))
    rounded.paste(base, (0, 0), card_mask)
    base = rounded

    avatar_bytes = await interaction_user.display_avatar.replace(size=256).read()
    avatar_image = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((140, 140))

    mask = Image.new("L", (140, 140), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 139, 139), fill=255)
    avatar_circle = ImageOps.fit(avatar_image, (140, 140))
    avatar_circle.putalpha(mask)
    base.paste(avatar_circle, (38, 170), avatar_circle)

    draw = ImageDraw.Draw(base)
    try:
        name_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 50)
        mid_font = ImageFont.truetype("DejaVuSans.ttf", 28)
        mid_bold_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 30)
        small_font = ImageFont.truetype("DejaVuSans.ttf", 22)
    except OSError:
        name_font = ImageFont.load_default()
        mid_font = ImageFont.load_default()
        mid_bold_font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    draw.text((38, 30), f"Lv {level}", fill=(255, 255, 255), font=mid_bold_font)
    draw.text((210, 196), callsign, fill=(245, 245, 245), font=name_font)
    title_color = (72, 176, 255) if title_name == "ARCPG Staff Team" else (205, 205, 205)
    draw.text((210, 252), f"{title_name}", fill=title_color, font=mid_font)

    current_xp, needed_xp, progress = _xp_progress(xp, level)
    xp_x, bar_y, xp_w, bar_h = 38, 330, 420, 54
    equipped_x, equipped_w = 480, CARD_SIZE - 38 - 480

    draw.rounded_rectangle((xp_x, bar_y, xp_x + xp_w, bar_y + bar_h), radius=14, fill=(110, 110, 110, 170))
    fill_inset = 4
    inner_w = xp_w - (fill_inset * 2)
    filled_width = max(0, int(inner_w * progress))
    if filled_width > 0:
        draw.rounded_rectangle((xp_x + fill_inset, bar_y + fill_inset, xp_x + fill_inset + filled_width, bar_y + bar_h - fill_inset), radius=10, fill=(214, 186, 120, 235))
    draw.text((xp_x + 12, bar_y + 12), "XP", fill=(255, 255, 255), font=mid_bold_font)
    draw.text((xp_x + xp_w - 180, bar_y + 12), f"{current_xp}/{needed_xp}", fill=(240, 240, 240), font=mid_bold_font)

    hp_ratio = max(0.0, min(float(health) / max(1, float(max_health)), 1.0))
    hp_color = (55, 199, 112, 230)
    if hp_ratio < 0.25:
        hp_color = (215, 63, 63, 230)
    elif hp_ratio < 0.5:
        hp_color = (234, 134, 44, 230)
    elif hp_ratio < 0.75:
        hp_color = (227, 207, 56, 230)

    hp_x, hp_w = equipped_x, equipped_w
    draw.rounded_rectangle((hp_x, bar_y, hp_x + hp_w, bar_y + bar_h), radius=14, fill=(95, 95, 95, 180))
    hp_inner = hp_w - (fill_inset * 2)
    hp_filled = max(0, int(hp_inner * hp_ratio))
    if hp_filled > 0:
        draw.rounded_rectangle((hp_x + fill_inset, bar_y + fill_inset, hp_x + fill_inset + hp_filled, bar_y + bar_h - fill_inset), radius=10, fill=hp_color)
    draw.text((hp_x + 12, bar_y + 12), "HP", fill=(255, 255, 255), font=mid_bold_font)
    draw.text((hp_x + hp_w - 110, bar_y + 12), f"{health}/100", fill=(240, 240, 240), font=mid_bold_font)

    equipped_title_y = bar_y + bar_h + 18
    draw.rounded_rectangle((equipped_x, equipped_title_y, equipped_x + equipped_w, equipped_title_y + bar_h), radius=14, fill=(132, 149, 201, 210))
    equipped_label = "Equipped"
    label_box = draw.textbbox((0, 0), equipped_label, font=mid_bold_font)
    label_w = label_box[2] - label_box[0]
    label_h = label_box[3] - label_box[1]
    draw.text((equipped_x + (equipped_w - label_w) / 2, equipped_title_y + (bar_h - label_h) / 2 - 2), equipped_label, fill=(255, 255, 255), font=mid_bold_font)

    if equipped_weapons:
        weapon_text = equipped_weapons[0]
        if len(equipped_weapons) > 1:
            weapon_text = f"{weapon_text} +{len(equipped_weapons) - 1}"
    else:
        weapon_text = "None"

    def _trim(value: str, size: int) -> str:
        return value[: size - 3] + "..." if len(value) > size else value

    info_y = equipped_title_y + bar_h + 18
    draw.text((equipped_x + 6, info_y), f"Weapon: {_trim(weapon_text, 17)}", fill=(255, 255, 255), font=small_font)
    draw.text((equipped_x + 6, info_y + 30), f"Gadget: {_trim(equipped_gadget or 'None', 17)}", fill=(255, 255, 255), font=small_font)
    draw.text((equipped_x + 6, info_y + 60), f"Healing: {_trim(equipped_healing or 'None', 16)}", fill=(255, 255, 255), font=small_font)
    draw.text((equipped_x + 6, info_y + 90), f"Shield: {_trim(equipped_shield or 'None', 17)}", fill=(255, 255, 255), font=small_font)

    draw.text((38, 410), "⚔", fill=(255, 255, 255), font=mid_font)
    draw.text((74, 412), f"Combat {combat}", fill=(238, 238, 238), font=mid_font)
    draw.text((38, 452), "⌬", fill=(255, 255, 255), font=mid_font)
    draw.text((74, 454), f"Tech {tech}", fill=(238, 238, 238), font=mid_font)
    draw.text((38, 494), "★", fill=(255, 255, 255), font=mid_font)
    draw.text((74, 496), f"Luck {luck}", fill=(238, 238, 238), font=mid_font)
    draw.text((250, 410), "◈", fill=(255, 255, 255), font=mid_font)
    draw.text((286, 412), f"Scraps {credits}", fill=(238, 238, 238), font=mid_font)

    bio_text = bio[:160]
    draw.text((38, 560), "Bio", fill=(255, 255, 255), font=mid_font)
    draw.multiline_text((38, 595), bio_text, fill=(218, 218, 218), font=small_font, spacing=4)

    out = BytesIO()
    base.save(out, format="PNG")
    out.seek(0)
    return out
