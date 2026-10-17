"""Rule-based tow detection on sliding pair windows (definition fixed in README)"""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
PAIR_WINDOWS = ROOT / "features" / "pair_window" / "*" / "*" / "*.parquet"
VESSELS = ROOT / "clean_data" / "vessels.parquet"
RESULTS = ROOT / "results"

RUN_CHECK = True
STEP_MIN = 1  # simulate streaming each min has a window
MIN_COVERAGE = 0.6  # minimum proportion that window is valid
MAX_SD_DISTANCE_M = 10
MAX_MEAN_DISTANCE_M = 1000
MIN_FRAC_ASTERN = 0.9  # minimum proportion of time that a is behind of b
SHIP_MMSI = (200000000, 799999999)  # ITU-R M.585: ship MMSIs start with 2-7
MAX_MERGE_GAP_MIN = 15  # a break up to 15 min does not split a tow
IRREGULAR_CLASSES = ("Fishing", "Pleasure Craft/Sailing", "Industrial Vessel")


def main() -> None:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")

    # Judge which vessel is towed/tower, sailing away back to back return NULL
    # Select valid pairs in condition(rules)
    con.execute(f"""
        CREATE TABLE tow_windows AS
        WITH roles AS (
            SELECT
                *,
                CASE
                    WHEN frac_a_astern_of_b >= {MIN_FRAC_ASTERN} AND frac_b_astern_of_a < {MIN_FRAC_ASTERN} THEN mmsi_a
                    WHEN frac_b_astern_of_a >= {MIN_FRAC_ASTERN} AND frac_a_astern_of_b < {MIN_FRAC_ASTERN} THEN mmsi_b
                END AS towed,
                CASE towed 
                    WHEN mmsi_a THEN mmsi_b 
                    WHEN mmsi_b THEN mmsi_a 
                END AS tower
            FROM read_parquet('{PAIR_WINDOWS.as_posix()}')
        )
        SELECT
            tower,
            towed,
            window_min,
            window_end,
            mean_distance_m,
            sd_distance_m,
            max_gap_s
        FROM roles
        WHERE towed IS NOT NULL
            AND n_min >= {MIN_COVERAGE} * window_min
            AND sd_distance_m <= {MAX_SD_DISTANCE_M}
            AND mean_distance_m <= {MAX_MEAN_DISTANCE_M}
            AND tower BETWEEN {SHIP_MMSI[0]} AND {SHIP_MMSI[1]}
            AND towed BETWEEN {SHIP_MMSI[0]} AND {SHIP_MMSI[1]}
    """)

    # Calculate longest window minute for danger level
    con.execute("""
        CREATE TABLE levels AS
        SELECT
            tower,
            towed,
            window_end,
            max(window_min) AS longest_window_min,
            avg(mean_distance_m) FILTER (WHERE window_min = 5) AS distance_m,
            avg(sd_distance_m) FILTER (WHERE window_min = 5) AS sd_distance_m,
            max(max_gap_s) AS max_gap_s
        FROM tow_windows
        GROUP BY tower, towed, window_end
    """)

    # Calculate gap min for each row to find out time of break WITH gaps
    # Number the interval with no break in same episode id WITH numbered
    # Aggragate same episode WITH agg
    # is_irregular judge the type of towed vessel
    # large vessel with tower vessel to stop in habor is nomal
    con.execute(f"""
        CREATE TABLE episodes AS
        WITH gaps AS (
            SELECT
                *,
                window_end - lag(window_end) OVER (PARTITION BY tower, towed ORDER BY window_end) AS gap
            FROM levels
        ),
        numbered AS (
            SELECT
                *,
                sum(CASE WHEN gap IS NULL OR gap > INTERVAL {MAX_MERGE_GAP_MIN + STEP_MIN} MINUTE THEN 1 ELSE 0 END)
                    OVER (PARTITION BY tower, towed ORDER BY window_end ROWS UNBOUNDED PRECEDING) AS episode_id
            FROM gaps
        ),
        agg AS (
            SELECT
                tower,
                towed,
                episode_id,
                min(window_end) AS first_seen,
                max(window_end) AS last_seen,
                max(longest_window_min) AS max_window_min,
                min(window_end) FILTER (WHERE longest_window_min >= 15) AS low_at,
                min(window_end) FILTER (WHERE longest_window_min >= 30) AS mid_at,
                min(window_end) FILTER (WHERE longest_window_min >= 60) AS high_at,
                avg(distance_m) AS mean_distance_m,
                avg(sd_distance_m) AS mean_sd_distance_m,
                max(max_gap_s) AS max_gap_s
            FROM numbered
            GROUP BY tower, towed, episode_id
        )
        SELECT
            a.*,
            CASE a.max_window_min
                WHEN 60 THEN 'High'
                WHEN 30 THEN 'Mid'
                WHEN 15 THEN 'Low'
            END AS tow_confidence_level,
            vt.name AS tower_name,
            vt.vessel_class AS tower_class,
            vd.name AS towed_name,
            vd.vessel_class AS towed_class,
            CASE
                WHEN vd.vessel_class IN {IRREGULAR_CLASSES} THEN true
                WHEN vd.vessel_class = 'Unknown' THEN NULL
                ELSE false
            END AS is_irregular
        FROM agg AS a
        LEFT JOIN read_parquet('{VESSELS.as_posix()}') AS vt 
        ON vt.mmsi = a.tower
        LEFT JOIN read_parquet('{VESSELS.as_posix()}') AS vd 
        ON vd.mmsi = a.towed
        WHERE a.max_window_min >= 15
        ORDER BY a.first_seen
    """)

    RESULTS.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"COPY episodes TO '{(RESULTS / 'tow_episodes.parquet').as_posix()}' (FORMAT parquet)"
    )

    if RUN_CHECK:
        con.sql("""
            SELECT
                year(first_seen) AS year,
                tow_confidence_level,
                count(*) AS episodes,
                count(*) FILTER (WHERE is_irregular) AS irregular,
                count(*) FILTER (WHERE is_irregular IS NULL) AS unknown_type
            FROM episodes
            GROUP BY ALL
            ORDER BY ALL
        """).show()

        # Incident 1: IRON LADY (367514890) towing THE SEEKER II (367137680)
        con.sql("""
            SELECT
                tow_confidence_level,
                strftime(first_seen, '%m-%d %H:%M') AS first_seen,
                strftime(low_at, '%m-%d %H:%M') AS low_at,
                strftime(mid_at, '%m-%d %H:%M') AS mid_at,
                strftime(high_at, '%m-%d %H:%M') AS high_at,
                strftime(last_seen, '%m-%d %H:%M') AS last_seen,
                round(mean_distance_m) AS distance_m,
                round(mean_sd_distance_m, 1) AS sd_distance_m
            FROM episodes
            WHERE tower = 367514890 AND towed = 367137680
            ORDER BY first_seen
        """).show()


if __name__ == "__main__":
    main()
