"""SQLAlchemy 2.0 models for a travel project database.

Automatically generated rows use origin='auto'. User edits use origin='manual'.
Original media files are never stored in the database, only path references.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class Base(DeclarativeBase):
    """Declarative base for all project tables."""


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_root: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    settings_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_files: Mapped[list[SourceFile]] = relationship(back_populates="project")
    trips: Mapped[list[Trip]] = relationship(back_populates="project")
    file_errors: Mapped[list[FileError]] = relationship(back_populates="project")


class SourceFile(Base):
    """Central file index. One row per discovered source file."""

    __tablename__ = "source_files"
    __table_args__ = (UniqueConstraint("project_id", "path", name="uq_source_files_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    extension: Mapped[str] = mapped_column(String(32), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    fs_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fs_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ok")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    captured_at_raw: Mapped[str | None] = mapped_column(String(64), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    captured_at_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timezone_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timezone_unknown: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    gps_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_altitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    position_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_time_delta_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    heading_degrees: Mapped[float | None] = mapped_column(Float, nullable=True)
    heading_ref: Mapped[str | None] = mapped_column(String(8), nullable=True)
    heading_source: Mapped[str | None] = mapped_column(String(32), nullable=True)

    camera: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lens: Mapped[str | None] = mapped_column(String(255), nullable=True)
    focal_length: Mapped[float | None] = mapped_column(Float, nullable=True)
    focal_length_35mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    iso: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exposure_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    aperture: Mapped[str | None] = mapped_column(String(32), nullable=True)
    orientation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rotation_degrees: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    project: Mapped[Project] = relationship(back_populates="source_files")
    photo: Mapped[Photo | None] = relationship(back_populates="source_file")
    video: Mapped[Video | None] = relationship(back_populates="source_file")


class FileError(Base):
    __tablename__ = "file_errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    project: Mapped[Project] = relationship(back_populates="file_errors")


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), nullable=False, unique=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    used_in_journal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_cover: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")

    source_file: Mapped[SourceFile] = relationship(back_populates="photo")
    analysis: Mapped[PhotoAnalysis | None] = relationship(back_populates="photo")


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), nullable=False, unique=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")

    source_file: Mapped[SourceFile] = relationship(back_populates="video")


class GpsTrack(Base):
    __tablename__ = "gps_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("source_files.id"), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    track_format: Mapped[str] = mapped_column(String(16), nullable=False, default="gpx")
    pilot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    points: Mapped[list[GpsPoint]] = relationship(back_populates="track")


class GpsPoint(Base):
    __tablename__ = "gps_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("gps_tracks.id"), nullable=False, index=True)
    segment_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    altitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    track: Mapped[GpsTrack] = relationship(back_populates="points")


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")

    project: Mapped[Project] = relationship(back_populates="trips")
    days: Mapped[list[TripDay]] = relationship(back_populates="trip")
    sections: Mapped[list[TripSection]] = relationship(back_populates="trip")


class TripDay(Base):
    __tablename__ = "trip_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"), nullable=False, index=True)
    day_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    youtube_urls: Mapped[str | None] = mapped_column(Text, nullable=True)
    leonardo_urls: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_source_file_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")

    trip: Mapped[Trip] = relationship(back_populates="days")
    places: Mapped[list[Place]] = relationship(back_populates="day")
    events: Mapped[list[Event]] = relationship(back_populates="day")
    text_notes: Mapped[list[TextNote]] = relationship(back_populates="day")


class TripSection(Base):
    """Thematic journal block. May span or split calendar days via member timestamps."""

    __tablename__ = "trip_sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_from: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pin_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    pin_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    youtube_urls: Mapped[str | None] = mapped_column(Text, nullable=True)
    leonardo_urls: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_source_file_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outbound_geometry: Mapped[str | None] = mapped_column(String(16), nullable=True)
    outbound_dash: Mapped[str | None] = mapped_column(String(16), nullable=True)
    outbound_symbol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")

    trip: Mapped[Trip] = relationship(back_populates="sections")
    members: Mapped[list[SectionMember]] = relationship(back_populates="section")
    transfer_links: Mapped[list[TransferLink]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
    )


class TransferLink(Base):
    """One ordered connection line owned by a Transfer section."""

    __tablename__ = "transfer_links"
    __table_args__ = (UniqueConstraint("section_id", "sort_index", name="uq_transfer_links_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("trip_sections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    geometry: Mapped[str] = mapped_column(String(16), nullable=False, default="line")
    dash: Mapped[str] = mapped_column(String(16), nullable=False, default="solid")
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    end_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    track_source_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True
    )

    section: Mapped[TripSection] = relationship(back_populates="transfer_links")


class SectionMember(Base):
    __tablename__ = "section_members"
    __table_args__ = (UniqueConstraint("source_file_id", name="uq_section_members_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("trip_sections.id"), nullable=False, index=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), nullable=False, index=True)
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    journal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    journal_timezone_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    journal_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    journal_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    section: Mapped[TripSection] = relationship(back_populates="members")


class Place(Base):
    __tablename__ = "places"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day_id: Mapped[int | None] = mapped_column(ForeignKey("trip_days.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    radius_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    departed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")

    day: Mapped[TripDay | None] = relationship(back_populates="places")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day_id: Mapped[int | None] = mapped_column(ForeignKey("trip_days.id"), nullable=True, index=True)
    place_id: Mapped[int | None] = mapped_column(ForeignKey("places.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")

    day: Mapped[TripDay | None] = relationship(back_populates="events")


class TextNote(Base):
    __tablename__ = "text_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day_id: Mapped[int | None] = mapped_column(ForeignKey("trip_days.id"), nullable=True, index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"), nullable=True)
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("source_files.id"), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")

    day: Mapped[TripDay | None] = relationship(back_populates="text_notes")


class PhotoAnalysis(Base):
    __tablename__ = "photo_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    photo_id: Mapped[int] = mapped_column(ForeignKey("photos.id"), nullable=False, unique=True)
    resolution_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    brightness: Mapped[float | None] = mapped_column(Float, nullable=True)
    contrast: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpness: Mapped[float | None] = mapped_column(Float, nullable=True)
    overexposed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    underexposed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    technical_quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    photo: Mapped[Photo] = relationship(back_populates="analysis")


class SimilarityGroup(Base):
    __tablename__ = "similarity_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    cluster_type: Mapped[str] = mapped_column(String(16), nullable=False, default="stack")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="accepted")
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")

    members: Mapped[list[SimilarityGroupMember]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class SimilarityGroupMember(Base):
    __tablename__ = "similarity_group_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("similarity_groups.id"), nullable=False, index=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), nullable=False)
    distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    group: Mapped[SimilarityGroup] = relationship(back_populates="members")


class ExportConfig(Base):
    __tablename__ = "export_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    exporter: Mapped[str] = mapped_column(String(64), nullable=False)
    settings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_export_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
