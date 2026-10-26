"""Pipeline of streaming: raw AIS messages -> windows -> RDF -> Kolibrie -> alert events -> alert board"""

from collections.abc import Iterator

import duckdb
import pandas as pd
from app import show_board
from stream_alerts import update
from stream_features import WATERMARK_MIN, create_state, step
from stream_reasoning import judge
from stream_simulation import SPEED, incident_period, replay
from transform_to_rdf import vessels_to_rdf, windows_to_rdf

DEMO_INCIDENTS = [23, 122, 13, 22]

VESSELS = vessels_to_rdf()


def run(
    incident: int, speed: float | None = SPEED
) -> Iterator[tuple[pd.Timestamp, list[tuple]]]:
    """Replay one known tow through the whole stream pipeline.

    Args:
        incident: Incident number.
        speed: Stream minutes per real second(None as fast as possible).

    Yields:
        The stream time and the alert at that time.
    """
    start, end = incident_period(incident)
    con = duckdb.connect()
    create_state(con)
    episodes = {}
    for now, new_rows in replay(start, end, speed):
        windows = step(con, new_rows, now)
        irregular = judge(windows_to_rdf(windows), VESSELS)
        minute = int((now - pd.Timedelta(minutes=WATERMARK_MIN)).timestamp())
        yield now, update(episodes, irregular, minute)


def main() -> None:
    """Open the alert board on the demo tows."""
    show_board(run, DEMO_INCIDENTS)


if __name__ == "__main__":
    main()
