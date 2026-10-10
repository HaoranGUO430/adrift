"""Common functions here"""


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
