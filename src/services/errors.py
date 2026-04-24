class FeatureLockedError(RuntimeError):
    """Raised when a commercial/native-only feature is unavailable."""

    def __init__(self, feature_name, reason=""):
        self.feature_name = str(feature_name or "Feature")
        self.reason = str(reason or "").strip()
        message = self.reason or f"{self.feature_name} is not unlocked."
        super().__init__(message)
