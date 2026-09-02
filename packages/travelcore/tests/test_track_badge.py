from pathlib import Path

from travelcore.gps.track_badge import TRACK_BADGE_ACT, TRACK_BADGE_IGC, TRACK_BADGE_MAP, track_badge_for


def test_track_badge_for_map_act_igc() -> None:
    assert track_badge_for(Path("D:/fotos/.MapTracks/Map-Track.gpx")) == TRACK_BADGE_MAP
    assert track_badge_for(Path("D:/fotos/.FitnessTracks/ride.gpx")) == TRACK_BADGE_ACT
    assert track_badge_for(Path("D:/fotos/tag1/walk.gpx")) is None
    assert track_badge_for(Path("D:/fotos/.IGCTracks/flug.igc")) == TRACK_BADGE_IGC
    assert track_badge_for(Path("D:/fotos/tag1/flug.igc")) == TRACK_BADGE_IGC
    assert track_badge_for(Path("D:/fotos/tag1/foto.jpg")) is None
