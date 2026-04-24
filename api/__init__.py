"""PTE Backend Service Layer.

FastAPI service exposing PTE artefacts via HTTP. Reads filesystem
(`current` symlinks for latest artefact resolution) and SQLite
directly. **Does not import PTE internal modules** at startup — the
only PTE-internal touch is lazy-loaded Pydantic schemas inside the
yaml-upload validator (:mod:`api.services.yaml_manager`), kept narrow
so a PTE refactor cannot break API service boot.

Sprint 0 — additive only; the PTE Python codebase under
``src/portfolio_thesis_engine/`` is unchanged.
"""

__version__ = "0.10.0"
