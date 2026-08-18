"""Stay detection and reverse-geocoding hooks.

Stay-detection parameters (radius, minimum duration) belong in ``AppSettings``.
Automatically detected places are suggestions until the user confirms, edits,
or deletes them. Reverse-Geocoding bleibt bewusst aus (OP-01).
"""

from travelcore.geolocation.stays import StayCluster, cluster_stays, haversine_m

__all__ = ["StayCluster", "cluster_stays", "haversine_m"]
