from __future__ import annotations

from typing import Protocol

from kabu_per_bot.committee.types import CommitteeContext, LensEvaluation


class CommitteeLens(Protocol):
    key: str
    title: str

    def evaluate(self, context: CommitteeContext) -> LensEvaluation:
        """Evaluate one perspective and return normalized output."""
