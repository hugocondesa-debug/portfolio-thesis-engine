"""Route tasks to configured models.

Task types are declared once and mapped at call time to whichever model ID
is currently configured in :mod:`shared.config`. Changing the model used
for every ``ANALYSIS`` task is therefore a settings change, not a code
change.
"""

from __future__ import annotations

from enum import StrEnum

from portfolio_thesis_engine.shared.config import settings


class TaskType(StrEnum):
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    ANALYSIS = "analysis"
    JUDGMENT = "judgment"
    NARRATIVE = "narrative"


def model_for_task(task: TaskType) -> str:
    """Return the model ID currently configured for ``task``."""
    mapping = {
        TaskType.CLASSIFICATION: settings.llm_model_classification,
        TaskType.EXTRACTION: settings.llm_model_analysis,
        TaskType.ANALYSIS: settings.llm_model_analysis,
        TaskType.JUDGMENT: settings.llm_model_judgment,
        TaskType.NARRATIVE: settings.llm_model_analysis,
    }
    return mapping[task]
