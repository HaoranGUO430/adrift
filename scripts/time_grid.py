"""Resample vessels to a one-min grid by linear interpolation."""

from pathlib import Path

import duckdb
from functions import haversine

ROOT = Path(__file__).resolve().parents[1]
POINTS_DIR = ROOT / "clean_data" / "points"
MINUTE_DIR = ROOT / "features" / "minute"

RUN_CHECK = True
YEARS = [2017, 2018]  # development
MIN_SOG_KN = 1.0  # if vessels moving
MAX_GAP_MIN = 10  # if break < 10 min, interpolation
MAX_SPEED_MISMATCH_KN = 5  # additional speed limit
MS_TO_KN = 1.943844


def main() -> None:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")

    # Import haversine function in SQL
    con.execute(haversine())

    for year in YEARS:
        src = (POINTS_DIR / f"year={year}" / "points.parquet").as_posix()
        out_dir = MINUTE_DIR / f"year={year}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = (out_dir / "minute.parquet").as_posix()

        # Trait missing values by interpolation
        # Combine lines WITH pairs
        # Keep interval which can interpolate WITH usable
        # Extend time points WITH grid(unit min)
        # Calculate proportion of time WITH weight
        # Calculate rotation for each interpolation WITH interpolated
        con.execute(f"""
            COPY (
                WITH pairs AS (
                    SELECT
                        mmsi, seg_id,
                        t AS t0,
                        lat AS lat0,
                        lon AS lon0,
                        sog AS sog0,
                        cog AS cog0,
                        lead(t) OVER w AS t1,
                        lead(lat) OVER w AS lat1,
                        lead(lon) OVER w AS lon1,
                        lead(sog) OVER w AS sog1,
                        lead(cog) OVER w AS cog1
                    FROM read_parquet('{src}')
                    WINDOW w AS (PARTITION BY mmsi, seg_id ORDER BY t)
                ),
                usable AS (
                    SELECT *
                    FROM pairs
                    WHERE t1 IS NOT NULL
                      AND t1 - t0 <= INTERVAL {MAX_GAP_MIN} MINUTE
                      AND sog0 >= {MIN_SOG_KN}
                      AND sog1 >= {MIN_SOG_KN}
                      AND haversine(lat0, lon0, lat1, lon1) / (epoch(t1) - epoch(t0)) * {MS_TO_KN}
                          <= sog0 + sog1 + {MAX_SPEED_MISMATCH_KN}
                ),
                grid AS (
                    SELECT
                        *,
                        unnest(generate_series(
                            time_bucket(INTERVAL 1 MINUTE, t0) + INTERVAL 1 MINUTE,
                            t1,
                            INTERVAL 1 MINUTE
                        )) AS minute
                    FROM usable
                ),
                weighted AS (
                    SELECT
                        *,
                        (epoch(minute) - epoch(t0)) / (epoch(t1) - epoch(t0)) AS prop
                    FROM grid
                ),
                interpolated AS (
                    SELECT
                        *,
                        CASE
                            WHEN cog1 - cog0 > 180 THEN (cog1 - cog0 - 360) * prop + cog0 
                            WHEN cog1 - cog0 < -180 THEN (cog1 - cog0 + 360) * prop + cog0 
                            ELSE (cog1 - cog0) * prop + cog0 
                        END AS cog_raw
                    FROM weighted
                )
                SELECT
                    mmsi,
                    minute,
                    lat0 + prop * (lat1 - lat0) AS lat,
                    lon0 + prop * (lon1 - lon0) AS lon,
                    (sog0 + prop * (sog1 - sog0)) AS sog,
                    CASE
                        WHEN cog_raw < 0 THEN cog_raw + 360
                        WHEN cog_raw >= 360 THEN cog_raw - 360
                        ELSE cog_raw
                    END AS cog,
                    seg_id,
                    (epoch(t1) - epoch(t0)) AS gap_s
                FROM interpolated
                ORDER BY minute, mmsi
            ) TO '{out}' (FORMAT parquet)
        """)

        if RUN_CHECK:
            con.sql(f"""
                SELECT
                    {year} AS year,
                    count(*) AS minute_rows,
                    count(DISTINCT mmsi) AS vessels,
                    count(*) - count(DISTINCT (mmsi, minute)) AS duplicate_minutes,
                    median(gap_s) AS median_gap_s,
                    max(cog) AS max_cog
                FROM read_parquet('{out}')
            """).show()

    if RUN_CHECK:
        # Incident 1: IRON LADY (367514890) towing THE SEEKER II (367137680)
        file_2017 = (MINUTE_DIR / "year=2017" / "minute.parquet").as_posix()
        con.sql(f"""
            SELECT count(*) AS minutes_with_both_vessels
            FROM read_parquet('{file_2017}') AS a
            JOIN read_parquet('{file_2017}') AS b USING (minute)
            WHERE a.mmsi = 367514890 AND b.mmsi = 367137680
              AND minute BETWEEN '2017-01-08 11:36' AND '2017-01-10 02:56'
        """).show()


if __name__ == "__main__":
    main()
