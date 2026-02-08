RARITY_COLORS = {
    "common": 0x808080,
    "uncommon": 0x2ECC71,
    "rare": 0x3498DB,
    "epic": 0x9B59B6,
    "legendary": 0xE67E22,
}

ZONE_CONFIG = {
    "Residential": {"risk": 0.15, "duration_min": 20, "reward_mult": 1.0},
    "Industrial": {"risk": 0.30, "duration_min": 45, "reward_mult": 1.7},
    "ARC Site": {"risk": 0.45, "duration_min": 90, "reward_mult": 2.6},
}

RARITY_WEIGHTS = {
    "Residential": [("common", 60), ("uncommon", 30), ("rare", 10)],
    "Industrial": [("common", 35), ("uncommon", 40), ("rare", 20), ("epic", 5)],
    "ARC Site": [("uncommon", 30), ("rare", 40), ("epic", 22), ("legendary", 8)],
}
