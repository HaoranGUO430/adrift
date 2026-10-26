"""Find out the pair vessel and their features in the same min"""

from pathlib import Path

import duckdb
from functions import angle_diff, bearing, haversine

ROOT = Path(__file__).resolve().parents[1]
MINUTE_DIR = ROOT / "features" / "minute"
PAIR_DIR = ROOT / "features" / "pair"

RUN_CHECK = True
YEARS = [2017, 2018, 2019, 2020]
CANDIDATE_MAX_M = 2000  # threshold for distanse of 2 vessels chosen by data and fact


def main() -> None:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute(haversine())
    con.execute(bearing())
    con.execute(angle_diff())

    for year in YEARS:
        src = (MINUTE_DIR / f"year={year}" / "minute.parquet").as_posix()
        out_dir = PAIR_DIR / f"year={year}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = (out_dir / "pair_minute.parquet").as_posix()

        con.execute(f"""
            COPY (
                SELECT
                    a.minute,
                    a.mmsi AS mmsi_a,
                    b.mmsi AS mmsi_b,
                    haversine(a.lat, a.lon, b.lat, b.lon) AS distance_m,
                    abs(a.sog - b.sog) AS sog_diff,
                    angle_diff(a.cog, b.cog) AS cog_diff,
                    (bearing(a.lat, a.lon, b.lat, b.lon) - a.cog + 360) % 360 AS b_rel_to_a,
                    (bearing(b.lat, b.lon, a.lat, a.lon) - b.cog + 360) % 360 AS a_rel_to_b,
                    greatest(a.gap_s, b.gap_s) AS max_gap_s
                FROM read_parquet('{src}') AS a
                JOIN read_parquet('{src}') AS b
                  ON a.minute = b.minute AND a.mmsi < b.mmsi
                WHERE distance_m < {CANDIDATE_MAX_M}
                ORDER BY a.minute
            ) TO '{out}' (FORMAT parquet, COMPRESSION zstd)
        """)

        if RUN_CHECK:
            con.sql(f"""
                SELECT
                    {year} AS year,
                    count(*) AS pair_rows,
                    count(DISTINCT (mmsi_a, mmsi_b)) AS pairs,
                    count(*) - count(DISTINCT (minute, mmsi_a, mmsi_b)) AS duplicate_rows,
                    max(distance_m) AS max_distance_m
                FROM read_parquet('{out}')
            """).show()

    if RUN_CHECK:
        # Incident 1: THE SEEKER II (367137680) towed by IRON LADY (367514890)
        file_2017 = (PAIR_DIR / "year=2017" / "pair_minute.parquet").as_posix()
        con.sql(f"""
            SELECT
                count(*) AS tow_minutes,
                median(distance_m) AS median_distance_m,
                avg((abs(a_rel_to_b - 180) <= 45)::INT) AS frac_seeker_astern
            FROM read_parquet('{file_2017}')
            WHERE mmsi_a = 367137680 AND mmsi_b = 367514890
              AND minute BETWEEN '2017-01-08 11:36' AND '2017-01-10 02:56'
        """).show()


if __name__ == "__main__":
    main()
