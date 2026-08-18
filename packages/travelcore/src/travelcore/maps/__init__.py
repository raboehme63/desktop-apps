"""Map backend abstraction. Folium/Leaflet is one implementation, not the API."""

from travelcore.maps.backend import FoliumMapBackend, MapBackend
from travelcore.maps.scene import MapMarker, MapPolyline, MapScene, build_map_scene, downsample_points

__all__ = [
    "FoliumMapBackend",
    "MapBackend",
    "MapMarker",
    "MapPolyline",
    "MapScene",
    "build_map_scene",
    "downsample_points",
]
