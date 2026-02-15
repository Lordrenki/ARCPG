from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

RaidAction = Literal["attack", "dodge", "heal", "retreat"]

ENEMY_ARCHETYPES = [
    "Apex Stalker",
    "Titan Reclaimer",
    "Void Marauder",
    "Overclocked Juggernaut",
    "Sable Warmind",
    "Riftbound Warden",
]

OPENING_FLAVOR = [
    "Thunder rips across ruined towers as a signal flare marks your target.",
    "A blacksite siren blares once, then silence. Something massive moves in the smoke.",
    "Your visor fogs from heat vents while a high-level contact pings nearby.",
    "A cracked loudspeaker mutters evacuation warnings as your raid target steps into view.",
]

PLAYER_ATTACK_FLAVOR = [
    "You squeeze the trigger and drive forward through flying debris.",
    "You commit to an aggressive push and force the enemy off balance.",
    "You thread a burst through armor seams.",
]

ENEMY_ATTACK_FLAVOR = [
    "The enemy counters with a brutal swing.",
    "A heavy burst tears through cover and pressure mounts.",
    "The target lunges with frightening speed.",
]

DODGE_FLAVOR = [
    "You read the wind-up and slip outside the strike lane.",
    "You dive behind fractured plating just in time.",
    "A quick sidestep keeps you alive by inches.",
]

HEAL_FLAVOR = [
    "You slam an injector and steady your breathing.",
    "Field foam seals the worst injuries.",
    "You patch armor leaks while the target repositions.",
]


@dataclass(slots=True)
class RaidEnemy:
    name: str
    level: int
    max_hp: int
    hp: int
    min_damage: int
    max_damage: int


@dataclass(slots=True)
class RaidState:
    player_level: int
    player_max_hp: int
    player_hp: int
    enemy: RaidEnemy
    heals_left: int = 2
    turn: int = 1
    consecutive_dodges: int = 0


@dataclass(slots=True)
class RaidTurnResult:
    lines: list[str]
    raid_over: bool
    player_won: bool


def generate_enemy(player_level: int, rng: random.Random) -> RaidEnemy:
    level = max(player_level + rng.randint(4, 10), 8)
    hp = rng.randint(95, 140) + (level * 5)
    return RaidEnemy(
        name=f"{rng.choice(ENEMY_ARCHETYPES)} Lv.{level}",
        level=level,
        max_hp=hp,
        hp=hp,
        min_damage=max(10, int(level * 0.9)),
        max_damage=max(17, int(level * 1.4)),
    )


def begin_raid(
    player_level: int,
    player_hp: int,
    player_max_hp: int,
    rng: random.Random,
) -> tuple[RaidState, str]:
    enemy = generate_enemy(player_level, rng)
    state = RaidState(
        player_level=player_level,
        player_max_hp=max(40, player_max_hp),
        player_hp=max(1, player_hp),
        enemy=enemy,
    )
    opening = rng.choice(OPENING_FLAVOR)
    return state, opening


def _roll_player_attack(state: RaidState, rng: random.Random) -> tuple[str, int]:
    hit = rng.random() <= 0.82
    if not hit:
        return "Your volley misses as the target drifts out of sight.", 0
    base = rng.randint(14, 24) + int(state.player_level * 1.6)
    crit = rng.random() <= 0.2
    dmg = int(base * 1.65) if crit else base
    return (
        f"{rng.choice(PLAYER_ATTACK_FLAVOR)} {'Critical hit!' if crit else ''} (-{dmg} HP)",
        dmg,
    )


def _roll_enemy_attack(state: RaidState, rng: random.Random, dodge_active: bool) -> tuple[str, int]:
    if dodge_active:
        dodge_chance = max(0.2, 0.62 - (0.14 * state.consecutive_dodges))
        if rng.random() <= dodge_chance:
            return f"{rng.choice(DODGE_FLAVOR)} You avoid all damage.", 0
        hit = rng.random() <= 0.92
        if not hit:
            return "You overcommit to a dodge, but the enemy still whiffs wide.", 0

        dmg = int(rng.randint(state.enemy.min_damage, state.enemy.max_damage) * 1.2)
        return f"You try to dodge, but the enemy reads your movement. (-{dmg} HP)", dmg

    hit = rng.random() <= 0.86
    if not hit:
        return "The enemy overextends and misses wide.", 0

    dmg = rng.randint(state.enemy.min_damage, state.enemy.max_damage)
    return f"{rng.choice(ENEMY_ATTACK_FLAVOR)} (-{dmg} HP)", dmg


def resolve_action(state: RaidState, action: RaidAction, rng: random.Random, can_heal: bool = True) -> RaidTurnResult:
    lines: list[str] = [f"**Turn {state.turn}**"]

    if action == "retreat":
        lines.append("You pop smoke and retreat from the raid zone.")
        return RaidTurnResult(lines=lines, raid_over=True, player_won=False)

    dodge_active = action == "dodge"
    if dodge_active:
        state.consecutive_dodges += 1
    else:
        state.consecutive_dodges = 0

    if action == "attack":
        attack_line, dealt = _roll_player_attack(state, rng)
        state.enemy.hp = max(0, state.enemy.hp - dealt)
        lines.append(attack_line)
    elif action == "heal":
        if state.heals_left <= 0:
            lines.append("Your med reserves are dry. No healing applied.")
        elif not can_heal:
            lines.append("You have no bandages in your inventory. Healing failed.")
        else:
            heal_amt = rng.randint(22, 38)
            before = state.player_hp
            state.player_hp = min(state.player_max_hp, state.player_hp + heal_amt)
            state.heals_left -= 1
            lines.append(f"{rng.choice(HEAL_FLAVOR)} (+{state.player_hp - before} HP)")
    else:
        lines.append(f"{rng.choice(DODGE_FLAVOR)} You brace for the counter.")

    if state.enemy.hp <= 0:
        lines.append("Target neutralized. The raid zone falls quiet.")
        return RaidTurnResult(lines=lines, raid_over=True, player_won=True)

    enemy_line, incoming = _roll_enemy_attack(state, rng, dodge_active=dodge_active)
    lines.append(enemy_line)
    if incoming > 0:
        state.player_hp = max(0, state.player_hp - incoming)

    if state.player_hp <= 0:
        lines.append("You collapse under sustained fire. Raid failed.")
        return RaidTurnResult(lines=lines, raid_over=True, player_won=False)

    state.turn += 1
    return RaidTurnResult(lines=lines, raid_over=False, player_won=False)


def raid_rewards(enemy_level: int, rng: random.Random) -> tuple[int, int]:
    xp = rng.randint(40, 75) + int(enemy_level * 1.25)
    scrap = rng.randint(180, 340) + enemy_level * 5
    return xp, scrap


def strip_equipped_loadout(loadout: dict | None) -> tuple[dict, list[str]]:
    normalized = dict(loadout or {})
    lost_names: list[str] = []

    for weapon in [w for w in (normalized.get("weapons") or []) if w]:
        lost_names.append(str(weapon.get("name") or "Unknown weapon"))
    for slot in ("gadget", "healing", "shield"):
        payload = normalized.get(slot)
        if payload:
            lost_names.append(str(payload.get("name") or f"Unknown {slot}"))

    return ({"weapons": [], "gadget": None, "healing": None, "shield": None}, lost_names)


def should_lose_gear_on_raid_failure(player_hp: int) -> bool:
    return player_hp <= 0
