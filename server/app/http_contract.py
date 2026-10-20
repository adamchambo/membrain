"""Stable operation names and documented HTTP error envelopes."""
from typing import Annotated, Any
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    code: str
    detail: str


def disjoint_union(schema: dict) -> None:
    """String/integer and string/array alternatives are mutually exclusive."""
    schema["oneOf"] = schema.pop("anyOf")


class ValidationIssue(BaseModel):
    loc: list[Annotated[str | int, Field(json_schema_extra=disjoint_union)]]
    msg: str
    type: str
    input: Any = Field(default=None, description="The rejected JSON value, when supplied by validation.")
    ctx: dict[str, Any] | None = Field(default=None, description="Optional validator-specific context.")


class ValidationErrorResponse(BaseModel):
    detail: Annotated[list[ValidationIssue] | str, Field(json_schema_extra=disjoint_union)]


def operation_id(route: APIRoute) -> str:
    """Use the endpoint's unique name, independent of its URL layout."""
    return route.name


ERROR_RESPONSES = {
    404: {"model": ErrorResponse, "description": "Requested record not found."},
    409: {"model": ErrorResponse, "description": "Operation conflicts with current state or scope."},
    422: {"model": ValidationErrorResponse, "description": "Request validation failed."},
    503: {"model": ErrorResponse, "description": "Required provider or configuration unavailable."},
}
