"""list the evaluated result manuelly"""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
INCIDENTS = ROOT / "clean_data" / "incidents.parquet"
GROUND_TRUTH = ROOT / "ground_truth" / "ground_truth.csv"

RUN_CHECK = True
SWAPPED_MMSI = (127, 130)  # Annotation mistake(by report)

# Addition manuel
ADDED_TOWS = [
    (69, 367330610, "DESTINY", 367516940, "PRINCESS K"),
    (79, 367330610, "DESTINY", 367003760, "SEA HUNT"),
    (88, 367114110, "QUEEN DIAMOND", 367490140, "QUEEN DIAMOND II"),
    (103, 367732990, "CAPT MILLIONS III", 368001590, "MIGHTY JOE"),
]


def main() -> None:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute(
        f"CREATE TABLE incidents AS SELECT * FROM read_parquet('{INCIDENTS.as_posix()}')"
    )

    GROUND_TRUTH.parent.mkdir(parents=True, exist_ok=True)

    added = ", ".join(
        f"({incident_num}, {tower}, '{tower_name}', {towed}, '{towed_name}')"
        for incident_num, tower, tower_name, towed, towed_name in ADDED_TOWS
    )

    # Combine helper and victim vessel in same row WITH labelled
    # Add manuelly the correct results checked by me WITH add
    con.execute(f"""
        COPY (
            WITH t AS (
                SELECT * FROM incidents WHERE is_tow AND usable
            ),
            labelled AS (
                SELECT
                    h.incident_num,
                    CASE
                        WHEN h.incident_num IN {SWAPPED_MMSI} THEN v.mmsi
                        ELSE h.mmsi
                    END AS tower,
                    h.vessel_name AS tower_name,
                    CASE
                        WHEN h.incident_num IN {SWAPPED_MMSI} THEN h.mmsi
                        ELSE v.mmsi
                    END AS towed,
                    v.vessel_name AS towed_name,
                    greatest(h.t_start, v.t_start) AS t_start,
                    least(h.t_end, v.t_end) AS t_end,
                    v.report_description AS report,
                    h.incident_num IN {SWAPPED_MMSI} AS added_manually
                FROM t AS h
                JOIN t AS v
                    ON h.incident_num = v.incident_num
                    AND h.role = 'helper'
                    AND v.role = 'victim'
            ),
            added AS (
                SELECT
                    a.*,
                    greatest(v.t_start, h.t_start) AS t_start,
                    least(v.t_end, h.t_end) AS t_end,
                    v.report_description AS report,
                    true AS added_manually
                FROM (VALUES {added}) AS a(incident_num, tower, tower_name, towed, towed_name)
                JOIN incidents AS v ON v.incident_num = a.incident_num AND v.mmsi = a.towed
                LEFT JOIN incidents AS h ON h.incident_num = a.incident_num AND h.mmsi = a.tower
            )
            SELECT * FROM labelled
            UNION ALL
            SELECT * FROM added
            ORDER BY incident_num
        ) TO '{GROUND_TRUTH.as_posix()}' (HEADER)
    """)

    if RUN_CHECK:
        con.sql(f"""
            SELECT
                count(*) AS tows,
                count(*) FILTER (WHERE added_manually) AS added,
                count(*) FILTER (WHERE t_end <= t_start) AS bad_time,
                count(report) AS with_report
            FROM read_csv('{GROUND_TRUTH.as_posix()}', header = true)
        """).show()


if __name__ == "__main__":
    main()
