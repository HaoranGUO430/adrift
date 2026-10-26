"""Simulated stream: replay the raw CSV files minute by minute around known tows"""

import time
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DATA = ROOT / "HawaiiCoast_GT"
GROUND_TRUTH = ROOT / "ground_truth" / "ground_truth.csv"
AIS_DATA = RAW_DATA / "AIS_data"

COLUMNS = "MMSI, datetime_utc::VARCHAR AS datetime_utc, lat, lon, speed_over_ground_knots, course_over_ground_deg"
DEMO_INCIDENTS = [
    23,
    122,
    13,
    22,
]  # Example for simulation
MARGIN_MIN = 60  # Period from 60 mins before the tow to 60 mins after
SPEED = 2  # Load data for each min in 0.5 s


def incident_period(incident_num: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Replay period of one example tow.

    Args:
        incident_num: Incident number, e.g. 23.

    Returns:
        Start and end of the replay(min).
    """
    t_start, t_end = duckdb.sql(f"""
        SELECT
            epoch(time_bucket(INTERVAL 1 MINUTE, t_start) - INTERVAL {MARGIN_MIN} MINUTE),
            epoch(time_bucket(INTERVAL 1 MINUTE, t_end) + INTERVAL {MARGIN_MIN + 1} MINUTE)
        FROM read_csv('{GROUND_TRUTH.as_posix()}')
        WHERE incident_num = {incident_num}
    """).fetchone()
    return pd.Timestamp(t_start, unit="s", tz="UTC"), pd.Timestamp(
        t_end, unit="s", tz="UTC"
    )


def replay(
    start: pd.Timestamp, end: pd.Timestamp, speed: float | None = SPEED
) -> Iterator[tuple[pd.Timestamp, pd.DataFrame]]:
    """Replay the raw messages between start and end, one minute at a time.

    Args:
        start: First minute of the replay(min).
        end: Last minute of the replay(min).
        speed: Stream minutes per real second.

    Yields:
        The current stream time `now` and the raw rows that arrived in the minute before it.
    """
    # Find the month file that we want
    months = pd.period_range(start, end - pd.Timedelta(seconds=1), freq="M")
    files = [
        (AIS_DATA / f"Hawaii_{m.year}_{m.month:02d}.csv").as_posix() for m in months
    ]

    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    rows = con.sql(f"""
        SELECT
            {COLUMNS},
            epoch(time_bucket(INTERVAL 1 MINUTE, datetime_utc) + INTERVAL 1 MINUTE)::BIGINT AS arrived_by
        FROM read_csv({files}, header = true, types = {{'MMSI': 'INTEGER', 'datetime_utc': 'TIMESTAMPTZ'}})
        WHERE datetime_utc >= TIMESTAMPTZ '{start}' AND datetime_utc < TIMESTAMPTZ '{end}'
    """).df()

    # Each min for a row in dictionary
    by_minute = dict(tuple(rows.groupby("arrived_by")))

    # Stream simulation
    next_tick = time.monotonic()
    for now in pd.date_range(start + pd.Timedelta(minutes=1), end, freq="min"):
        # sleep + diff(time.monotonic) = 0.5s; run + sleep = 0.5 s
        if speed:
            next_tick += 1 / speed
            time.sleep(max(0, next_tick - time.monotonic()))
        new_rows = by_minute.get(int(now.timestamp()), rows.iloc[:0])
        yield now, new_rows.drop(columns="arrived_by")
