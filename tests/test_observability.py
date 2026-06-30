"""Learner tests for the observability layer."""

import json
import logging

from fastapi.testclient import TestClient

from api.main import app
from api.observability import requests_total


def _json_log_records(caplog):
    """Return structured JSON log payloads captured from the m11.api logger."""
    payloads = []

    for record in caplog.records:
        if record.name != "m11.api":
            continue

        try:
            payloads.append(json.loads(record.getMessage()))
        except json.JSONDecodeError:
            continue

    return payloads


def test_request_id_header_is_set_and_non_empty():
    with TestClient(app) as client:
        response = client.get("/healthz")

    request_id = response.headers.get("x-request-id")

    assert response.status_code == 200
    assert request_id is not None
    assert len(request_id) >= 8


def test_requests_total_counter_increments_for_successful_request():
    labeled_counter = requests_total.labels(path="/healthz", status="200")
    before = labeled_counter._value.get()

    with TestClient(app) as client:
        response = client.get("/healthz")

    after = labeled_counter._value.get()

    assert response.status_code == 200
    assert after == before + 1


def test_structured_log_contains_response_request_id(caplog):
    caplog.set_level(logging.INFO, logger="m11.api")

    with TestClient(app) as client:
        response = client.get("/healthz")

    response_request_id = response.headers.get("x-request-id")
    log_payloads = _json_log_records(caplog)

    matching_logs = [
        payload
        for payload in log_payloads
        if payload.get("path") == "/healthz"
        and payload.get("status") == 200
        and payload.get("request_id") == response_request_id
    ]

    assert response.status_code == 200
    assert response_request_id is not None
    assert matching_logs
    assert isinstance(matching_logs[-1]["latency_ms"], float | int)