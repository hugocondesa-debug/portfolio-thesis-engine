"""Phase 2 Sprint 3 — static reference data (Damodaran tables).

The :class:`DamodaranReference` loader exposes the YAML tables checked
in under ``data/reference/damodaran/`` as typed accessors. Tables are
manually refreshed quarterly (vintage stamped in each file).
"""

from portfolio_thesis_engine.reference.damodaran import DamodaranReference

__all__ = ["DamodaranReference"]
