from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class TitleRule:
    id: str
    name: str
    description: str
    category: str
    rarity: str
    how_to_earn: str
    is_hidden: bool
    progress_fn: Callable[[dict], float]
    complete_fn: Callable[[dict], bool]


def _counter_progress(counter: str, target: int):
    return (
        lambda p: min(100.0, (float(p.get(counter, 0)) / float(target)) * 100.0),
        lambda p: int(p.get(counter, 0)) >= target,
    )


def build_title_rules() -> list[TitleRule]:
    defs = [
        ("raider_first_blood", "First Footfall", "Clear your first deployment.", "Raider", "common", "Complete 1 deployment clear.", False, "raid_clears", 1),
        ("raider_25", "Dustrunner", "Clear 25 deployments.", "Raider", "uncommon", "Complete 25 deployments.", False, "raid_clears", 25),
        ("raider_100", "Zone Cartographer", "Clear 100 deployments.", "Raider", "epic", "Complete 100 deployments.", False, "raid_clears", 100),
        ("extract_5_streak", "Steady Hands", "Extract 5 times in a row.", "Raider", "rare", "Reach extraction streak 5.", False, "extract_streak", 5),
        ("extract_20_streak", "Untouchable", "Extract 20 times in a row.", "Raider", "legendary", "Reach extraction streak 20.", False, "extract_streak", 20),
        ("crafter_10", "Workbench Spark", "Craft 10 items.", "Crafter", "common", "Craft 10 items.", False, "crafted", 10),
        ("crafter_100", "Systems Artisan", "Craft 100 items.", "Crafter", "epic", "Craft 100 items.", False, "crafted", 100),
        ("scrapper_100", "Recycler", "Scrap 100 items.", "Crafter", "uncommon", "Scrap 100 items.", False, "scrapped", 100),
        ("scrapper_1000", "Furnace Whisperer", "Scrap 1000 items.", "Crafter", "legendary", "Scrap 1000 items.", False, "scrapped", 1000),
        ("trade_5", "Handshake", "Complete 5 safe trades.", "Trader", "common", "Complete 5 confirmed trades.", False, "trade_completed", 5),
        ("trade_50", "Quartermaster", "Complete 50 safe trades.", "Trader", "epic", "Complete 50 confirmed trades.", False, "trade_completed", 50),
        ("exp_donor_1k", "Supply Mule", "Earn 1,000 expedition score.", "Expedition", "uncommon", "Contribute score 1,000.", False, "expedition_score", 1000),
        ("exp_donor_20k", "Convoy Anchor", "Earn 20,000 expedition score.", "Expedition", "legendary", "Contribute score 20,000.", False, "expedition_score", 20000),
        ("exp_depart_1", "Departure Confirmed", "Depart once.", "Expedition", "rare", "Use /expedition depart once.", False, "expeditions_departed", 1),
        ("exp_depart_5", "Long Hauler", "Depart five expeditions.", "Expedition", "legendary", "Depart 5 expedition seasons.", False, "expeditions_departed", 5),
        ("squad_join", "Wingmate", "Join a squad.", "Squad", "common", "Join any squad.", False, "squad_joins", 1),
        ("squad_mission_10", "Formation Keeper", "Finish 10 squad-tagged activities.", "Squad", "rare", "Complete 10 squad operations.", False, "squad_ops", 10),
        ("pvp_1", "Challenger", "Win one duel.", "PvP", "common", "Win 1 duel.", False, "pvp_wins", 1),
        ("pvp_25", "Arena Regular", "Win 25 duels.", "PvP", "epic", "Win 25 duels.", False, "pvp_wins", 25),
        ("pvp_fair_10", "Code of Honor", "Win 10 fair-band duels.", "PvP", "rare", "Win 10 duels within level band.", False, "pvp_fair_wins", 10),
        ("collector_common_50", "Stockroom Starter", "Own 50 common items in stash.", "Collector", "common", "Hold 50 common items at once.", False, "collect_common_owned", 50),
        ("collector_rare_20", "Rare Curator", "Own 20 rare items in stash.", "Collector", "rare", "Hold 20 rare items at once.", False, "collect_rare_owned", 20),
        ("collector_legendary_5", "Golden Shelf", "Own 5 legendary items in stash.", "Collector", "legendary", "Hold 5 legendary items at once.", False, "collect_legendary_owned", 5),
        ("quest_ch1", "Chapter I Complete", "Complete chapter 1.", "Events", "uncommon", "Finish chapter 1 quests.", False, "quest_chapter_1", 1),
        ("quest_chapter_3", "Chapter III Complete", "Complete chapter 3.", "Events", "rare", "Finish chapter 3 quests.", False, "quest_chapter_3", 1),
        ("quest_ch5", "Storyline Vanguard", "Complete chapter 5.", "Events", "legendary", "Finish chapter 5 quests.", False, "quest_chapter_5", 1),
        ("scavenge_25", "Side Street Scout", "Complete 25 scavenges.", "Raider", "uncommon", "Use /scavenge 25 times.", False, "scavenge_runs", 25),
        ("salvage_25", "Bench Salvager", "Complete 25 salvage ops.", "Crafter", "uncommon", "Use /salvage 25 times.", False, "salvage_runs", 25),
        ("courier_25", "Courier Route", "Complete 25 courier runs.", "Trader", "uncommon", "Use /courier 25 times.", False, "courier_runs", 25),
        ("event_founder", "Outpost Founder", "Reach level 20.", "Events", "rare", "Reach level 20.", False, "level", 20),
        ("event_veteran", "Frontier Veteran", "Reach level 50.", "Events", "legendary", "Reach level 50.", False, "level", 50),
        ("hidden_last_hp", "Thread the Needle", "Extract after surviving at 1 health.", "Events", "epic", "Extract with critical health.", True, "hidden_last_hp", 1),
        ("hidden_trinket", "Pocket Universe", "Scrap absurd quantities of trinkets.", "Collector", "epic", "Scrap 777 trinket-class items.", True, "hidden_trinket_scrap", 777),
        ("hidden_nightshift", "Night Shift", "Complete 3 courier failures then a success.", "Trader", "rare", "Persist through 3 failed courier runs then win.", True, "hidden_courier_comeback", 1),
        ("hidden_empty_extract", "Bare Hands", "Extract with no loot.", "Raider", "rare", "Successfully extract while carrying nothing.", True, "hidden_empty_extract", 1),
        ("hidden_arc_echo", "Echo Listener", "Trigger the arc_echo event 7 times.", "Events", "epic", "Encounter arc echoes repeatedly.", True, "arc_echo", 7),
        ("hidden_silent_trade", "Silent Broker", "Complete 10 trades in one day.", "Trader", "epic", "Complete 10 trades within 24 hours.", True, "hidden_trade_day", 10),
        ("hidden_zero_credit", "All In", "Depart expedition with zero credits remaining.", "Expedition", "legendary", "Depart while broke.", True, "hidden_zero_credit_depart", 1),
        ("hidden_salvage_jackpot", "Refinery Luck", "Hit 5 salvage jackpots.", "Crafter", "epic", "Roll refined material jackpot five times.", True, "hidden_salvage_jackpot", 5),
        ("hidden_scavenge_chain", "Back-Alley Oracle", "Roll 5 mini events in a row.", "Raider", "legendary", "Trigger 5 scavenge mini-events consecutively.", True, "hidden_scavenge_chain", 1),
        ("hidden_true_neutral", "Diplomatic Ghost", "Trade and duel same opponent in one hour.", "Squad", "rare", "Complete duel+trade with same target quickly.", True, "hidden_duel_trade_combo", 1),
        ("hidden_depart_early", "Early Seat", "Depart in first 10% of departure window.", "Expedition", "rare", "Depart very early in window.", True, "hidden_depart_early", 1),
    ]
    out: list[TitleRule] = []
    for item in defs:
        id_, name, description, cat, rarity, how, hidden, counter, target = item
        pfn, cfn = _counter_progress(counter, target)
        out.append(TitleRule(id_, name, description, cat, rarity, how, hidden, pfn, cfn))
    return out


TITLE_RULES = build_title_rules()
TITLE_RULE_MAP = {r.id: r for r in TITLE_RULES}
