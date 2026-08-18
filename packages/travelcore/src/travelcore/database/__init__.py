"""SQLAlchemy persistence for travel projects."""

from travelcore.database.models import (
    Base,
    Event,
    ExportConfig,
    FileError,
    GpsPoint,
    GpsTrack,
    OvernightStay,
    Photo,
    PhotoAnalysis,
    Place,
    Project,
    SimilarityGroup,
    SimilarityGroupMember,
    SourceFile,
    TextNote,
    Trip,
    TripDay,
    Video,
)
from travelcore.database.project_store import ProjectStore
from travelcore.database.session import create_session_factory, sqlite_url, upgrade_database

__all__ = [
    "Base",
    "Event",
    "ExportConfig",
    "FileError",
    "GpsPoint",
    "GpsTrack",
    "OvernightStay",
    "Photo",
    "PhotoAnalysis",
    "Place",
    "Project",
    "ProjectStore",
    "SimilarityGroup",
    "SimilarityGroupMember",
    "SourceFile",
    "TextNote",
    "Trip",
    "TripDay",
    "Video",
    "create_session_factory",
    "sqlite_url",
    "upgrade_database",
]
