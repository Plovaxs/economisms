"""OpenAPI 3.1 structural schemas from the existing typed runner allowlist.

JSON Schema validates wire types; original decoders and resource admission
remain authoritative for financial semantics and cross-field constraints.
"""

from __future__ import annotations

import types
from dataclasses import fields, is_dataclass
from datetime import date
from fractions import Fraction
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from prometheus.core.money import Money
from prometheus.jobs.store import STATUSES
from prometheus.orchestration.recipes import RUNNERS, _config_class

API_VERSION = "1.0.0"


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _schema(annotation: Any) -> dict[str, Any]:
    origin, arguments = get_origin(annotation), get_args(annotation)
    if annotation is type(None):
        return {"type": "null"}
    if annotation is date:
        return {"type": "string", "format": "date"}
    if annotation is Fraction:
        return {
            "anyOf": [
                _object(
                    {
                        "numerator": {"type": "integer"},
                        "denominator": {"type": "integer", "minimum": 1},
                    }
                ),
                {"type": "number"},
            ]
        }
    if annotation is Money:
        return _object(
            {
                "minor_units": {"type": "integer"},
                "currency": {"type": "string", "minLength": 1, "maxLength": 128},
            }
        )
    if annotation in (str, int, float, bool):
        return {
            "type": {str: "string", int: "integer", float: "number", bool: "boolean"}[annotation]
        }
    if origin is Literal:
        return {"enum": list(arguments)}
    if origin in (Union, types.UnionType):
        return {"anyOf": [_schema(value) for value in arguments]}
    if origin is tuple and arguments[-1] is Ellipsis:
        return {"type": "array", "items": _schema(arguments[0])}
    if is_dataclass(annotation) and isinstance(annotation, type):
        hints = get_type_hints(annotation)
        return _object({field.name: _schema(hints[field.name]) for field in fields(annotation)})
    raise ValueError(f"unsupported API schema type: {annotation}")


def submission_schema() -> dict[str, Any]:
    variants = []
    for kind in RUNNERS:
        variant = _object(
            {
                "kind": {"const": kind},
                "config": _schema(_config_class(kind)),
                "timeout_seconds": {"type": "number", "minimum": 0.05},
            }
        )
        variant["required"] = ["kind", "config"]
        variants.append(variant)
    return {"oneOf": variants}


def job_schema() -> dict[str, Any]:
    nullable_digest = {"type": ["string", "null"], "pattern": "^[a-f0-9]{64}$"}
    return _object(
        {
            "job_id": {"type": "string", "format": "uuid"},
            "trace_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
            "kind": {"enum": list(RUNNERS)},
            "status": {"enum": sorted(STATUSES)},
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"},
            "recipe_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            "attempts": {"type": "integer", "minimum": 0},
            "cancel_requested": {"type": "boolean"},
            "timeout_seconds": {"type": "number"},
            "resource_estimate": {"type": "object", "additionalProperties": {"type": "integer"}},
            "artifact_sha256": nullable_digest,
            "result_hash": nullable_digest,
            "error_code": {"type": ["string", "null"]},
            "diagnostic_id": {"type": ["string", "null"]},
        }
    )


def openapi_document() -> dict[str, Any]:
    def response(schema: dict[str, Any], description: str = "Success") -> dict[str, Any]:
        return {"description": description, "content": {"application/json": {"schema": schema}}}

    def operation(identifier: str, schema: dict[str, Any], code: str = "200") -> dict[str, Any]:
        return {
            "operationId": identifier,
            "responses": {
                code: response(schema),
                "default": response(
                    {"$ref": "#/components/schemas/Error"}, "Structured error; no raw diagnostics"
                ),
            },
        }

    job = {"$ref": "#/components/schemas/Job"}
    status = _object({"status": {"type": "string"}})
    listing = _object(
        {"jobs": {"type": "array", "items": job}, "next_cursor": {"type": ["string", "null"]}}
    )
    paths: dict[str, Any] = {
        "/health/live": {"get": operation("liveness", status)},
        "/health/ready": {"get": operation("readiness", status)},
        "/v1/openapi.json": {"get": operation("openapi", {"type": "object"})},
        "/v1/jobs": {
            "get": operation("listJobs", listing),
            "post": operation("submitJob", job, "202"),
        },
        "/v1/jobs/{job_id}": {"get": operation("getJob", job)},
        "/v1/jobs/{job_id}/cancel": {"post": operation("cancelJob", job)},
        "/v1/jobs/{job_id}/artifact": {"get": operation("getArtifact", {"type": "object"})},
    }
    for path, methods in paths.items():
        for method in methods.values():
            if path.startswith("/health/"):
                method["security"] = []
            if "{job_id}" in path:
                method["parameters"] = [
                    {
                        "in": "path",
                        "name": "job_id",
                        "required": True,
                        "schema": {"type": "string", "format": "uuid"},
                    }
                ]
    paths["/v1/jobs"]["post"]["parameters"] = [
        {
            "in": "header",
            "name": "Idempotency-Key",
            "required": True,
            "schema": {"type": "string", "pattern": "^[A-Za-z0-9._:@-]{1,128}$"},
        }
    ]
    paths["/v1/jobs"]["post"]["requestBody"] = {
        "required": True,
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Submission"}}},
    }
    paths["/v1/jobs"]["get"]["parameters"] = [
        {
            "in": "query",
            "name": "limit",
            "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
        },
        {"in": "query", "name": "cursor", "schema": {"type": "string", "maxLength": 1024}},
    ]
    error = _object(
        {
            "error": _object(
                {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "request_id": {"type": "string"},
                    "diagnostic_id": {"type": "string"},
                    "field": {"type": ["string", "null"]},
                }
            )
        }
    )
    return {
        "openapi": "3.1.1",
        "info": {
            "title": "PROMETHEUS research jobs",
            "version": API_VERSION,
            "description": (
                "Synthetic research only. Full recipes required; wire schema plus typed semantics "
                "resource validation. No live trading, order execution or payment endpoints."
            ),
        },
        "security": [{"ServiceToken": []}],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "ServiceToken": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "opaque service token",
                }
            },
            "schemas": {"Submission": submission_schema(), "Job": job_schema(), "Error": error},
        },
    }
