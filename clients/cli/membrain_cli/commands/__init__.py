"""Shared conversion and selection guards for command handlers."""
from ..types import ClientError


def data(value):
    """Convert generated model value to displayable wire data."""
    return value.to_dict() if hasattr(value, 'to_dict') else value


def required(value, label):
    """Require selected value; label names the missing concept/session/item."""
    if value is None:
        raise ClientError(f'Choose {label} first.')
    return value
