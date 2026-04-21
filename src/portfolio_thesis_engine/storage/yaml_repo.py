"""YAML-file repositories — source of truth for human-edited entities.

Atomic writes use ``tempfile.NamedTemporaryFile`` in the target directory
followed by :func:`os.replace` so a mid-write crash never leaves a partial
file in place. Versioned repositories keep each version at
``{base}/{key}/{subdir}/{version}.yaml`` and maintain a ``current`` symlink
alongside them.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from portfolio_thesis_engine.schemas.base import BaseSchema
from portfolio_thesis_engine.schemas.company import CanonicalCompanyState
from portfolio_thesis_engine.schemas.ficha import Ficha
from portfolio_thesis_engine.schemas.market_context import MarketContext
from portfolio_thesis_engine.schemas.peer import Peer
from portfolio_thesis_engine.schemas.position import Position
from portfolio_thesis_engine.schemas.valuation import ValuationSnapshot
from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.storage.base import (
    NotFoundError,
    Repository,
    StorageError,
    VersionedRepository,
)


def _normalise_ticker(ticker: str) -> str:
    """Replace ``.`` with ``-`` so tickers like ``ASML.AS`` become safe
    directory names without colliding with filesystem conventions."""
    return ticker.replace(".", "-")


def _atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically.

    Writes to a temp file in the same directory first, then renames. If the
    rename fails, the temp file is cleaned up and the target is left
    untouched. ``os.replace`` is atomic on POSIX and Windows.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        tmp_path.replace(path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


class YAMLRepository[T: BaseSchema](Repository[T]):
    """Generic YAML-file repository.

    Subclasses typically override :meth:`_get_key` (to derive the entity key
    from its schema-specific identity field) and :meth:`_normalise_key` (to
    canonicalise caller-supplied lookup keys so that
    ``save(entity) → get(entity.ticker)`` round-trips even when the on-disk
    name differs from the human form — e.g. ``TEST.L`` stored as ``TEST-L``).
    """

    entity_class: type[T]
    base_path: Path
    filename_template: str

    def __init__(
        self,
        entity_class: type[T],
        base_path: Path,
        filename_template: str = "{key}.yaml",
    ) -> None:
        self.entity_class = entity_class
        self.base_path = base_path
        self.filename_template = filename_template

    def _normalise_key(self, key: str) -> str:
        """Canonicalise a lookup key to its on-disk form.

        Default is identity. Ticker-keyed subclasses override to apply
        :func:`_normalise_ticker` so callers can pass either ``TEST.L`` or
        ``TEST-L`` and hit the same file.
        """
        return key

    def _path_for(self, key: str) -> Path:
        normalised = self._normalise_key(key)
        return self.base_path / self.filename_template.format(key=normalised)

    def _get_key(self, entity: T) -> str:
        """Default: use the ``ticker`` attribute, normalised via
        :meth:`_normalise_key`."""
        ticker = getattr(entity, "ticker", None)
        if isinstance(ticker, str):
            return self._normalise_key(ticker)
        raise NotImplementedError(
            f"{type(self).__name__} must override _get_key for {type(entity).__name__}"
        )

    def get(self, key: str) -> T | None:
        path = self._path_for(key)
        if not path.exists():
            return None
        try:
            return self.entity_class.from_yaml(path.read_text(encoding="utf-8"))
        except Exception as e:  # pydantic, yaml, OS — any failure is storage
            raise StorageError(f"Failed to load {path}: {e}") from e

    def save(self, entity: T) -> None:
        key = self._get_key(entity)
        path = self._path_for(key)
        try:
            _atomic_write_text(path, entity.to_yaml())
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(f"Failed to save {path}: {e}") from e

    def delete(self, key: str) -> None:
        path = self._path_for(key)
        path.unlink(missing_ok=True)

    def list_keys(self) -> list[str]:
        """Default: list ``*.yaml`` files in ``base_path`` and return stems."""
        if not self.base_path.exists():
            return []
        return sorted(p.stem for p in self.base_path.glob("*.yaml"))

    def exists(self, key: str) -> bool:
        return self._path_for(key).exists()


class VersionedYAMLRepository[T: BaseSchema](VersionedRepository[T]):
    """Versioned YAML repository.

    Layout::

        {base_path}/{key}/{subdir}/{version}.yaml
        {base_path}/{key}/{subdir}/current          (symlink)

    ``save`` writes a new ``{version}.yaml`` and advances ``current`` to
    point at it. ``get`` and ``get_current`` read through the symlink.
    """

    def __init__(
        self,
        entity_class: type[T],
        base_path: Path,
        subdir: str,
    ) -> None:
        self.entity_class = entity_class
        self.base_path = base_path
        self.subdir = subdir

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------
    def _normalise_key(self, key: str) -> str:
        """Canonicalise a lookup key to its on-disk form. Default identity;
        ticker-keyed subclasses override."""
        return key

    def _dir_for(self, key: str) -> Path:
        return self.base_path / self._normalise_key(key) / self.subdir

    def _version_path(self, key: str, version: str) -> Path:
        return self._dir_for(key) / f"{version}.yaml"

    def _current_symlink(self, key: str) -> Path:
        return self._dir_for(key) / "current"

    def _get_key(self, entity: T) -> str:
        raise NotImplementedError

    def _get_version_id(self, entity: T) -> str:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Repository interface
    # ------------------------------------------------------------------
    def get(self, key: str) -> T | None:
        return self.get_current(key)

    def save(self, entity: T) -> None:
        key = self._get_key(entity)
        version = self._get_version_id(entity)
        path = self._version_path(key, version)
        try:
            _atomic_write_text(path, entity.to_yaml())
            self._retarget_current(key, version)
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(f"Failed to save version {version} of {key}: {e}") from e

    def delete(self, key: str) -> None:
        d = self.base_path / key / self.subdir
        if d.exists():
            shutil.rmtree(d)

    def list_keys(self) -> list[str]:
        if not self.base_path.exists():
            return []
        return sorted(
            p.name for p in self.base_path.iterdir() if p.is_dir() and (p / self.subdir).is_dir()
        )

    def exists(self, key: str) -> bool:
        return self._current_symlink(key).exists()

    # ------------------------------------------------------------------
    # VersionedRepository interface
    # ------------------------------------------------------------------
    def get_version(self, key: str, version: str) -> T | None:
        path = self._version_path(key, version)
        if not path.exists():
            return None
        try:
            return self.entity_class.from_yaml(path.read_text(encoding="utf-8"))
        except Exception as e:
            raise StorageError(f"Failed to load {path}: {e}") from e

    def list_versions(self, key: str) -> list[str]:
        d = self._dir_for(key)
        if not d.exists():
            return []
        return sorted(p.stem for p in d.glob("*.yaml"))

    def get_current(self, key: str) -> T | None:
        link = self._current_symlink(key)
        if not link.exists():
            return None
        try:
            return self.entity_class.from_yaml(link.read_text(encoding="utf-8"))
        except Exception as e:
            raise StorageError(f"Failed to load current version of {key}: {e}") from e

    def set_current(self, key: str, version: str) -> None:
        if not self._version_path(key, version).exists():
            raise NotFoundError(f"No version {version!r} for {key!r} in {self._dir_for(key)}")
        self._retarget_current(key, version)

    def _retarget_current(self, key: str, version: str) -> None:
        """Atomically swap the ``current`` symlink to point at ``{version}.yaml``.

        Creates a sibling temp symlink then :func:`os.replace`\\s it over the
        live one, so readers never see a missing or half-updated pointer.
        """
        d = self._dir_for(key)
        d.mkdir(parents=True, exist_ok=True)
        link = self._current_symlink(key)
        tmp_name = d / f".current.{os.getpid()}.tmp"
        tmp_name.unlink(missing_ok=True)
        tmp_name.symlink_to(f"{version}.yaml")
        tmp_name.replace(link)


# ----------------------------------------------------------------------
# Concrete repositories
# ----------------------------------------------------------------------


def _companies_root(base_path: Path | None) -> Path:
    return base_path or (settings.data_dir / "yamls" / "companies")


class CompanyRepository(YAMLRepository[Ficha]):
    """:class:`Ficha` persisted as ``companies/{ticker}/ficha.yaml``.

    Tickers are normalised on both save and lookup, so ``repo.get("TEST.L")``
    and ``repo.get("TEST-L")`` resolve to the same file.
    """

    def __init__(self, base_path: Path | None = None) -> None:
        super().__init__(
            entity_class=Ficha,
            base_path=_companies_root(base_path),
            filename_template="{key}/ficha.yaml",
        )

    def _normalise_key(self, key: str) -> str:
        return _normalise_ticker(key)

    def list_keys(self) -> list[str]:
        if not self.base_path.exists():
            return []
        return sorted(
            p.name for p in self.base_path.iterdir() if p.is_dir() and (p / "ficha.yaml").exists()
        )


class PositionRepository(YAMLRepository[Position]):
    """:class:`Position` persisted as ``portfolio/positions/{ticker}.yaml``.

    Tickers are normalised on both save and lookup.
    """

    def __init__(self, base_path: Path | None = None) -> None:
        super().__init__(
            entity_class=Position,
            base_path=base_path or (settings.data_dir / "yamls" / "portfolio" / "positions"),
        )

    def _normalise_key(self, key: str) -> str:
        return _normalise_ticker(key)


class PeerRepository(YAMLRepository[Peer]):
    """:class:`Peer` persisted as ``companies/{parent}/peers/{peer}.yaml``.

    One instance per parent company; pass ``parent_ticker`` to the
    constructor. Both parent and peer tickers are normalised.
    """

    def __init__(self, parent_ticker: str, base_path: Path | None = None) -> None:
        parent = _normalise_ticker(parent_ticker)
        super().__init__(
            entity_class=Peer,
            base_path=_companies_root(base_path) / parent / "peers",
        )

    def _normalise_key(self, key: str) -> str:
        return _normalise_ticker(key)


class MarketContextRepository(YAMLRepository[MarketContext]):
    """:class:`MarketContext` persisted as
    ``market_contexts/{cluster_id}/context.yaml``."""

    def __init__(self, base_path: Path | None = None) -> None:
        super().__init__(
            entity_class=MarketContext,
            base_path=base_path or (settings.data_dir / "yamls" / "market_contexts"),
            filename_template="{key}/context.yaml",
        )

    def _get_key(self, entity: MarketContext) -> str:
        return entity.cluster_id

    def list_keys(self) -> list[str]:
        if not self.base_path.exists():
            return []
        return sorted(
            p.name for p in self.base_path.iterdir() if p.is_dir() and (p / "context.yaml").exists()
        )


class ValuationRepository(VersionedYAMLRepository[ValuationSnapshot]):
    """Versioned :class:`ValuationSnapshot` under ``companies/{ticker}/valuation/``.

    Version ID is ``snapshot.snapshot_id``. Tickers are normalised on both
    save and lookup.
    """

    def __init__(self, base_path: Path | None = None) -> None:
        super().__init__(
            entity_class=ValuationSnapshot,
            base_path=_companies_root(base_path),
            subdir="valuation",
        )

    def _normalise_key(self, key: str) -> str:
        return _normalise_ticker(key)

    def _get_key(self, entity: ValuationSnapshot) -> str:
        return self._normalise_key(entity.ticker)

    def _get_version_id(self, entity: ValuationSnapshot) -> str:
        return entity.snapshot_id


class CompanyStateRepository(VersionedYAMLRepository[CanonicalCompanyState]):
    """Versioned :class:`CanonicalCompanyState` under
    ``companies/{ticker}/extraction/``.

    Version ID is ``state.extraction_id``. Tickers are normalised on both
    save and lookup.
    """

    def __init__(self, base_path: Path | None = None) -> None:
        super().__init__(
            entity_class=CanonicalCompanyState,
            base_path=_companies_root(base_path),
            subdir="extraction",
        )

    def _normalise_key(self, key: str) -> str:
        return _normalise_ticker(key)

    def _get_key(self, entity: CanonicalCompanyState) -> str:
        return self._normalise_key(entity.identity.ticker)

    def _get_version_id(self, entity: CanonicalCompanyState) -> str:
        return entity.extraction_id
