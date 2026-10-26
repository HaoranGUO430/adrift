"""Common functions here"""

PREFIXES = {
    "ad:": "https://github.com/HaoranGUO430/adrift#",
    "rdf:": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs:": "http://www.w3.org/2000/01/rdf-schema#",
}


def valid(col: str, val: str, interval: tuple[float, float]) -> str:
    """SQL that keeps a value only inside its valid interval.

    Args:
        col: Output column name, e.g. "sog".
        val: Input column, e.g. "speed_over_ground_knots".
        interval: Lowest and highest valid value.

    Returns:
        SQL expression.
    """
    low, high = interval
    return f"""
        CASE WHEN {val} BETWEEN {low} AND {high} 
            THEN {val} 
        END AS {col}
    """


def haversine() -> str:
    """Creat haversine distance function in SQL"""
    # Calculate distance by haversine function, better than euclidean distance
    # φ: lat λ：lon
    # a = sin^2(Δφ / 2) + cos φ₁ * cos φ₂ * sin²(Δλ / 2)
    # d = 2R · arcsin(√a); R = 6371000
    return """
        CREATE MACRO haversine(lat1, lon1, lat2, lon2) AS
            2 * 6371000 * asin(sqrt(
                power(sin(radians(lat2 - lat1) / 2), 2) 
                + cos(radians(lat1)) * cos(radians(lat2)) * power(sin(radians(lon2 - lon1) / 2), 2) 
            ))
    """


def bearing() -> str:
    """Creat bearing function in SQL: compass direction (0 = north) from point 1 to point 2"""
    return """
        CREATE MACRO bearing(lat1, lon1, lat2, lon2) AS
            (degrees(atan2((lon2 - lon1) * cos(radians(lat1)), lat2 - lat1)) + 360) % 360
    """


def angle_diff() -> str:
    """Create angle_diff function in SQL: smallest difference between two angles (0-180)"""
    return """
        CREATE MACRO angle_diff(x, y) AS 180 - abs(abs(x - y) % 360 - 180)
    """


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson confidence interval of a proportion k/n.

    Args:
        k: Number of successes.
        n: Number of trials.
        z: z-score of the confidence level.

    Returns:
        Lower and upper bound of the interval.
    """
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / d
    return centre - half, centre + half


def expand(name: str) -> str:
    """Expand a prefixed name into a full IRI.

    Args:
        name: Prefixed name, e.g. "ad:Ship".

    Returns:
        Full IRI, e.g. "https://github.com/HaoranGUO430/adrift#Ship".
    """
    for prefix, iri in PREFIXES.items():
        if name.startswith(prefix):
            return iri + name[len(prefix) :]
    return name


def shorten(iri: str) -> str:
    """Shorten a full IRI into a prefixed name.

    Args:
        iri: Full IRI, e.g. "https://github.com/HaoranGUO430/adrift#Ship".

    Returns:
        Prefixed name, e.g. "ad:Ship".
    """
    for prefix, base in PREFIXES.items():
        if iri.startswith(base):
            return prefix + iri[len(base) :]
    return iri
