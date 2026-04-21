"""Ficha — aggregate view of a company across modules.

:class:`FichaComposer` builds a :class:`Ficha` from the canonical state
+ valuation snapshot; :class:`FichaLoader` wraps repository access for
UI / CLI callers that want the latest of everything in one step.
"""

from portfolio_thesis_engine.ficha.composer import FichaComposer
from portfolio_thesis_engine.ficha.loader import FichaBundle, FichaLoader

__all__ = [
    "FichaBundle",
    "FichaComposer",
    "FichaLoader",
]
