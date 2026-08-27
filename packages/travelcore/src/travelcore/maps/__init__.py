"""Map backend abstraction. Folium/Leaflet is one implementation, not the API."""

from travelcore.maps.backend import FoliumMapBackend, MapBackend, leaflet_payload, timeline_js_cards
from travelcore.maps.cache import (
    MapRenderResult,
    ensure_map_cache,
    is_map_cache_current,
    map_cache_identity,
    read_cached_map,
    tiles_for_map_provider,
)
from travelcore.maps.groups import (
    MapTimelineCard,
    build_map_group_detail,
    build_map_overview,
    build_map_timeline,
    parse_group_key,
    stay_links_from_entries,
)
from travelcore.maps.scene import (
    COVER_ICON_PX,
    FLIGHT_LINE_MIN_ZOOM,
    PHOTO_STACK_DISABLE_ZOOM,
    MapMarker,
    MapPolyline,
    MapScene,
    StayLink,
    build_map_scene,
    downsample_points,
    photo_fov_degrees,
    stay_link_visible,
)
from travelcore.maps.static import render_leaflet_excerpt

__all__ = [
    "COVER_ICON_PX",
    "FLIGHT_LINE_MIN_ZOOM",
    "PHOTO_STACK_DISABLE_ZOOM",
    "FoliumMapBackend",
    "MapBackend",
    "MapMarker",
    "MapPolyline",
    "MapRenderResult",
    "MapScene",
    "MapTimelineCard",
    "StayLink",
    "build_map_group_detail",
    "build_map_overview",
    "build_map_scene",
    "build_map_timeline",
    "downsample_points",
    "ensure_map_cache",
    "is_map_cache_current",
    "leaflet_payload",
    "map_cache_identity",
    "parse_group_key",
    "photo_fov_degrees",
    "read_cached_map",
    "render_leaflet_excerpt",
    "stay_link_visible",
    "stay_links_from_entries",
    "tiles_for_map_provider",
    "timeline_js_cards",
]
