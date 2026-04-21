"""Abstract repository interfaces and the UnitOfWork transaction boundary.

Every storage backend (YAML, DuckDB, SQLite, Chroma, filesystem, in-memory)
implements either :class:`Repository` or :class:`VersionedRepository`.
Typed exceptions are re-exported from :mod:`shared.exceptions` so callers
can ``from portfolio_thesis_engine.storage.base import StorageError``
without crossing layer boundaries.

**Ticker normalisation contract.** Tickers routinely contain a dot
(``ASML.AS``, ``BRK.B``, ``TEST.L``) which is awkward on POSIX filesystems
and in SQL LIKE patterns. :func:`normalise_ticker` replaces ``.`` with
``-``; every repository that takes a ticker — by that name or as a primary
``key`` — normalises before touching disk or DB. Callers may therefore
pass **either form interchangeably**::

    repo.save(ficha)                 # ticker='TEST.L'
    repo.get('TEST.L')  == ficha     # dotted form works
    repo.get('TEST-L')  == ficha     # normalised form works too

The transform is idempotent: ``normalise_ticker('TEST-L') == 'TEST-L'``.
"""

from abc import ABC, abstractmethod
from types import TracebackType

from portfolio_thesis_engine.schemas.base import BaseSchema
from portfolio_thesis_engine.shared.exceptions import (
    NotFoundError,
    StorageError,
    VersionConflictError,
)

__all__ = [
    "NotFoundError",
    "Repository",
    "StorageError",
    "UnitOfWork",
    "VersionConflictError",
    "VersionedRepository",
    "normalise_ticker",
]


def normalise_ticker(ticker: str) -> str:
    """Canonical on-disk / on-DB form of a ticker.

    Replaces every ``.`` with ``-``. Idempotent — calling it twice is the
    same as once. Empty string passes through untouched so callers can
    compose freely with other validation.
    """
    return ticker.replace(".", "-")


class Repository[T: BaseSchema](ABC):
    """CRUD contract for an entity type keyed by a string primary key.

    Implementations that use ticker-based keys must normalise their key
    argument in every public method (``get``, ``save``, ``delete``,
    ``exists``, ``list_keys``, and versioned variants). See the
    module-level docstring for the normalisation contract.
    """

    @abstractmethod
    def get(self, key: str) -> T | None:
        """Return entity by key, or ``None`` if absent."""

    @abstractmethod
    def save(self, entity: T) -> None:
        """Persist entity. Idempotent — safe to rerun."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove entity by key. No-op if absent."""

    @abstractmethod
    def list_keys(self) -> list[str]:
        """Return all primary keys in sorted order."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return ``True`` if an entity with this key is persisted."""


class VersionedRepository[T: BaseSchema](Repository[T]):
    """Repository that keeps every saved version and tracks a ``current`` pointer.

    :meth:`save` always creates a new version and advances ``current``; prior
    versions remain retrievable via :meth:`get_version`. :meth:`get` is
    expected to delegate to :meth:`get_current`.
    """

    @abstractmethod
    def get_version(self, key: str, version: str) -> T | None:
        """Return a specific version, or ``None`` if absent."""

    @abstractmethod
    def list_versions(self, key: str) -> list[str]:
        """Return all version identifiers for ``key`` in sorted order."""

    @abstractmethod
    def get_current(self, key: str) -> T | None:
        """Return the current (latest) version, or ``None`` if absent."""

    @abstractmethod
    def set_current(self, key: str, version: str) -> None:
        """Mark ``version`` as current. Raises :class:`NotFoundError` if
        the version does not exist."""


class UnitOfWork:
    """Transaction boundary — Phase 0 stub.

    Phase 1 will replace this with real cross-repository transactional
    semantics (begin / commit / rollback across YAML, DuckDB, SQLite, and
    Chroma). For now it is a no-op context manager so call sites can already
    adopt the pattern:

    .. code-block:: python

        with UnitOfWork() as uow:
            company_repo.save(ficha)
            valuation_repo.save(snapshot)
            uow.commit()

    Current behaviour: every repository operation is applied immediately.
    ``rollback`` on exit is a no-op.
    """

    def __enter__(self) -> "UnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """TODO Phase 1: rollback all pending repo ops if ``exc_type`` is set."""

    def commit(self) -> None:
        """TODO Phase 1: flush pending writes across all registered repos."""

    def rollback(self) -> None:
        """TODO Phase 1: undo pending writes since last commit."""
