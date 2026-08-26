"""YouTube and IGC-related links attached to timeline days and sections."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from travelcore.exceptions import ProjectError

_YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "www.youtu.be",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }
)


def is_igc_filename(name: str) -> bool:
    return Path(name).suffix.lower() == ".igc"


def parse_youtube_urls(raw: str | None) -> tuple[str, ...]:
    if not raw or not str(raw).strip():
        return ()
    text = str(raw).strip()
    collected: list[str] = []
    if text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            collected = [str(item).strip() for item in data if str(item).strip()]
    else:
        collected = [line.strip() for line in text.replace(",", "\n").splitlines() if line.strip()]
    result: list[str] = []
    for item in collected:
        try:
            normalized = normalize_youtube_url(item)
        except ProjectError:
            continue
        if normalized and normalized not in result:
            result.append(normalized)
    return tuple(result)


def serialize_youtube_urls(urls: list[str]) -> str | None:
    cleaned: list[str] = []
    for item in urls:
        normalized = normalize_youtube_url(item)
        if normalized and normalized not in cleaned:
            cleaned.append(normalized)
    if not cleaned:
        return None
    return json.dumps(cleaned, ensure_ascii=False)


def normalize_youtube_url(url: str) -> str:
    text = url.strip()
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        text = f"https://{text}"
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if host not in _YOUTUBE_HOSTS:
        raise ProjectError("Bitte nur YouTube-Links eintragen (youtube.com oder youtu.be).")
    return text


def youtube_video_id(url: str) -> str | None:
    try:
        normalized = normalize_youtube_url(url)
    except ProjectError:
        return None
    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower()
    path_parts = [part for part in parsed.path.split("/") if part]
    if host in {"youtu.be", "www.youtu.be"}:
        return _clean_youtube_id(path_parts[0] if path_parts else "")
    query_id = parse_qs(parsed.query).get("v", [""])[0]
    if query_id:
        return _clean_youtube_id(query_id)
    if path_parts and path_parts[0] in {"embed", "shorts", "live", "v"} and len(path_parts) >= 2:
        return _clean_youtube_id(path_parts[1])
    return None


def youtube_thumbnail_url(url: str) -> str | None:
    video_id = youtube_video_id(url)
    if not video_id:
        return None
    return f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"


def _clean_youtube_id(value: str) -> str | None:
    text = value.strip()
    if not text or len(text) > 64:
        return None
    return text


def parse_leonardo_urls(raw: str | None) -> tuple[str, ...]:
    if not raw or not str(raw).strip():
        return ()
    text = str(raw).strip()
    collected: list[str] = []
    if text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            collected = [str(item).strip() for item in data if str(item).strip()]
    else:
        collected = [line.strip() for line in text.replace(",", "\n").splitlines() if line.strip()]
    result: list[str] = []
    for item in collected:
        try:
            normalized = normalize_leonardo_url(item)
        except ProjectError:
            continue
        if normalized and normalized not in result:
            result.append(normalized)
    return tuple(result)


def serialize_leonardo_urls(urls: list[str]) -> str | None:
    cleaned: list[str] = []
    for item in urls:
        normalized = normalize_leonardo_url(item)
        if normalized and normalized not in cleaned:
            cleaned.append(normalized)
    if not cleaned:
        return None
    return json.dumps(cleaned, ensure_ascii=False)


def normalize_leonardo_url(url: str) -> str:
    text = url.strip()
    if not text:
        return ""
    existing = urlparse(text)
    if existing.scheme and existing.scheme not in {"http", "https"}:
        raise ProjectError("Der DHV-Leonardo-Link muss mit http:// oder https:// beginnen.")
    if not text.startswith(("http://", "https://")):
        text = f"https://{text}"
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProjectError("Der DHV-Leonardo-Link muss mit http:// oder https:// beginnen.")
    return text
