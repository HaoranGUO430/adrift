"""Map the vessel registry and pair windows to RDF with RML (Morph-KGC)"""

from pathlib import Path

import duckdb
import morph_kgc
import pandas as pd
from rdflib import Graph

ROOT = Path(__file__).resolve().parents[1]
VESSELS = ROOT / "clean_data" / "vessels.parquet"
MAPPINGS = ROOT / "rml"


def to_rdf(mapping: str, source: str, table: pd.DataFrame) -> Graph:
    """Apply RML mapping to table.

    Args:
        mapping: File name for rml mapping, e.g. "window_rml.ttl".
        source: Name of the logical source in the mapping, e.g. "windows".
        table: Table need to be transformed by rml.

    Returns:
        RDF graph of the mapped rows.
    """
    config = f"""
        [DataSource]
        mappings: {(ROOT / "rml" / mapping).as_posix()}
    """
    return morph_kgc.materialize(config, {source: table})


def vessels_to_rdf() -> Graph:
    """Map the vessel registry.

    Returns:
        RDF graph of all vessels.
    """
    vessels = duckdb.sql(f"""
        SELECT 
            mmsi, 
            name, 
            vessel_class 
        FROM read_parquet('{VESSELS.as_posix()}')
    """).df()
    return to_rdf("vessel_rml.ttl", "vessels", vessels)


def windows_to_rdf(windows: pd.DataFrame) -> Graph:
    """Map the pair windows of one stream step.

    Args:
        windows: Windows returned by stream_features.step().

    Returns:
        RDF graph of the windows.
    """
    return to_rdf("window_rml.ttl", "windows", windows)
