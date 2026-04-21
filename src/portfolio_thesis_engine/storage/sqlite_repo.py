"""SQLite-backed metadata repository for relational lookups.

Tables:

- ``companies``         — master list of tickers
- ``archetypes``        — profile definitions (P1, P2, ...)
- ``clusters``          — market cluster definitions
- ``company_clusters``  — company × cluster many-to-many
- ``company_peers``     — target company × peer many-to-many

Uses SQLAlchemy 2.0 declarative style with typed mappings. All operations
are scoped to a single session per call for safety.

Ticker arguments are normalised per the ``storage.base`` contract —
callers pass either ``TEST.L`` or ``TEST-L``; the stored value is always
the hyphenated form so DB queries are consistent regardless of how the
caller typed the ticker.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import ForeignKey, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.storage.base import NotFoundError, StorageError, normalise_ticker


class _Base(DeclarativeBase):
    pass


class CompanyRow(_Base):
    __tablename__ = "companies"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    profile: Mapped[str]
    currency: Mapped[str]
    exchange: Mapped[str]
    isin: Mapped[str | None] = mapped_column(default=None)


class ArchetypeRow(_Base):
    __tablename__ = "archetypes"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    description: Mapped[str | None] = mapped_column(default=None)


class ClusterRow(_Base):
    __tablename__ = "clusters"

    cluster_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    description: Mapped[str | None] = mapped_column(default=None)


class CompanyClusterRow(_Base):
    __tablename__ = "company_clusters"

    ticker: Mapped[str] = mapped_column(ForeignKey("companies.ticker"), primary_key=True)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.cluster_id"), primary_key=True)

    company: Mapped[CompanyRow] = relationship()
    cluster: Mapped[ClusterRow] = relationship()


class CompanyPeerRow(_Base):
    __tablename__ = "company_peers"

    ticker: Mapped[str] = mapped_column(ForeignKey("companies.ticker"), primary_key=True)
    peer_ticker: Mapped[str] = mapped_column(String, primary_key=True)
    extraction_level: Mapped[str]  # "A" | "B" | "C"


class MetadataRepository:
    """Relational metadata store (companies, archetypes, clusters, joins).

    One instance per database file. ``__init__`` creates tables if absent,
    so the repository can be used immediately after construction.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (settings.data_dir / "metadata.sqlite")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.db_path}", future=True)
        _Base.metadata.create_all(self.engine)

    # ------------------------------------------------------------------
    # Companies
    # ------------------------------------------------------------------
    def add_company(
        self,
        ticker: str,
        name: str,
        profile: str,
        currency: str,
        exchange: str,
        isin: str | None = None,
    ) -> None:
        normalised = normalise_ticker(ticker)
        try:
            with Session(self.engine) as session, session.begin():
                session.merge(
                    CompanyRow(
                        ticker=normalised,
                        name=name,
                        profile=profile,
                        currency=currency,
                        exchange=exchange,
                        isin=isin,
                    )
                )
        except Exception as e:
            raise StorageError(f"Failed to add company {normalised}: {e}") from e

    def get_company(self, ticker: str) -> CompanyRow | None:
        with Session(self.engine) as session:
            return session.get(CompanyRow, normalise_ticker(ticker))

    def list_companies(self) -> list[CompanyRow]:
        with Session(self.engine) as session:
            return list(session.scalars(select(CompanyRow).order_by(CompanyRow.ticker)))

    # ------------------------------------------------------------------
    # Archetypes
    # ------------------------------------------------------------------
    def add_archetype(self, code: str, name: str, description: str | None = None) -> None:
        with Session(self.engine) as session, session.begin():
            session.merge(ArchetypeRow(code=code, name=name, description=description))

    def get_archetype(self, code: str) -> ArchetypeRow | None:
        with Session(self.engine) as session:
            return session.get(ArchetypeRow, code)

    # ------------------------------------------------------------------
    # Clusters & joins
    # ------------------------------------------------------------------
    def add_cluster(self, cluster_id: str, name: str, description: str | None = None) -> None:
        with Session(self.engine) as session, session.begin():
            session.merge(ClusterRow(cluster_id=cluster_id, name=name, description=description))

    def link_company_to_cluster(self, ticker: str, cluster_id: str) -> None:
        normalised = normalise_ticker(ticker)
        with Session(self.engine) as session, session.begin():
            if session.get(CompanyRow, normalised) is None:
                raise NotFoundError(f"Unknown company {normalised!r}")
            if session.get(ClusterRow, cluster_id) is None:
                raise NotFoundError(f"Unknown cluster {cluster_id!r}")
            session.merge(CompanyClusterRow(ticker=normalised, cluster_id=cluster_id))

    def list_companies_in_cluster(self, cluster_id: str) -> list[str]:
        with Session(self.engine) as session:
            stmt = (
                select(CompanyClusterRow.ticker)
                .where(CompanyClusterRow.cluster_id == cluster_id)
                .order_by(CompanyClusterRow.ticker)
            )
            return list(session.scalars(stmt))

    # ------------------------------------------------------------------
    # Peers
    # ------------------------------------------------------------------
    def add_peer(self, ticker: str, peer_ticker: str, extraction_level: str) -> None:
        normalised = normalise_ticker(ticker)
        normalised_peer = normalise_ticker(peer_ticker)
        with Session(self.engine) as session, session.begin():
            if session.get(CompanyRow, normalised) is None:
                raise NotFoundError(f"Unknown company {normalised!r}")
            session.merge(
                CompanyPeerRow(
                    ticker=normalised,
                    peer_ticker=normalised_peer,
                    extraction_level=extraction_level,
                )
            )

    def list_peers(self, ticker: str) -> list[CompanyPeerRow]:
        with Session(self.engine) as session:
            stmt = (
                select(CompanyPeerRow)
                .where(CompanyPeerRow.ticker == normalise_ticker(ticker))
                .order_by(CompanyPeerRow.peer_ticker)
            )
            return list(session.scalars(stmt))
