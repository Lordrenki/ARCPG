from __future__ import annotations

from dataclasses import dataclass
import random


@dataclass(frozen=True)
class BossTemplate:
    name: str
    archetype: str
    hp_range: tuple[int, int]
    intro: str


BOSS_TEMPLATES: tuple[BossTemplate, ...] = (
    BossTemplate(
        name="Bastion Siege Walker",
        archetype="Heavy ARC war machine",
        hp_range=(3200, 5200),
        intro="A Bastion unit stomps into the district, deploying suppression shields and rotary cannons.",
    ),
    BossTemplate(
        name="Warden Null",
        archetype="Command-and-control ARC core",
        hp_range=(2800, 4800),
        intro="Warden Null descends from orbit and begins tagging raiders for elimination.",
    ),
    BossTemplate(
        name="Hornet Carrier",
        archetype="Aerial ARC hive",
        hp_range=(2600, 4300),
        intro="A Hornet Carrier tears through the clouds, launching drone swarms toward scavenger positions.",
    ),
    BossTemplate(
        name="Strider Reaper",
        archetype="Long-range ARC execution platform",
        hp_range=(3400, 5600),
        intro="A Strider Reaper locks the zone with artillery-grade rail fire.",
    ),
)

FLAVOR_CRITS = (
    "{user} landed a critical hit on **{boss}**.",
    "{user} exposed a weak point and chunks armor plating off **{boss}**.",
    "{user} overcharged their weapon and scorched **{boss}**.",
)

FLAVOR_SUPPORT = (
    "{user} coordinates target telemetry for the whole squad.",
    "{user} keeps pressure with suppressing fire.",
    "{user} reroutes power and stabilizes their weapon platform.",
)

FLAVOR_DAMAGE = (
    "{user} gets clipped by shrapnel (-{damage} HP).",
    "{user} is hit by shockwave backblast (-{damage} HP).",
    "{user} is caught in crossfire (-{damage} HP).",
)


@dataclass
class BossSpawn:
    name: str
    archetype: str
    intro: str
    max_hp: int



def random_boss(rng: random.Random) -> BossSpawn:
    template = rng.choice(BOSS_TEMPLATES)
    return BossSpawn(
        name=template.name,
        archetype=template.archetype,
        intro=template.intro,
        max_hp=rng.randint(*template.hp_range),
    )



def weighted_damage_roll(rng: random.Random, rating: float) -> int:
    floor = 18 + int(rating * 2.2)
    ceiling = 65 + int(rating * 4.8)
    return rng.randint(max(8, floor), max(floor + 2, ceiling))
