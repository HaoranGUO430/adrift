"""Stream alerts: irregular tow windows of one minute in, alert events out"""

import pandas as pd

# SQL basic rules
MAX_MERGE_GAP_MIN = 15
STEP_MIN = 1
# New rules
MAX_GAP_S = (MAX_MERGE_GAP_MIN + STEP_MIN) * 60  # a longer break starts a new episode
LEVELS = {15: "Low", 30: "Mid", 60: "High"}


def update(episodes: dict, irregular: pd.DataFrame, minute: int) -> list[tuple]:
    """Open, close, update the alert level of one minute.

    Args:
        episodes: Open episodes per (tower, towed).
        irregular: Irregular tow windows of this minute.
        minute: The minute (epoch s) these windows end at.

    Returns:
        Alert events is "Low", "Mid", "High" or "end".
    """
    events = []

    # 1. Close the episodes whose break is now too long to continue
    for pair, episode in list(episodes.items()):
        if minute - episode["last_seen"] > MAX_GAP_S:
            if "Low" in episode:
                events.append((minute, *pair, "end"))
            del episodes[pair]

    # 2. Continue or start an episode for each pair seen at this minute
    longest = irregular.groupby(["tower", "towed"])["window_min"].max()
    for pair, window_min in longest.items():
        episode = episodes.setdefault(pair, {"first_seen": minute})
        episode["last_seen"] = minute
        # 3. Raise the alert level the first time a longer window holds
        for length, level in LEVELS.items():
            if window_min >= length and level not in episode:
                episode[level] = minute
                events.append((minute, *pair, level))
    return events
