"""Public exception types for fitnesscore."""


class FitnessError(Exception):
    """Base error for fitness store failures."""


class StoreError(FitnessError):
    """Raised when the fitness database cannot be created or opened."""


class ImportFileError(FitnessError):
    """Raised when a source file cannot be imported."""


class QueryError(FitnessError):
    """Raised when a query cannot be executed."""
