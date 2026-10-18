"""Application errors. These are not restaurant facts."""


class FoodCopilotError(Exception):
    """Base error for a controlled failure."""


class FeatureDisabled(FoodCopilotError):
    """An optional backend was requested while its flag is off or its package is missing."""


class DataValidationError(FoodCopilotError):
    """A record or request failed validation."""


class ToolError(FoodCopilotError):
    """A tool rejected its arguments or could not run."""


class ModelConfigError(FoodCopilotError):
    """The model cannot be called because its configuration is missing."""


class ModelCallError(FoodCopilotError):
    """The model request failed. The message must not include secrets."""
