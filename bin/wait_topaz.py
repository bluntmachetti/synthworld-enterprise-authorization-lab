#!/usr/bin/env python3
"""Wait for both Topaz REST gateways without requiring curl in the lab image."""

from __future__ import annotations

import http.client
import os
import time


def ready(host: str, port: int, path: str) -> bool:
    try:
        connection = http.client.HTTPConnection(host, port, timeout=2)
        connection.request("GET", path)
        response = connection.getresponse()
        response.read()
        connection.close()
        return response.status == 200
    except OSError:
        return False


def main() -> int:
    host = os.environ.get("TOPAZ_AUTHZ_HOST", "topaz")
    for attempt in range(90):
        if ready(host, 8383, "/api/v2/policies") and ready(
            host, 9393, "/api/v3/directory/manifest"
        ):
            print(f"Topaz ready after {attempt + 1} probe(s)")
            return 0
        time.sleep(1)
    raise SystemExit("Topaz did not expose both REST gateways within 90 seconds")


if __name__ == "__main__":
    raise SystemExit(main())
