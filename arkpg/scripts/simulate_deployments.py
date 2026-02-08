from collections import Counter

from arkpg.game.deployments import resolve_deployment


def run_simulation(samples: int = 10_000) -> None:
    rarity = Counter()
    status = Counter()
    for i in range(samples):
        result = resolve_deployment(seed=f"sim-{i}", zone="Industrial", level=20)
        status[result.status] += 1
        for loot in result.loot:
            rarity[loot["rarity"]] += loot["qty"]

    print("Status rates:")
    for key, count in status.items():
        print(f"  {key}: {count/samples:.2%}")
    print("Loot rarity share:")
    total_loot = sum(rarity.values()) or 1
    for key, count in sorted(rarity.items()):
        print(f"  {key}: {count/total_loot:.2%}")


if __name__ == "__main__":
    run_simulation()
