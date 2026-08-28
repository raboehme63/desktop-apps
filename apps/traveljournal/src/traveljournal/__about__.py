"""Application identity. Keep in sync with apps/traveljournal/pyproject.toml."""

__version__ = "2.0.0"
APP_NAME = "Reisetagebuch"


def app_window_title(project_name: str | None = None) -> str:
    """Title bar: ``Reisetagebuch R2.0.0`` or ``Reisetagebuch R2.0.0 - Titel``."""

    base = f"{APP_NAME} R{__version__}"
    title = (project_name or "").strip()
    if title:
        return f"{base} - {title}"
    return base
