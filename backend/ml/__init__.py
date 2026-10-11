"""
NEXA ML Intent Classification Package.
Provides local fast-path intent classification with confidence and margin gating.
"""

from .normalizer import normalize_text
from .classifier import (
    CONFIDENCE_THRESHOLD,
    MARGIN_THRESHOLD,
    create_vectorizers,
    create_classifier,
    build_features,
    predict_intent_details,
    predict_intent,
)

__all__ = [
    "normalize_text",
    "CONFIDENCE_THRESHOLD",
    "MARGIN_THRESHOLD",
    "create_vectorizers",
    "create_classifier",
    "build_features",
    "predict_intent_details",
    "predict_intent",
]
