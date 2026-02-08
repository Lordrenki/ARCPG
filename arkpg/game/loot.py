import random
from collections.abc import Sequence

from arkpg.game.constants import RARITY_WEIGHTS


class LootRoller:
    def __init__(self, seed: str):
        self.rng = random.Random(seed)

    def roll_rarity(self, zone: str) -> str:
        options: Sequence[tuple[str, int]] = RARITY_WEIGHTS[zone]
        total = sum(weight for _, weight in options)
        roll = self.rng.uniform(0, total)
        cursor = 0.0
        for rarity, weight in options:
            cursor += weight
            if roll <= cursor:
                return rarity
        return options[-1][0]

    def roll_event(self) -> str:
        events = ["ambush", "arc_echo", "lucky_cache", "teammate_assist", "quiet_run"]
        return self.rng.choice(events)
