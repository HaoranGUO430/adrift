"""Calculate and judge the feature for single and paied vessel(s) in windows"""

from pathlib import Path

import duckdb
from functions import haversine

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "features"

RUN_CHECK = True
YEARS = [2017, 2018]
WINDOW_LENGTHS = [
    5,
    15,
    30,
    60,
]  # 4 type of window, 5 -> ezist for streaming to find out, 60 -> relation most reliable
STEP_MIN = 5
TOLERANCE_DEG = 45  # Judge if a or b is behind


def main() -> None:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute(haversine())

    for year in YEARS:
        minute_src = (
            FEATURES / "minute" / f"year={year}" / "minute.parquet"
        ).as_posix()
        pair_src = (
            FEATURES / "pair" / f"year={year}" / "pair_minute.parquet"
        ).as_posix()

        for window_min in WINDOW_LENGTHS:
            vessel_dir = (
                FEATURES / "vessel_window" / f"window_min={window_min}" / f"year={year}"
            )
            pair_dir = (
                FEATURES / "pair_window" / f"window_min={window_min}" / f"year={year}"
            )
            vessel_dir.mkdir(parents=True, exist_ok=True)
            pair_dir.mkdir(parents=True, exist_ok=True)
            vessel_out = (vessel_dir / "vessel_window.parquet").as_posix()
            pair_out = (pair_dir / "pair_window.parquet").as_posix()

            # Study features for single vessel in windows
            # List feature for single vessel compare woth 1 min ago WITH steps
            # Classify each row into correspond window WITH windows
            # Aggregate data for same vessel and time window WITH agg
            # sin & cos ez to calculate (1 degree and 359 degree)
            con.execute(f"""
                COPY (
                    WITH steps AS (
                        SELECT
                            *,
                            lag(minute) OVER w AS prev_minute,
                            haversine(lag(lat) OVER w, lag(lon) OVER w, lat, lon) AS step_m
                        FROM read_parquet('{minute_src}')
                        WINDOW w AS (PARTITION BY mmsi ORDER BY minute)
                    ),
                    windows AS (
                        SELECT
                            *,
                            unnest(generate_series(
                                time_bucket(INTERVAL {STEP_MIN} MINUTE, minute) - INTERVAL {window_min - STEP_MIN} MINUTE,
                                time_bucket(INTERVAL {STEP_MIN} MINUTE, minute),
                                INTERVAL {STEP_MIN} MINUTE
                            )) AS window_start
                        FROM steps
                    ),
                    agg AS (
                        SELECT
                            mmsi,
                            window_start,
                            count(*) AS n_min,
                            avg(sog) AS mean_sog,
                            stddev_pop(sog) AS sd_sog,
                            avg(sin(radians(cog))) AS mean_sin,
                            avg(cos(radians(cog))) AS mean_cos,
                            haversine(
                                arg_min(lat, minute), arg_min(lon, minute),
                                arg_max(lat, minute), arg_max(lon, minute)
                            ) AS displacement_m,
                            sum(step_m) FILTER (WHERE prev_minute >= window_start) AS path_m
                        FROM windows
                        GROUP BY mmsi, window_start
                    )
                    SELECT
                        mmsi,
                        {window_min} AS window_min,
                        window_start,
                        window_start + INTERVAL {window_min} MINUTE AS window_end,
                        n_min,
                        mean_sog,
                        sd_sog,
                        (degrees(atan2(mean_sin, mean_cos)) + 360) % 360 AS mean_cog,
                        sqrt(mean_sin * mean_sin + mean_cos * mean_cos) AS cog_R,
                        displacement_m,
                        displacement_m / nullif(path_m, 0) AS linear_displacement
                    FROM agg
                    ORDER BY window_end
                ) TO '{vessel_out}' (FORMAT parquet, COMPRESSION zstd)
            """)

            # Study features for paired vessels in windows
            # Classify each paired row into correspond window WITH windows
            # Calculate the proportion of time if a is behind b with frac_a_astern_of_b == 1
            con.execute(f"""
                COPY (
                    WITH windows AS (
                        SELECT
                            *,
                            unnest(generate_series(
                                time_bucket(INTERVAL {STEP_MIN} MINUTE, minute) - INTERVAL {window_min - STEP_MIN} MINUTE,
                                time_bucket(INTERVAL {STEP_MIN} MINUTE, minute),
                                INTERVAL {STEP_MIN} MINUTE
                            )) AS window_start
                        FROM read_parquet('{pair_src}')
                    )
                    SELECT
                        mmsi_a,
                        mmsi_b,
                        {window_min} AS window_min,
                        window_start,
                        window_start + INTERVAL {window_min} MINUTE AS window_end,
                        count(*) AS n_min,
                        avg(distance_m) AS mean_distance_m,
                        max(distance_m) AS max_distance_m,
                        avg(sog_diff) AS mean_sog_diff,
                        avg(cog_diff) AS mean_cog_diff,
                        avg((abs(a_rel_to_b - 180) <= {TOLERANCE_DEG})::INT) AS frac_a_astern_of_b,
                        avg((abs(b_rel_to_a - 180) <= {TOLERANCE_DEG})::INT) AS frac_b_astern_of_a,
                        max(max_gap_s) AS max_gap_s
                    FROM windows
                    GROUP BY mmsi_a, mmsi_b, window_start
                    ORDER BY window_end
                ) TO '{pair_out}' (FORMAT parquet, COMPRESSION zstd)
            """)

            if RUN_CHECK:
                con.sql(f"""
                    SELECT
                        {year} AS year,
                        {window_min} AS window_min,
                        (SELECT count(*) FROM read_parquet('{minute_src}')) * {window_min // STEP_MIN} AS expected_vessel,
                        (SELECT sum(n_min) FROM read_parquet('{vessel_out}')) AS vessel,
                        (SELECT count(*) FROM read_parquet('{pair_src}')) * {window_min // STEP_MIN} AS expected_pair,
                        (SELECT sum(n_min) FROM read_parquet('{pair_out}')) AS pair
                """).show()


if __name__ == "__main__":
    main()
