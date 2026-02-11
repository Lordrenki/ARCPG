RARITY_COLORS = {
    "common": 0x808080,
    "uncommon": 0x2ECC71,
    "rare": 0x3498DB,
    "epic": 0x9B59B6,
    "legendary": 0xE67E22,
}

ZONE_CONFIG = {
    "Residential": {"risk": 0.15, "duration_min": 20, "reward_mult": 1.15},
    "Industrial": {"risk": 0.30, "duration_min": 45, "reward_mult": 1.95},
    "ARC Site": {"risk": 0.45, "duration_min": 90, "reward_mult": 3.1},
}

RARITY_WEIGHTS = {
    "Residential": [("common", 52), ("uncommon", 34), ("rare", 12), ("epic", 2)],
    "Industrial": [("common", 28), ("uncommon", 38), ("rare", 24), ("epic", 9), ("legendary", 1)],
    "ARC Site": [("common", 8), ("uncommon", 22), ("rare", 38), ("epic", 24), ("legendary", 8)],
}
