"""
Lightweight multi-response consensus for high-risk classifications.
"""

from __future__ import annotations

import logging
import statistics
from collections import Counter
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("consensus_validation")


class ConsensusValidator:
    def validate(self, responses: List[Dict[str, Any]], label_key: str = "label") -> Tuple[Any, float]:
        if not responses:
            raise ValueError("no_responses")
        labels = [r.get(label_key) for r in responses if label_key in r]
        if not labels:
            raise ValueError("no_labels")
        counts = Counter(labels)
        winner, cnt = counts.most_common(1)[0]
        agreement = cnt / len(labels)
        return winner, agreement

    def score_confidence(self, scores: List[float]) -> float:
        if not scores:
            return 0.0
        return float(statistics.median(scores))


__all__ = ["ConsensusValidator"]
