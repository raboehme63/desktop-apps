"""Public exception types for travelcore."""


class TravelCoreError(Exception):
    """Base error for all travelcore failures."""


class ProjectError(TravelCoreError):
    """Raised when a travel project cannot be created or opened."""


class ImportError_(TravelCoreError):
    """Raised when a source directory cannot be indexed.

    Named with a trailing underscore to avoid clashing with the builtin.
    """


class UnsupportedFileError(TravelCoreError):
    """Raised when a file type is not supported."""


class MetadataError(TravelCoreError):
    """Raised when metadata cannot be read from a media file."""


class GpsError(TravelCoreError):
    """Raised when a GPS track cannot be parsed or matched."""


class ExportError(TravelCoreError):
    """Raised when an export backend fails."""


class DatabaseError(TravelCoreError):
    """Raised when the project database cannot be used."""
