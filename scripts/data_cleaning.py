"""Data cleaning, using parquet instead of csv"""

import shutil
from pathlib import Path

import duckdb
from functions import haversine, valid

ROOT = Path(__file__).resolve().parents[1]
RAW_DATA = ROOT / "HawaiiCoast_GT"
OUT = ROOT / "clean_data"
POINTS_DIR = OUT / "points"
LABELS_PATH = OUT / "labels.parquet"
VESSELS_PATH = OUT / "vessels.parquet"
INCIDENTS_PATH = OUT / "incidents.parquet"

RUN_CHECK = True
YEARS = [2017, 2018, 2019, 2020]
SPIKE_MIN_DIST_M = 1000  # spike > 1 km away on both sides
SPIKE_MIN_SPEED_KN = 50  # spike speed > 50 kn on both sides
MS_TO_KN = 1.943844  # 1 m/s = 1.943844 knots
TOW_TYPES = "Irregular tow|Helper tow"
VALID_INTERVAL = {
    "sog": (0, 102.2),  # 2^10 is invalide because 9 nomber for binary
    "cog": (0, 359.9),
}
BBOX = {
    "lat": (18.13869, 24.07175),
    "lon": (-161.70558, -152.98331),
}

AIS_TYPES = {
    "MMSI": "INTEGER",
    "datetime_utc": "TIMESTAMPTZ",
    "lat": "DOUBLE",
    "lon": "DOUBLE",
    "speed_over_ground_knots": "DOUBLE",
    "course_over_ground_deg": "DOUBLE",
    "incident_num": "DOUBLE",
}


def main() -> None:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")

    # Import haversine function in SQL
    con.execute(haversine())

    # RAW_DATA has Windows path with \, change \ into /
    glob = (RAW_DATA / "AIS_data" / "Hawaii_20*.csv").as_posix()

    # Build table
    con.execute(f"""
        CREATE TABLE stage AS
        SELECT
            MMSI AS mmsi,
            datetime_utc AS t,
            lat,
            lon,
            {valid("sog", "speed_over_ground_knots", VALID_INTERVAL["sog"])},
            {valid("cog", "course_over_ground_deg", VALID_INTERVAL["cog"])},
            incident_num
        FROM read_csv('{glob}', header = true, types = {AIS_TYPES})
        WHERE lat BETWEEN {BBOX["lat"][0]} AND {BBOX["lat"][1]}
            AND lon BETWEEN {BBOX["lon"][0]} AND {BBOX["lon"][1]}
    """)

    if RUN_CHECK:
        n = con.sql("SELECT count(*) FROM stage").fetchone()[0]
        print(f"stage rows: {n:,}")
        con.sql("SELECT * FROM stage LIMIT 5").show()

        # If cleaning works?
        con.sql("""
            SELECT
                count(*) FILTER (WHERE sog IS NULL) AS sog_null,
                max(cog) AS cog_max
            FROM stage
        """).show()

    # Remove duplicates WITH dedup
    # Flag position spikes WITH neighbours(distance & time) and flags
    con.execute(f"""
        CREATE TABLE flagged AS
        WITH dedup AS (
            SELECT *
            FROM stage
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
        flags AS (
            SELECT 
                *,
                d_in  > {SPIKE_MIN_DIST_M}
                    AND d_in  / dt_in  * {MS_TO_KN} > {SPIKE_MIN_SPEED_KN}  AS jump_in,
                d_out > {SPIKE_MIN_DIST_M}
                    AND d_out / dt_out * {MS_TO_KN} > {SPIKE_MIN_SPEED_KN}  AS jump_out
            FROM neighbours
        )
        SELECT
            * EXCLUDE (d_in, d_out, dt_in, dt_out, jump_in, jump_out),
            coalesce(jump_in, false)
                AND coalesce(jump_out, true) AS is_spike
        FROM flags
    """)

    # Save memories
    con.execute("DROP TABLE stage")

    # Delete position spikes
    con.execute("""
        CREATE TABLE points AS
        SELECT
            mmsi, t, lat, lon, sog, cog,
            incident_num::SMALLINT AS incident_num
        FROM flagged
        WHERE NOT is_spike
    """)

    if RUN_CHECK:
        con.sql("""
            SELECT
                (SELECT count(*) FROM flagged) AS after_dedup,
                (SELECT count(*) FROM flagged WHERE is_spike) AS spikes,
                (SELECT count(*) FROM points) AS clean_points,
                (SELECT count(incident_num) FROM points) AS labeled_points
        """).show()

    # Build vessels table from vessel_names_and_classes.csv
    vessels_csv = (RAW_DATA / "AIS_data" / "vessel_names_and_classes.csv").as_posix()

    con.execute(f"""
        CREATE TABLE vessels AS
        WITH v AS (
            SELECT
                MMSI::INTEGER AS mmsi,
                CASE WHEN vessel_names LIKE '[''%'
                     THEN regexp_extract(vessel_names, '^[[]''([^'']*)''', 1)
                     ELSE regexp_extract(vessel_names, '^[[]"([^"]*)"', 1)
                END AS name,
                CASE
                    WHEN vessel_class IS NULL OR vessel_class = 'nan' THEN 'Unknown'
                    WHEN vessel_class = 'Pilot Vessel' THEN 'Pilot vessel'
                    ELSE vessel_class
                END AS vessel_class
            FROM read_csv('{vessels_csv}')
        )
        SELECT *
        FROM v
        ORDER BY mmsi
    """)

    con.execute("DROP TABLE flagged")

    # Build incidents reference table from hawaii_primary_trajectories_of_interest_2017_2020.csv
    # Keep all incidents; is_tow marks the ones this project detects
    incidents_csv = (
        RAW_DATA
        / "incident_data"
        / "hawaii_primary_trajectories_of_interest_2017_2020.csv"
    ).as_posix()

    con.execute(f"""
        CREATE TABLE incidents AS
        SELECT
            incident_num::SMALLINT AS incident_num,
            MMSI AS mmsi,
            vessel_name,
            ais_incident_type AS incident_type,
            ais_incident_evidence AS evidence,
            CASE WHEN report_vessel_role ILIKE '%helper%'
                OR ais_incident_type  ILIKE '%helper%'
                THEN 'helper' ELSE 'victim'
            END AS role,
            ais_incident_start_bound_hst::TIMESTAMPTZ AS t_start,
            ais_incident_end_bound_hst::TIMESTAMPTZ AS t_end,
            regexp_matches(incident_type, '{TOW_TYPES}') AS is_tow,
            evidence IN ('High evidence', 'Good evidence') AS usable,
            report_based_incident_description AS report_description,
            ais_availability_description AS ais_description
        FROM read_csv('{incidents_csv}')
        ORDER BY incident_num, mmsi
    """)

    # Write Parquet output
    if OUT.exists():
        shutil.rmtree(OUT)  # start from an empty folder
    OUT.mkdir(parents=True, exist_ok=True)

    for year in YEARS:
        folder = POINTS_DIR / f"year={year}"
        folder.mkdir(parents=True, exist_ok=True)
        path = (folder / "points.parquet").as_posix()
        con.execute(f"""
            COPY (
                SELECT * EXCLUDE (incident_num)
                FROM points
                WHERE t >= '{year}-01-01' AND t < '{year + 1}-01-01'
                ORDER BY t
            ) TO '{path}' (FORMAT parquet)
        """)

    con.execute(f"""
        COPY (SELECT mmsi, t, incident_num FROM points WHERE incident_num IS NOT NULL ORDER BY t)
            TO '{LABELS_PATH.as_posix()}' (FORMAT parquet)
    """)
    con.execute(f"COPY vessels TO '{VESSELS_PATH.as_posix()}' (FORMAT parquet)")
    con.execute(f"COPY incidents TO '{INCIDENTS_PATH.as_posix()}' (FORMAT parquet)")

    if RUN_CHECK:
        size_mb = sum(f.stat().st_size for f in OUT.rglob("*.parquet")) / 1e6
        print(f"Parquet on disk: {size_mb:,.0f} MB")
        con.sql(f"""
            SELECT year, count(*) AS n_points
            FROM read_parquet('{POINTS_DIR.as_posix()}/*/*.parquet', hive_partitioning = true)
            GROUP BY year
            ORDER BY year
        """).show()
        con.sql("""
            SELECT count(*) AS vessels,
                   count(*) FILTER (WHERE vessel_class = 'Unknown') AS unknown_class
            FROM vessels
        """).show()
        con.sql("""
            SELECT count(*) AS tow_tracks, count(DISTINCT incident_num) AS tow_incidents,
                   count(*) FILTER (WHERE role = 'helper') AS towers,
                   count(*) FILTER (WHERE role = 'victim') AS towed
            FROM incidents
            WHERE is_tow AND usable
        """).show()


if __name__ == "__main__":
    main()
