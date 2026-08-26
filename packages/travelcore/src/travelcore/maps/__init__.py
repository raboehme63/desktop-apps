"""Map backend abstraction. Folium/Leaflet is one implementation, not the API."""

from travelcore.maps.backend import FoliumMapBackend, MapBackend
from travelcore.maps.scene import (
    FLIGHT_LINE_MIN_ZOOM,
    MapMarker,
    MapPolyline,
    MapScene,
    build_map_scene,
    downsample_points,
)
from travelcore.maps.static import render_leaflet_excerpt

__all__ = [
    "FLIGHT_LINE_MIN_ZOOM",
    "FoliumMapBackend",
    "MapBackend",
    "MapMarker",
    "MapPolyline",
    "MapScene",
    "build_map_scene",
    "downsample_points",
    "render_leaflet_excerpt",
]
