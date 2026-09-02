"""SQLAlchemy models for the standalone fitness store."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class Base(DeclarativeBase):
    """Declarative base for fitness tables."""


class Meta(Base):
    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class Source(Base):
    """One imported original file. The full payload is stored compressed."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mtime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload_zlib: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ok")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    documents: Mapped[list[Document]] = relationship(back_populates="source")


class Document(Base):
    """One logical record extracted from a source (session, day, test, …)."""

    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("dedup_key", name="uq_documents_dedup_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sport_slug: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    sport_raw: Mapped[str | None] = mapped_column(String(128), nullable=True)
    polar_sport_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    ascent_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    descent_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    hr_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    hr_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    source: Mapped[Source] = relationship(back_populates="documents")
    track: Mapped[Track | None] = relationship(back_populates="document", uselist=False)


class Track(Base):
    """Cached GPX for a document that has a route."""

    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    gpx_zlib: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    document: Mapped[Document] = relationship(back_populates="track")


class ImportErrorRow(Base):
    __tablename__ = "import_errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
