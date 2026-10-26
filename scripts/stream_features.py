"""Calculate stream features, same as basic SQL rules"""

import duckdb
import pandas as pd
from functions import angle_diff, bearing, haversine, valid

# Constant got from SQL basic rules
SPIKE_MIN_DIST_M = 1000
SPIKE_MIN_SPEED_KN = 50
MS_TO_KN = 1.943844
MAX_GAP_MIN = 10
MIN_SOG_KN = 1.0
MAX_SPEED_MISMATCH_KN = 5
CANDIDATE_MAX_M = 2000
WINDOW_LENGTHS = [5, 15, 30, 60]
ASTERN_TOLERANCE_DEG = 45
VALID_INTERVAL = {
    "sog": (0, 102.2),
    "cog": (0, 359.9),
}
BBOX = {
    "lat": (18.13869, 24.07175),
    "lon": (-161.70558, -152.98331),
}
# New feature
WATERMARK_MIN = MAX_GAP_MIN  # Time value which can interpolate
KEEP_BUFFER_MIN = 2 * MAX_GAP_MIN
KEEP_PAIRS_MIN = max(WINDOW_LENGTHS)


def create_state(con: duckdb.DuckDBPyConnection) -> None:
    """Prepare 3 empty tables for streaming :

    buffer for RAW data,

    minutes for single vessel data in a minute,

    pairs for paired vessel data in a minute.

    Args:
        con: DuckDB Connection.
    """
    con.execute("SET TimeZone = 'UTC'")
    con.execute(haversine())
    con.execute(bearing())
    con.execute(angle_diff())
    con.execute("""
        CREATE TABLE buffer (
            mmsi INTEGER, 
            t TIMESTAMPTZ, 
            lat DOUBLE, 
            lon DOUBLE, 
            sog DOUBLE, 
            cog DOUBLE
        )
    """)
    con.execute("""
        CREATE TABLE minutes (
            mmsi INTEGER, 
            minute TIMESTAMPTZ, 
            lat DOUBLE, 
            lon DOUBLE, 
            sog DOUBLE, 
            cog DOUBLE, 
            gap_s DOUBLE
        )
    """)
    con.execute("""
        CREATE TABLE pairs (
            minute TIMESTAMPTZ, 
            mmsi_a INTEGER, 
            mmsi_b INTEGER, 
            distance_m DOUBLE, 
            b_rel_to_a DOUBLE, 
            a_rel_to_b DOUBLE, 
            max_gap_s DOUBLE
        )
    """)


def step(
    con: duckdb.DuckDBPyConnection, new_rows: pd.DataFrame, now: pd.Timestamp
) -> pd.DataFrame:
    """Process the AIS messages that arrived in the minute before `now`.

    Args:
        con: DuckDB Connection.
        new_rows: New arrival AIS messages(raw CSV rows).
        now: Simulated stream time.

    Returns:
        Pair windows ending at the minute completed by this step.
    """
    watermark = now - pd.Timedelta(minutes=WATERMARK_MIN)

    # 1. buffer: valid messages inside the box
    con.register("new_rows", new_rows)
    con.execute(f"""
        INSERT INTO buffer
        SELECT
            MMSI AS mmsi,
            datetime_utc::TIMESTAMPTZ AS t,
            lat,
            lon,
            {valid("sog", "speed_over_ground_knots", VALID_INTERVAL["sog"])},
            {valid("cog", "course_over_ground_deg", VALID_INTERVAL["cog"])}
        FROM new_rows
        WHERE lat BETWEEN {BBOX["lat"][0]} AND {BBOX["lat"][1]}
            AND lon BETWEEN {BBOX["lon"][0]} AND {BBOX["lon"][1]}
    """)
    con.unregister("new_rows")

    # 2. Clean and interpolate(like SQL rules)
    # Delete duplication if 2 location in same min WITH dedup
    # Calculate diff of time and distance WITH neighbours
    # Clean the spike point by distance and speed WITH clean
    # Combine neighbours rows WITH intervals
    # Judge if this moment(watermarke) can be interpolated WITH usable
    # Interpolate the value WITH interpolated
    con.execute(f"""
        INSERT INTO minutes
        WITH dedup AS (
            SELECT *
            FROM buffer
            QUALIFY row_number() OVER (PARTITION BY mmsi, t ORDER BY lat, lon) = 1
        ),
        neighbours AS (
            SELECT
                *,
                haversine(lag(lat) OVER w, lag(lon) OVER w, lat, lon) AS d_in,
                haversine(lat, lon, lead(lat) OVER w, lead(lon) OVER w) AS d_out,
                epoch(t) - epoch(lag(t) OVER w) AS dt_in,
                epoch(lead(t) OVER w) - epoch(t) AS dt_out
            FROM dedup
            WINDOW w AS (PARTITION BY mmsi ORDER BY t)
        ),
        clean AS (
            SELECT mmsi, t, lat, lon, sog, cog
            FROM neighbours
            WHERE NOT (
                coalesce(
                    d_in > {SPIKE_MIN_DIST_M} AND d_in / dt_in * {MS_TO_KN} > {SPIKE_MIN_SPEED_KN}, 
                    false
                )
                    AND coalesce(
                        d_out > {SPIKE_MIN_DIST_M} AND d_out / dt_out * {MS_TO_KN} > {SPIKE_MIN_SPEED_KN}, 
                        true
                    )
            )
        ),
        intervals AS (
            SELECT
                mmsi,
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
            FROM clean
            WINDOW w AS (PARTITION BY mmsi ORDER BY t)
        ),
        usable AS (
            SELECT
                *,
                TIMESTAMPTZ '{watermark}' AS minute,
                (epoch(TIMESTAMPTZ '{watermark}') - epoch(t0)) / (epoch(t1) - epoch(t0)) AS prop
            FROM intervals
            WHERE t1 IS NOT NULL
                AND t1 - t0 <= INTERVAL {MAX_GAP_MIN} MINUTE
                AND sog0 >= {MIN_SOG_KN}
                AND sog1 >= {MIN_SOG_KN}
                AND haversine(lat0, lon0, lat1, lon1) / (epoch(t1) - epoch(t0)) * {MS_TO_KN} <= sog0 + sog1 + {MAX_SPEED_MISMATCH_KN}
                AND time_bucket(INTERVAL 1 MINUTE, t0) < TIMESTAMPTZ '{watermark}'
                AND t1 >= TIMESTAMPTZ '{watermark}'
        ),
        interpolated AS (
            SELECT
                *,
                CASE
                    WHEN cog1 - cog0 > 180 THEN (cog1 - cog0 - 360) * prop + cog0
                    WHEN cog1 - cog0 < -180 THEN (cog1 - cog0 + 360) * prop + cog0
                    ELSE (cog1 - cog0) * prop + cog0
                END AS cog_raw
            FROM usable
        )
        SELECT
            mmsi,
            minute,
            lat0 + prop * (lat1 - lat0) AS lat,
            lon0 + prop * (lon1 - lon0) AS lon,
            sog0 + prop * (sog1 - sog0) AS sog,
            CASE
                WHEN cog_raw < 0 THEN cog_raw + 360
                WHEN cog_raw >= 360 THEN cog_raw - 360
                ELSE cog_raw
            END AS cog,
            epoch(t1) - epoch(t0) AS gap_s
        FROM interpolated
    """)

    # 3. Paired vessel
    con.execute(f"""
        INSERT INTO pairs
        SELECT
            a.minute,
            a.mmsi AS mmsi_a,
            b.mmsi AS mmsi_b,
            haversine(a.lat, a.lon, b.lat, b.lon) AS distance_m,
            (bearing(a.lat, a.lon, b.lat, b.lon) - a.cog + 360) % 360 AS b_rel_to_a,
            (bearing(b.lat, b.lon, a.lat, a.lon) - b.cog + 360) % 360 AS a_rel_to_b,
            greatest(a.gap_s, b.gap_s) AS max_gap_s
        FROM minutes AS a
        JOIN minutes AS b
            ON a.minute = b.minute AND a.mmsi < b.mmsi
        WHERE a.minute = TIMESTAMPTZ '{watermark}'
            AND distance_m < {CANDIDATE_MAX_M}
    """)

    # 4. Window: only for pairs seen at that minute(watermark)
    queries = []
    for w in WINDOW_LENGTHS:
        queries.append(f"""
            SELECT
                mmsi_a,
                mmsi_b,
                {w} AS window_min,
                epoch(max(minute))::BIGINT AS window_end,
                count(*) AS n_min,
                count(*) / {w} AS coverage,
                avg(distance_m) AS mean_distance_m,
                stddev_pop(distance_m) AS sd_distance_m,
                avg((abs(a_rel_to_b - 180) <= {ASTERN_TOLERANCE_DEG})::INT) AS frac_a_astern_of_b,
                avg((abs(b_rel_to_a - 180) <= {ASTERN_TOLERANCE_DEG})::INT) AS frac_b_astern_of_a,
                max(max_gap_s) AS max_gap_s
            FROM pairs
            WHERE minute > TIMESTAMPTZ '{watermark}' - INTERVAL {w} MINUTE
                AND minute <= TIMESTAMPTZ '{watermark}'
            GROUP BY mmsi_a, mmsi_b
            HAVING max(minute) = TIMESTAMPTZ '{watermark}'
        """)
    windows = con.sql(" UNION ALL ".join(queries)).df()

    # 5. Remove useless data
    cutoff = now - pd.Timedelta(minutes=KEEP_BUFFER_MIN)

    con.execute(f"""
        DELETE FROM buffer
        WHERE t < TIMESTAMPTZ '{cutoff}'
    """)

    con.execute("DELETE FROM minutes")

    con.execute(f"""
        DELETE FROM pairs
        WHERE minute <= TIMESTAMPTZ '{watermark}' - INTERVAL {KEEP_PAIRS_MIN} MINUTE
    """)

    return windows
