"""Quality metrics used as recommendations only — never for automatic deletion."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageFilter, UnidentifiedImageError

QUALITY_GREEN = "green"
QUALITY_YELLOW = "yellow"
QUALITY_RED = "red"

# Ampel from technical_quality (konzept §9.2).
GREEN_MIN = 0.66
YELLOW_MIN = 0.40

_ANALYZE_EDGE = 768
_RED_MAX_PIXELS = 800_000
_RED_MIN_SIDE = 600
_SHARP_YELLOW_MAX = 0.22


@dataclass(frozen=True, slots=True)
class QualityMetrics:
    width: int | None
    height: int | None
    aspect_ratio: float | None
    brightness: float | None
    contrast: float | None
    sharpness: float | None
    overexposed: bool | None
    underexposed: bool | None
    technical_quality: float | None
    resolution_score: float | None = None
    light: str | None = None


class QualityAnalyzer(Protocol):
    def analyze(self, path: Path) -> QualityMetrics:
        """Inspect a photo without modifying it."""
        ...


def quality_light(score: float | None) -> str | None:
    """Map ``technical_quality`` (0–1) to green / yellow / red."""

    if score is None:
        return None
    if score >= GREEN_MIN:
        return QUALITY_GREEN
    if score >= YELLOW_MIN:
        return QUALITY_YELLOW
    return QUALITY_RED


def quality_light_label(light: str | None) -> str | None:
    if light == QUALITY_GREEN:
        return "Qualität gut"
    if light == QUALITY_YELLOW:
        return "Qualität mittel"
    if light == QUALITY_RED:
        return "Qualität schwach"
    return None


def quality_tooltip(
    *,
    technical_quality: float | None,
    resolution_score: float | None = None,
    sharpness: float | None = None,
    contrast: float | None = None,
    overexposed: bool | None = None,
    underexposed: bool | None = None,
    width: int | None = None,
    height: int | None = None,
) -> str | None:
    """Headline plus the component ratings that explain the Ampel."""

    overall = quality_light(technical_quality)
    headline = quality_light_label(overall)
    if headline is None or overall is None:
        return None
    notes = _decisive_quality_notes(
        overall,
        resolution_score=resolution_score,
        sharpness=sharpness,
        contrast=contrast,
        overexposed=overexposed,
        underexposed=underexposed,
        width=width,
        height=height,
    )
    if not notes:
        return headline
    return headline + "\n" + " · ".join(notes)


def _light_word(light: str) -> str:
    if light == QUALITY_GREEN:
        return "gut"
    if light == QUALITY_YELLOW:
        return "mittel"
    return "schwach"


def _light_rank(light: str) -> int:
    if light == QUALITY_GREEN:
        return 0
    if light == QUALITY_YELLOW:
        return 1
    return 2


def _low_resolution(width: int | None, height: int | None) -> bool:
    if not width or not height:
        return False
    return width * height < _RED_MAX_PIXELS or min(width, height) < _RED_MIN_SIDE


def _decisive_quality_notes(
    overall: str,
    *,
    resolution_score: float | None,
    sharpness: float | None,
    contrast: float | None,
    overexposed: bool | None,
    underexposed: bool | None,
    width: int | None,
    height: int | None,
) -> list[str]:
    candidates: list[tuple[int, str]] = []
    resolution_light = quality_light(resolution_score)
    if _low_resolution(width, height):
        resolution_light = QUALITY_RED
    if resolution_light is not None and resolution_light != QUALITY_GREEN:
        candidates.append((_light_rank(resolution_light), f"Auflösung {_light_word(resolution_light)}"))
    sharp_score = None if sharpness is None else _clamp(sharpness / 28.0)
    sharp_light = quality_light(sharp_score)
    if sharp_light is not None and sharp_light != QUALITY_GREEN:
        candidates.append((_light_rank(sharp_light), f"Schärfe {_light_word(sharp_light)}"))
    if overexposed or underexposed:
        if overexposed and underexposed:
            detail = "über- und unterbelichtet"
        elif overexposed:
            detail = "überbelichtet"
        else:
            detail = "unterbelichtet"
        candidates.append((_light_rank(QUALITY_RED), f"Belichtung schwach ({detail})"))
    contrast_score = None if contrast is None else _clamp(contrast / 0.22)
    contrast_light = quality_light(contrast_score)
    if contrast_light is not None and contrast_light != QUALITY_GREEN:
        candidates.append((_light_rank(contrast_light), f"Kontrast {_light_word(contrast_light)}"))
    if overall == QUALITY_GREEN:
        return []
    need = _light_rank(overall)
    selected = [note for rank, note in candidates if rank >= need]
    if selected:
        return selected
    return [note for rank, note in candidates if rank >= 1]


class PillowQualityAnalyzer:
    """Read-only Pillow analyzer for JPEG/PNG/WebP/TIFF (and any Pillow-openable file)."""

    def analyze(self, path: Path) -> QualityMetrics:
        return analyze_photo(path)


def analyze_photo(
    path: Path,
    *,
    width_hint: int | None = None,
    height_hint: int | None = None,
) -> QualityMetrics:
    """Compute metrics from the file. The original is never written."""

    image = _open_image(path)
    if image is None:
        return _resolution_only(width_hint, height_hint)
    try:
        width, height = image.size
        if width_hint and height_hint:
            width, height = width_hint, height_hint
        aspect = (width / height) if width and height else None
        sample = _analysis_sample(image)
        brightness, contrast, sharpness, over_frac, under_frac = _pixel_stats(sample)
        overexposed = over_frac > 0.08
        underexposed = under_frac > 0.08
        resolution = _resolution_score(width, height)
        sharp_score = _clamp((sharpness or 0.0) / 28.0)
        exposure = _exposure_score(brightness, over_frac, under_frac)
        contrast_score = _clamp((contrast or 0.0) / 0.22)
        technical = _clamp(
            0.28 * resolution
            + 0.34 * sharp_score
            + 0.22 * exposure
            + 0.16 * contrast_score
        )
        technical = _apply_quality_caps(
            technical,
            width=width,
            height=height,
            sharp_score=sharp_score,
            overexposed=overexposed,
            underexposed=underexposed,
        )
        return QualityMetrics(
            width=width,
            height=height,
            aspect_ratio=aspect,
            brightness=brightness,
            contrast=contrast,
            sharpness=sharpness,
            overexposed=overexposed,
            underexposed=underexposed,
            technical_quality=_clamp(technical),
            resolution_score=resolution,
            light=quality_light(_clamp(technical)),
        )
    finally:
        image.close()


def _resolution_only(width: int | None, height: int | None) -> QualityMetrics:
    if not width or not height:
        return QualityMetrics(
            width=width,
            height=height,
            aspect_ratio=None,
            brightness=None,
            contrast=None,
            sharpness=None,
            overexposed=None,
            underexposed=None,
            technical_quality=None,
            resolution_score=None,
            light=None,
        )
    resolution = _resolution_score(width, height)
    technical = _apply_quality_caps(
        _clamp(0.5 * resolution + 0.25),
        width=width,
        height=height,
        sharp_score=1.0,
        overexposed=False,
        underexposed=False,
    )
    return QualityMetrics(
        width=width,
        height=height,
        aspect_ratio=width / height,
        brightness=None,
        contrast=None,
        sharpness=None,
        overexposed=None,
        underexposed=None,
        technical_quality=_clamp(technical),
        resolution_score=resolution,
        light=quality_light(_clamp(technical)),
    )


def _open_image(path: Path) -> Image.Image | None:
    try:
        image = Image.open(path)
        image.load()
        return image
    except (OSError, UnidentifiedImageError, ValueError):
        return None


def _analysis_sample(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    rgb.thumbnail((_ANALYZE_EDGE, _ANALYZE_EDGE), Image.Resampling.BILINEAR)
    return rgb


def _pixel_stats(image: Image.Image) -> tuple[float, float, float, float, float]:
    gray = image.convert("L")
    pixels = _luma_values(gray)
    count = max(len(pixels), 1)
    mean = sum(pixels) / count / 255.0
    variance = sum((value / 255.0 - mean) ** 2 for value in pixels) / count
    contrast = math.sqrt(variance)
    over_frac = sum(1 for value in pixels if value >= 250) / count
    under_frac = sum(1 for value in pixels if value <= 5) / count
    laplacian = gray.filter(
        ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)
    )
    lap_pixels = _luma_values(laplacian)
    lap_mean = sum(lap_pixels) / count
    sharpness = math.sqrt(sum((value - lap_mean) ** 2 for value in lap_pixels) / count)
    return mean, contrast, sharpness, over_frac, under_frac


def _luma_values(image: Image.Image) -> list[int]:
    flattened = getattr(image, "get_flattened_data", None)
    if flattened is not None:
        return [int(value) for value in flattened()]
    return [int(value) for value in image.getdata()]


def _apply_quality_caps(
    score: float,
    *,
    width: int,
    height: int,
    sharp_score: float,
    overexposed: bool,
    underexposed: bool,
) -> float:
    """Hard limits so low resolution, blur, or bad exposure cannot stay green."""

    pixels = width * height
    if pixels < _RED_MAX_PIXELS or min(width, height) < _RED_MIN_SIDE:
        return min(score, YELLOW_MIN - 0.01)
    if sharp_score < _SHARP_YELLOW_MAX or overexposed or underexposed:
        return min(score, GREEN_MIN - 0.01)
    return score


def _resolution_score(width: int | None, height: int | None) -> float:
    if not width or not height:
        return 0.0
    pixels = max(width * height, 1)
    low = math.log10(250_000)
    high = math.log10(12_000_000)
    return _clamp((math.log10(pixels) - low) / (high - low))


def _exposure_score(brightness: float, over_frac: float, under_frac: float) -> float:
    brightness_pen = abs(brightness - 0.45) * 1.4
    clip_pen = (over_frac + under_frac) * 3.0
    return _clamp(1.0 - brightness_pen - clip_pen)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
