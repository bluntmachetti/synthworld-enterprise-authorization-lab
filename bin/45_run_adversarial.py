#!/usr/bin/env python3
"""Run the public adversarial attempts through Topaz's authorization API."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "03-topaz-input/adversarial"
POLICY = ROOT / "03-topaz-input/policy/adversarial/authz.rego"
OUTPUT = ROOT / "04-topaz-results/adversarial"
HOST = os.environ.get("TOPAZ_AUTHZ_HOST", "127.0.0.1")
PORT = int(os.environ.get("TOPAZ_AUTHZ_PORT", "8383"))


def canonical_json(document: object) -> bytes:
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    connection = http.client.HTTPConnection(HOST, PORT, timeout=60)
    payload = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    return response.status, json.loads(raw) if raw else {}


def load_requests() -> list[dict]:
    rows = []
    with (INPUT / "authz-requests.jsonl").open("r", encoding="utf-8") as source:
        for line in source:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def verify_policy() -> dict:
    status, payload = request("GET", "/api/v2/policies")
    if status != 200:
        raise SystemExit(f"Topaz policy endpoint returned HTTP {status}")
    expected = POLICY.read_text("utf-8")
    policy = next(
        (
            item
            for item in payload.get("result", [])
            if item.get("package_path") == "data.adversarial.authz"
        ),
        None,
    )
    if policy is None or policy.get("raw") != expected or not policy.get("ast"):
        raise SystemExit("adversarial.authz is absent, stale, or did not compile")
    return policy


def main() -> int:
    policy = verify_policy()
    info_status, info = request("GET", "/api/v2/info")
    if info_status != 200:
        raise SystemExit(f"Topaz info endpoint returned HTTP {info_status}")
    raw_rows = []
    normalized = {}
    for row in load_requests():
        status, response = request("POST", "/api/v2/authz/is", row["body"])
        decisions = {
            item["decision"]: bool(item.get("is", False)) for item in response.get("decisions", [])
        }
        if status != 200 or "allow" not in decisions:
            raise SystemExit(
                f"Topaz failed adversarial attempt {row['attempt_id']}: HTTP {status} {response}"
            )
        raw_rows.append(
            {
                "attempt_id": row["attempt_id"],
                "request": row["body"],
                "http_status": status,
                "response": response,
            }
        )
        normalized[row["attempt_id"]] = {
            "allow": decisions["allow"],
            "resolved_principal_id": row["resolved_principal_id"],
        }

    OUTPUT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT / "raw-decisions.jsonl").open("wb") as output:
        for row in sorted(raw_rows, key=lambda item: item["attempt_id"]):
            output.write(canonical_json(row))
    (OUTPUT / "decisions.json").write_bytes(canonical_json(normalized))
    report = {
        "schema_version": "synthworld-enterprise-authorization-topaz-run/1",
        "attempts_requested": len(raw_rows),
        "attempts_normalized": len(normalized),
        "policy_package": "adversarial.authz",
        "policy_id": policy["id"],
        "policy_sha256": hashlib.sha256(POLICY.read_bytes()).hexdigest(),
        "topaz": {
            "version": info.get("version"),
            "commit": info.get("commit"),
            "os": info.get("os"),
            "arch": info.get("arch"),
        },
    }
    (OUTPUT / "run-report.json").write_bytes(canonical_json(report))
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
