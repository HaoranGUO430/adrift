"""Evaluate tow alerts against the ground truth tows"""

from pathlib import Path

import duckdb
import pandas as pd
from functions import wilson

ROOT = Path(__file__).resolve().parents[1]
EPISODES = ROOT / "results" / "tow_episodes.parquet"
GROUND_TRUTH = ROOT / "ground_truth" / "ground_truth.csv"
PAIR_MINUTES = ROOT / "features" / "pair" / "*" / "*.parquet"

LEVELS = {"Low": "low_at", "Mid": "mid_at", "High": "high_at"}
N_DAYS = 1461  # 2017-01-01 to 2020-12-31


def main() -> None:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")

    con.execute(
        f"CREATE TABLE truth AS SELECT * FROM read_csv('{GROUND_TRUTH.as_posix()}', header = true)"
    )

    # Find real towed time by alerts
    con.execute(f"""
        CREATE TABLE alerts AS
        SELECT e.*, g.incident_num
        FROM read_parquet('{EPISODES.as_posix()}') AS e
        LEFT JOIN truth AS g
            ON g.tower = e.tower
            AND g.towed = e.towed
            AND e.first_seen <= g.t_end
            AND e.last_seen >= g.t_start
        WHERE e.is_irregular
    """)

    # First minute both vessels are seen together: start of the delay WITH seen
    # If use t_start in GROUND_TRUTH as incidents start time
    # Incidents occured out of monitored area, delay time meaningless for this project
    con.execute(f"""
        CREATE TABLE seen AS
        SELECT 
            g.incident_num, 
            min(m.minute) AS first_minute
        FROM truth AS g
        JOIN read_parquet('{PAIR_MINUTES.as_posix()}') AS m
            ON m.mmsi_a = least(g.tower, g.towed)
            AND m.mmsi_b = greatest(g.tower, g.towed)
            AND m.minute BETWEEN g.t_start AND g.t_end
        GROUP BY g.incident_num
    """)
    n_incident = con.sql("SELECT count(*) FROM seen").fetchone()[0]

    # Calculate recall and precision
    rows = []
    for level, col in LEVELS.items():
        alerts, correct, detected = con.sql(f"""
            SELECT
                count({col}),
                count({col}) FILTER (WHERE incident_num IS NOT NULL),
                count(DISTINCT incident_num) FILTER (WHERE {col} IS NOT NULL)
            FROM alerts
        """).fetchone()
        mean_delay, median_delay = con.sql(f"""
            SELECT 
                avg(delay_min), 
                median(delay_min)
            FROM (
                SELECT epoch(min(a.{col}) - s.first_minute) / 60 AS delay_min
                FROM alerts AS a
                JOIN seen AS s USING (incident_num)
                WHERE a.{col} >= s.first_minute
                GROUP BY a.incident_num, s.first_minute
            )
        """).fetchone()
        low, high = wilson(detected, n_incident)
        rows.append(
            {
                "level": level,
                "detected": f"{detected}/{n_incident}",
                "recall": round(detected / n_incident, 2),
                "recall_95CI": f"{low:.2f}-{high:.2f}",
                "correct": f"{correct}/{alerts}",
                "precision": round(correct / alerts, 2),
                "alerts_per_day": round(alerts / N_DAYS, 2),
                "delay_mean_min": round(mean_delay),
                "delay_median_min": round(median_delay),
            }
        )
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
