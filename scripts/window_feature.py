"""Calculate and judge the feature for single and paied vessel(s) in windows"""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "features"

RUN_CHECK = True
YEARS = [2017, 2018, 2019, 2020]
WINDOW_LENGTHS = [5, 15, 30, 60]  # alert levels
ASTERN_TOLERANCE_DEG = 45


def main() -> None:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")

    for year in YEARS:
        pair_src = (
            FEATURES / "pair" / f"year={year}" / "pair_minute.parquet"
        ).as_posix()

        for window_min in WINDOW_LENGTHS:
            out_dir = (
                FEATURES / "pair_window" / f"window_min={window_min}" / f"year={year}"
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            out = (out_dir / "pair_window.parquet").as_posix()

            # Calculate window feature
            con.execute(f"""
                COPY (
                    SELECT
                        mmsi_a,
                        mmsi_b,
                        {window_min} AS window_min,
                        minute AS window_end,
                        count(*) OVER w AS n_min,
                        avg(distance_m) OVER w AS mean_distance_m,
                        max(distance_m) OVER w AS max_distance_m,
                        stddev_pop(distance_m) OVER w AS sd_distance_m,
                        avg(sog_diff) OVER w AS mean_sog_diff,
                        avg(cog_diff) OVER w AS mean_cog_diff,
                        avg((abs(a_rel_to_b - 180) <= {ASTERN_TOLERANCE_DEG})::INT) OVER w AS frac_a_astern_of_b,
                        avg((abs(b_rel_to_a - 180) <= {ASTERN_TOLERANCE_DEG})::INT) OVER w AS frac_b_astern_of_a,
                        max(max_gap_s) OVER w AS max_gap_s
                    FROM read_parquet('{pair_src}')
                    WINDOW w AS (
                        PARTITION BY mmsi_a, mmsi_b
                        ORDER BY minute
                        RANGE BETWEEN INTERVAL {window_min - 1} MINUTE PRECEDING AND CURRENT ROW
                    )
                    ORDER BY window_end
                ) TO '{out}' (FORMAT parquet, COMPRESSION zstd)
            """)

            if RUN_CHECK:
                con.sql(f"""
                    SELECT
                        {year} AS year,
                        {window_min} AS window_min,
                        (SELECT count(*) FROM read_parquet('{pair_src}')) AS pair_minutes,
                        (SELECT count(*) FROM read_parquet('{out}')) AS windows,
                        (SELECT max(n_min) FROM read_parquet('{out}')) AS max_n_min
                """).show()


if __name__ == "__main__":
    main()
