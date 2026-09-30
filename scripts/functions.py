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
