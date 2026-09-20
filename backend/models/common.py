from __future__ import annotations
from enum import Enum

class PlanStatus(str, Enum):
    RAW = "RAW"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    ERROR = "ERROR"

class QualityStatus(str, Enum):
    OK = "OK"
    ESTIMATED = "ESTIMATED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
