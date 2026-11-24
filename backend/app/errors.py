"""Shared HTTP error for member C's web application."""
class AppError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


STATUS = {
    "INVALID_PARAMETER": 400, "INVALID_FILTER": 400, "EMPTY_PREFERENCES": 400,
    "NOT_FOUND": 404, "METHOD_NOT_ALLOWED": 405, "BATCH_MISMATCH": 409,
    "PRICE_POLICY_NOT_READY": 409, "STATISTIC_NOT_AVAILABLE": 409,
    "UNSUPPORTED_MEDIA_TYPE": 415, "DATASET_NOT_READY": 503, "DATASET_INVALID": 503,
    "DEPENDENCY_UNAVAILABLE": 503, "RECOMMENDER_UNAVAILABLE": 503, "INTERNAL_ERROR": 500,
}
