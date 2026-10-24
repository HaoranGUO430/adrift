"""Physical tow definition and background knowledge as Kolibrie rules"""

import kolibrie as k
from functions import expand
from rules_paired import (
    MAX_MEAN_DISTANCE_M,
    MAX_SD_DISTANCE_M,
    MIN_COVERAGE,
    MIN_FRAC_ASTERN,
    SHIP_MMSI,
)  # Constant defined by basic rules


def add_rules(graph: k.KnowledgeGraph) -> None:
    """Add the Kolibrie rules to find out irregular tow window and alert level.

    Args:
        graph: Knowledge graph to add the rules to.
    """
    V = k.Term.Variable
    T = k.TriplePattern
    F = k.FilterCondition

    def C(name: str) -> k.Term:
        """Constant term of a prefixed name, e.g. C("ad:Ship")."""
        return k.Term.Constant(graph.encode_term(expand(name)))

    # Rule 1 : ship MMSIs start with 2-7
    # ?vessel rdf:type ad:Ship ← ?vessel ad:mmsi ?mmsi, SHIP_MMSI[0] ≤ ?mmsi ≤ SHIP_MMSI[1]
    graph.add_rule(
        k.Rule(
            premise=[T(V("vessel"), C("ad:mmsi"), V("mmsi"))],
            filters=[
                F("mmsi", ">=", str(SHIP_MMSI[0])),
                F("mmsi", "<=", str(SHIP_MMSI[1])),
            ],
            conclusion=[T(V("vessel"), C("rdf:type"), C("ad:Ship"))],
        )
    )

    # Rule 2 : the vessel class
    # ?vessel rdf:type ?vessel_class ← ?vessel ad:registeredClass ?label, ?vessel_class ad:registryLabel ?label
    graph.add_rule(
        k.Rule(
            premise=[
                T(V("vessel"), C("ad:registeredClass"), V("label")),
                T(V("vessel_class"), C("ad:registryLabel"), V("label")),
            ],
            filters=[],
            conclusion=[T(V("vessel"), C("rdf:type"), V("vessel_class"))],
        )
    )

    # Rule 3 : is SelfPropelledVessel? by recurrence relation
    # ?instance rdf:type ?superclass ← ?instance rdf:type ?subclass, ?subclass rdfs:subClassOf ?superclass
    graph.add_rule(
        k.Rule(
            premise=[
                T(V("instance"), C("rdf:type"), V("subclass")),
                T(V("subclass"), C("rdfs:subClassOf"), V("superclass")),
            ],
            filters=[],
            conclusion=[T(V("instance"), C("rdf:type"), V("superclass"))],
        )
    )

    # Preparation for Rule 4
    window = [
        T(V("window"), C("ad:pairA"), V("vessel_a")),
        T(V("window"), C("ad:pairB"), V("vessel_b")),
        T(V("vessel_a"), C("rdf:type"), C("ad:Ship")),
        T(V("vessel_b"), C("rdf:type"), C("ad:Ship")),
        T(V("window"), C("ad:coverage"), V("coverage")),
        T(V("window"), C("ad:sdDistance"), V("sd_distance")),
        T(V("window"), C("ad:meanDistance"), V("mean_distance")),
        T(V("window"), C("ad:fracAAstern"), V("frac_a_astern")),
        T(V("window"), C("ad:fracBAstern"), V("frac_b_astern")),
    ]
    stable = [
        F("coverage", ">=", str(MIN_COVERAGE)),
        F("sd_distance", "<=", str(MAX_SD_DISTANCE_M)),
        F("mean_distance", "<=", str(MAX_MEAN_DISTANCE_M)),
    ]

    # Rule 4 : is window a towed window(stable)?
    # Rule 5a : who is tower/towed(a is towed by b)
    # ?window rdf:type ad:TowWindow, ad:towed ?vessel_a, ad:tower ?vessel_b ← window, stable, frac_a_astern ≥ MIN_FRAC_ASTERN, frac_b_astern < MIN_FRAC_ASTERN
    graph.add_rule(
        k.Rule(
            premise=window,
            filters=stable
            + [
                F("frac_a_astern", ">=", str(MIN_FRAC_ASTERN)),
                F("frac_b_astern", "<", str(MIN_FRAC_ASTERN)),
            ],
            conclusion=[
                T(V("window"), C("rdf:type"), C("ad:TowWindow")),
                T(V("window"), C("ad:towed"), V("vessel_a")),
                T(V("window"), C("ad:tower"), V("vessel_b")),
            ],
        )
    )

    # Rule 4 : is window a towed window(stable)?
    # Rule 5b : who is tower/towed(b is towed by a)
    # ?window rdf:type ad:TowWindow, ad:towed ?vessel_b, ad:tower ?vessel_a ← window, stable, frac_b_astern ≥ MIN_FRAC_ASTERN, frac_a_astern < MIN_FRAC_ASTERN
    graph.add_rule(
        k.Rule(
            premise=window,
            filters=stable
            + [
                F("frac_b_astern", ">=", str(MIN_FRAC_ASTERN)),
                F("frac_a_astern", "<", str(MIN_FRAC_ASTERN)),
            ],
            conclusion=[
                T(V("window"), C("rdf:type"), C("ad:TowWindow")),
                T(V("window"), C("ad:towed"), V("vessel_b")),
                T(V("window"), C("ad:tower"), V("vessel_a")),
            ],
        )
    )

    # Rule 6 : is towed window an irregular tow window by checking towed vessel a SelfPropelledVessel
    # ?window rdf:type ad:IrregularTowWindow ← ?window rdf:type ad:TowWindow, ?window ad:towed ?towed, ?towed rdf:type ad:SelfPropelledVessel
    graph.add_rule(
        k.Rule(
            premise=[
                T(V("window"), C("rdf:type"), C("ad:TowWindow")),
                T(V("window"), C("ad:towed"), V("towed")),
                T(V("towed"), C("rdf:type"), C("ad:SelfPropelledVessel")),
            ],
            filters=[],
            conclusion=[T(V("window"), C("rdf:type"), C("ad:IrregularTowWindow"))],
        )
    )

    # Rule 7 : alert level by mins
    # ?window ad:alertLevel ?level ← ?window rdf:type ad:IrregularTowWindow, ?window ad:windowMin ?window_min, ?level ad:levelWindowMin ?window_min
    graph.add_rule(
        k.Rule(
            premise=[
                T(V("window"), C("rdf:type"), C("ad:IrregularTowWindow")),
                T(V("window"), C("ad:windowMin"), V("window_min")),
                T(V("level"), C("ad:levelWindowMin"), V("window_min")),
            ],
            filters=[],
            conclusion=[T(V("window"), C("ad:alertLevel"), V("level"))],
        )
    )
