"""In-memory trip hierarchy. Persistence lives in ``travelcore.database``."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class MediaItem(BaseModel):
    source_file_id: int
    path: str
    caption: str | None = None
    used_in_journal: bool = False
    origin: str = "auto"


class TextNote(BaseModel):
    title: str | None = None
    body: str = ""
    origin: str = "manual"


class Place(BaseModel):
    name: str
    latitude: float | None = None
    longitude: float | None = None
    confirmed: bool = False
    origin: str = "auto"


class Event(BaseModel):
    title: str
    occurred_at: dt.datetime | None = None
    origin: str = "auto"
    media: list[MediaItem] = Field(default_factory=list)
    notes: list[TextNote] = Field(default_factory=list)


class TripDay(BaseModel):
    day_index: int
    title: str | None = None
    date: dt.date | None = None
    notes: str | None = None
    origin: str = "auto"
    places: list[Place] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)


class Trip(BaseModel):
    title: str
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    origin: str = "auto"
    days: list[TripDay] = Field(default_factory=list)
