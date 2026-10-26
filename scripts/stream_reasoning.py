"""Stream reasoning: RDF of one minute's windows in, irregular tow windows out"""

from pathlib import Path

import kolibrie as k
import pandas as pd
from functions import expand, shorten
from kolibrie_rules import add_rules
from rdflib import Graph, URIRef

ROOT = Path(__file__).resolve().parents[1]


def to_triples(graph: Graph) -> list[tuple[str, str, str]]:
    """Turn RDF graph into string triples.

    Args:
        graph: RDF graph.

    Returns:
        Triples (subject, predicate, object) as strings.
    """
    return [(str(s), str(p), str(o)) for s, p, o in graph]


ONTOLOGY_TRIPLES = to_triples(Graph().parse(ROOT / "ontology" / "adrift.ttl"))


def judge(windows: Graph, vessels: Graph) -> pd.DataFrame:
    """Run the Kolibrie rules on the windows of one minute.

    Args:
        windows: RDF of the windows.
        vessels: RDF of the vessel registry.

    Returns:
        Irregular tow windows: tower, towed, window_end (epoch s), window_min, alert_level.
    """
    window_triples = to_triples(windows)
    # Find triples about paired vessel
    seen = {
        o for s, p, o in window_triples if p in (expand("ad:pairA"), expand("ad:pairB"))
    }
    vessel_triples = []
    for v in seen:
        for s, p, o in vessels.triples((URIRef(v), None, None)):
            vessel_triples.append((str(s), str(p), str(o)))

    # Infer by kolibrie
    graph = k.KnowledgeGraph()
    for triple in ONTOLOGY_TRIPLES + vessel_triples + window_triples:
        graph.add_abox_triple(*triple)
    add_rules(graph)
    known = vessel_triples + window_triples + graph.infer_new_facts_semi_naive()

    def values(predicate: str) -> dict[str, str]:
        """Collect the known triples with one predicate to build dictionary.

        Args:
            predicate: Prefixed predicate name, e.g. "ad:tower".

        Returns:
            Subject: object of every known triple with this predicate.
        """
        return {s: o for s, p, o in known if p == expand(predicate)}

    mmsi, end, length = (
        values("ad:mmsi"),
        values("ad:windowEnd"),
        values("ad:windowMin"),
    )
    tower, towed, level = (
        values("ad:tower"),
        values("ad:towed"),
        values("ad:alertLevel"),
    )
    irregular = [
        s
        for s, p, o in known
        if p == expand("rdf:type") and o == expand("ad:IrregularTowWindow")
    ]
    rows = [
        (
            int(mmsi[tower[w]]),
            int(mmsi[towed[w]]),
            int(end[w]),
            int(length[w]),
            shorten(level[w]) if w in level else None,
        )
        for w in irregular
    ]
    return pd.DataFrame(
        rows, columns=["tower", "towed", "window_end", "window_min", "alert_level"]
    )
