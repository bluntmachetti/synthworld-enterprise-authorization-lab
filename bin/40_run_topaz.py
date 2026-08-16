#!/usr/bin/env python3
"""
40_run_topaz.py — load the projected world into a running Topaz and collect real decisions.

ZONE RULES
  reads  : 03-topaz-input/**  (produced by bin/30_project_topaz.py)
           infra/**           (compose project, for the policy-reload restart only)
  writes : 04-topaz-results/**
  It never reads 06-evaluator/ or any truth artifact.

STEPS
  1. assert Topaz is up on both gateways (bring it up with bin/topaz_up.sh first)
  2. ensure the container has the policy from 03-topaz-input/policy (restart if stale) and
     assert it COMPILED (non-empty `ast` in GET /api/v2/policies)
  3. POST the manifest, then load every object and every relation over REST, per record
     (the CLI importer silently drops relations in 0.33.16 — topaz-reference.md §12.4)
  4. VERIFY THE LOAD: read back every object and relation, compare per-type / per-tuple-shape
     counts against what stage 30 emitted, and fail loudly on any mismatch. Then run the
     structural /api/v3/directory/check smoke cases.
  5. one POST /api/v2/authz/is per evaluation cell, all four decisions
  6/7/8. write raw jsonl, normalized decisions, run report

HTTP is stdlib only (http.client over a small thread pool, one persistent connection each).
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
IN = ROOT / "03-topaz-input"
OUTDIR = ROOT / "04-topaz-results"
INFRA = ROOT / "infra"

DS_HOST = os.environ.get("TOPAZ_DS_HOST", "127.0.0.1")
DS_PORT = int(os.environ.get("TOPAZ_DS_PORT", "9393"))
AZ_HOST = os.environ.get("TOPAZ_AUTHZ_HOST", "127.0.0.1")
AZ_PORT = int(os.environ.get("TOPAZ_AUTHZ_PORT", "8383"))

COMPOSE_PROJECT = os.environ.get("TOPAZ_PROJECT", "britannia-phase2")
POLICY_PACKAGE = "britannia.authz"
JSON_HDR = {"Content-Type": "application/json", "Accept": "application/json"}


# ---------------------------------------------------------------------------- http
class Conn:
    """One persistent http.client connection, retried on a dropped keep-alive."""

    def __init__(self, host, port, timeout=60):
        self.host, self.port, self.timeout = host, port, timeout
        self._c = None

    def _connect(self):
        self._c = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)

    def request(self, method, path, body=None, headers=None):
        payload = None if body is None else json.dumps(body).encode()
        hdrs = dict(headers or JSON_HDR)
        for attempt in (0, 1):
            try:
                if self._c is None:
                    self._connect()
                self._c.request(method, path, body=payload, headers=hdrs)
                resp = self._c.getresponse()
                data = resp.read()
                return resp.status, data
            except (http.client.HTTPException, OSError, ConnectionError):
                try:
                    if self._c:
                        self._c.close()
                except Exception:
                    pass
                self._c = None
                if attempt == 1:
                    raise
        raise RuntimeError("unreachable")

    def json(self, method, path, body=None, headers=None):
        status, data = self.request(method, path, body, headers)
        try:
            parsed = json.loads(data) if data else {}
        except json.JSONDecodeError:
            parsed = {"_raw": data.decode("utf-8", "replace")}
        return status, parsed

    def close(self):
        if self._c:
            try:
                self._c.close()
            except Exception:
                pass
            self._c = None


class Pool:
    """Thread-local Conn factory."""

    def __init__(self, host, port, timeout=60):
        self.host, self.port, self.timeout = host, port, timeout
        self._local = threading.local()
        self._all = []
        self._lock = threading.Lock()

    def get(self) -> Conn:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = Conn(self.host, self.port, self.timeout)
            self._local.conn = c
            with self._lock:
                self._all.append(c)
        return c

    def close(self):
        with self._lock:
            for c in self._all:
                c.close()
            self._all.clear()


def die(msg):
    print(f"\n!!! FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


# ---------------------------------------------------------------------------- steps
def step1_assert_up(ds: Pool, az: Pool):
    print("== 1. assert Topaz is up ==")
    for label, pool, path in (("directory 9393", ds, "/api/v3/directory/manifest"),
                              ("authorizer 8383", az, "/api/v2/policies")):
        try:
            status, _ = pool.get().request("GET", path)
        except OSError as exc:
            die(f"{label} unreachable ({exc}). Run bin/topaz_up.sh first.")
        if status != 200:
            die(f"{label} returned HTTP {status} for {path}. Run bin/topaz_up.sh first.")
        print(f"   {label:<16} 200 {path}")
    status, info = az.get().json("GET", "/api/v2/info")
    print(f"   version          {info.get('version')} commit {info.get('commit')}")
    return info


def wait_ready(ds: Pool, az: Pool, attempts=60):
    for _ in range(attempts):
        try:
            d, _ = ds.get().request("GET", "/api/v3/directory/manifest")
            a, _ = az.get().request("GET", "/api/v2/policies")
            if d == 200 and a == 200:
                return True
        except OSError:
            pass
        time.sleep(1)
    return False


def step2_policy(ds: Pool, az: Pool):
    print("== 2. policy bundle ==")
    want = (IN / "policy" / "britannia" / "authz.rego").read_text(encoding="utf-8")
    live_path = INFRA / "policy" / "britannia" / "authz.rego"
    if live_path.read_text(encoding="utf-8") != want:
        die(f"{live_path} differs from {IN}/policy/britannia/authz.rego — re-run stage 30.")

    def loaded():
        status, body = az.get().json("GET", "/api/v2/policies")
        if status != 200:
            return None
        for p in body.get("result", []):
            if p.get("package_path") == f"data.{POLICY_PACKAGE}":
                return p
        return None

    pol = loaded()
    if pol is None or pol.get("raw") != want:
        # local_bundles without watch: a .rego edit needs a container restart (§7.6)
        print("   loaded policy is absent/stale -> restarting container to reload the bundle")
        subprocess.run(
            ["docker", "compose", "-p", COMPOSE_PROJECT,
             "-f", str(INFRA / "docker-compose.yaml"), "restart", "topaz"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        ds.close()
        az.close()
        if not wait_ready(ds, az):
            die("gateways did not come back after restart")
        pol = loaded()

    if pol is None:
        die(f"policy {POLICY_PACKAGE} is not loaded (GET /api/v2/policies)")
    if pol.get("raw") != want:
        die(f"loaded policy for {POLICY_PACKAGE} does not match 03-topaz-input")
    if not pol.get("ast"):
        die(f"policy {POLICY_PACKAGE} has an empty `ast` -> it did NOT compile; "
            "every decision would silently fall to its default")
    print(f"   {pol['id']}")
    print(f"   package_path {pol['package_path']}  ast_bytes {len(pol['ast'])}  COMPILED")


def step3_load(ds: Pool, workers: int):
    print("== 3. load model + directory ==")
    manifest = (IN / "model" / "manifest.yaml").read_bytes()
    # The manifest body is raw YAML, not JSON-wrapped (topaz-reference.md §5.2), so it goes
    # over its own short-lived connection rather than through the JSON helper.
    c = http.client.HTTPConnection(DS_HOST, DS_PORT, timeout=60)
    c.request("POST", "/api/v3/directory/manifest", body=manifest,
              headers={"Content-Type": "application/yaml"})
    r = c.getresponse()
    body = r.read()
    c.close()
    if r.status != 200:
        die(f"manifest POST -> HTTP {r.status}: {body[:400]!r}")
    print(f"   manifest POST 200 ({len(manifest)} bytes)")

    timings = {}
    counts = {}
    for name, fname, path in (("objects", "objects.jsonl", "/api/v3/directory/object"),
                              ("relations", "relations.jsonl", "/api/v3/directory/relation")):
        records = list(read_jsonl(IN / "directory" / fname))
        t0 = time.monotonic()
        errors = []
        done = [0]
        lock = threading.Lock()

        def post(rec, _path=path, _errors=errors):
            status, resp = ds.get().json("POST", _path, rec)
            with lock:
                done[0] += 1
                if done[0] % 1000 == 0:
                    print(f"   {name}: {done[0]}/{len(records)}", flush=True)
            if status != 200:
                _errors.append({"status": status, "record": rec, "response": resp})

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(post, records))
        dt = time.monotonic() - t0
        timings[name] = round(dt, 3)
        counts[name] = len(records)
        if errors:
            for e in errors[:5]:
                print(f"   ERROR {e['status']}: {json.dumps(e['record'])[:200]} -> "
                      f"{json.dumps(e['response'])[:200]}", file=sys.stderr)
            die(f"{len(errors)} {name} failed to write")
        print(f"   {name}: {len(records)} written, 0 errors, {dt:.1f}s "
              f"({len(records)/max(dt, 1e-9):.0f}/s)")
    return counts, timings


# Verified empirically on 0.33.16: the v3 list endpoints return HTTP 500
# ("E00000 an unknown error has occurred") for any page.size > 100. 100 is also the server
# default. Do not raise this.
MAX_PAGE_SIZE = 100


def list_all(ds: Pool, path: str, params: dict, page_size=MAX_PAGE_SIZE):
    out = []
    token = ""
    while True:
        query = dict(params)
        query["page.size"] = page_size
        if token:
            query["page.token"] = token
        url = path + "?" + urlencode(query)
        status, body = ds.get().json("GET", url)
        if status != 200:
            die(f"GET {url} -> HTTP {status}: {json.dumps(body)[:300]}")
        out.extend(body.get("results", []))
        token = (body.get("page") or {}).get("next_token") or ""
        if not token:
            return out


def step4_verify(ds: Pool, summary: dict):
    print("== 4. verify the load ==")
    # ---- objects, per type
    live_objects = list_all(ds, "/api/v3/directory/objects", {})
    live_obj_counts = Counter(o["type"] for o in live_objects)
    want_obj_counts = Counter(summary["object_counts"])
    print(f"   objects read back: {len(live_objects)} (expected {summary['object_total']})")
    bad = []
    for t in sorted(set(live_obj_counts) | set(want_obj_counts)):
        got, exp = live_obj_counts.get(t, 0), want_obj_counts.get(t, 0)
        flag = "ok " if got == exp else "MISMATCH"
        print(f"      {t:<14} expected {exp:>5}  got {got:>5}  {flag}")
        if got != exp:
            bad.append(f"object type {t}: expected {exp}, got {got}")

    # ---- relations, per tuple shape
    live_relations = list_all(ds, "/api/v3/directory/relations", {})
    live_rel_counts = Counter(
        (r["object_type"], r["relation"], r["subject_type"], r.get("subject_relation") or "")
        for r in live_relations
    )
    want_rel_counts = Counter(
        {(x["object_type"], x["relation"], x["subject_type"], x["subject_relation"]): x["count"]
         for x in summary["relation_counts"]}
    )
    print(f"   relations read back: {len(live_relations)} (expected {summary['relation_total']})")
    for key in sorted(set(live_rel_counts) | set(want_rel_counts)):
        got, exp = live_rel_counts.get(key, 0), want_rel_counts.get(key, 0)
        label = f"{key[0]}.{key[1]} <- {key[2]}" + (f"#{key[3]}" if key[3] else "")
        flag = "ok " if got == exp else "MISMATCH"
        print(f"      {label:<46} expected {exp:>5}  got {got:>5}  {flag}")
        if got != exp:
            bad.append(f"relation {label}: expected {exp}, got {got}")

    if len(live_objects) != summary["object_total"]:
        bad.append(f"object total: expected {summary['object_total']}, got {len(live_objects)}")
    if len(live_relations) != summary["relation_total"]:
        bad.append(
            f"relation total: expected {summary['relation_total']}, got {len(live_relations)}")
    if bad:
        for b in bad:
            print(f"   !! {b}", file=sys.stderr)
        die(f"directory load verification failed ({len(bad)} mismatches)")
    print("   LOAD VERIFIED: every object type and every relation shape matches stage 30.")

    # ---- smoke checks
    print("   smoke: POST /api/v3/directory/check")
    smoke_results = []
    failures = 0
    for case in summary["smoke_checks"]:
        status, body = ds.get().json("POST", "/api/v3/directory/check", case["body"])
        got = bool(body.get("check")) if status == 200 else None
        ok = (status == 200 and got == case["expect"])
        failures += 0 if ok else 1
        smoke_results.append({**case, "http_status": status, "got": got, "ok": ok,
                              "context": body.get("context")})
        print(f"      [{'PASS' if ok else 'FAIL'}] expected {case['expect']!s:<5} "
              f"got {got!s:<5}  {case['name']}")
    if failures:
        die(f"{failures} directory smoke check(s) failed — model or load is wrong")
    return {"objects_read_back": len(live_objects), "relations_read_back": len(live_relations),
            "object_counts": dict(sorted(live_obj_counts.items())),
            "smoke_checks": smoke_results}


def step5_decisions(az: Pool, requests: list, workers: int):
    print(f"== 5. decisions: {len(requests)} x POST /api/v2/authz/is ==")
    results = [None] * len(requests)
    done = [0]
    lock = threading.Lock()
    t0 = time.monotonic()

    def call(idx):
        req = requests[idx]
        status, body = az.get().json("POST", "/api/v2/authz/is", req["body"])
        results[idx] = {
            "cell_id": req["cell_id"],
            "access_atom_id": req.get("access_atom_id"),
            "http_status": status,
            "request": req["body"],
            "response": body,
        }
        with lock:
            done[0] += 1
            if done[0] % 500 == 0:
                print(f"   {done[0]}/{len(requests)}", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(call, range(len(requests))))
    dt = time.monotonic() - t0
    print(f"   {len(requests)} decisions in {dt:.1f}s ({len(requests)/max(dt, 1e-9):.0f}/s)")
    return results, round(dt, 3)


DECISIONS = [
    "birthright",
    "intended",
    "effective",
    "rbac_final",
    "final",
    "abac_deny",
    "cross_tenant",
]


def normalize(results):
    normalized = {}
    errors = []
    for row in results:
        if row["http_status"] != 200:
            errors.append(row)
            continue
        got = {d["decision"]: bool(d.get("is", False))
               for d in (row["response"].get("decisions") or [])}
        missing = [d for d in DECISIONS if d not in got]
        if missing:
            errors.append({**row, "_missing_decisions": missing})
            continue
        entry = {d: got[d] for d in DECISIONS}
        # Mechanism outcome for the ABAC family, as the scorer expects it.
        entry["abac"] = "deny" if got["abac_deny"] else "allow"
        normalized[row["cell_id"]] = entry
    return normalized, errors


def read_all_relations(ds: Pool, object_type: str, relation: str) -> dict[str, str]:
    """Page the whole relation set out of the directory.

    page.size is capped server-side; 1000 silently returns zero rows, so page in 100s and
    follow next_token. Returns {object_id: subject_id}.
    """
    out: dict[str, str] = {}
    token = ""
    for _ in range(200):  # hard stop; 597 rows fit in 6 pages
        query = {"object_type": object_type, "relation": relation, "page.size": "100"}
        if token:
            query["page.token"] = token
        status, body = ds.get().json(
            "GET", f"/api/v3/directory/relations?{urlencode(query)}"
        )
        if status != 200:
            die(f"relation listing failed: HTTP {status} {body}")
        rows = body.get("results", [])
        for r in rows:
            out[r["object_id"]] = r["subject_id"]
        token = (body.get("page") or {}).get("next_token") or ""
        if not token or not rows:
            break
    return out


def step5b_role_holders(ds: Pool, workers: int):
    """Ask Topaz which subjects hold each role.

    `authorized_role_sets` is a scored dimension and is genuinely derivable from the
    directory, so it is derived rather than left empty. The graph endpoint returns the
    CLOSURE-expanded holder set (group membership, group nesting and role hierarchy all
    applied by Topaz), which is exactly what the truth's per-subject role set means.

    GET /api/v3/directory/graph/role/holder/subject?object_id=<role_id>
    """
    queries = list(read_jsonl(IN / "requests" / "role-holder-queries.jsonl"))
    print(f"== 5b. role holders: {len(queries)} x GET /api/v3/directory/graph ==")
    holders: dict[str, list[str]] = {}
    errors = []

    def one(q):
        rid = q["role_id"]
        path = f"/api/v3/directory/graph/role/holder/subject?{urlencode({'object_id': rid})}"
        status, body = ds.get().json("GET", path)
        if status != 200:
            return rid, None, {"role_id": rid, "http_status": status, "body": body}
        subs = sorted(
            r["object_id"] for r in body.get("results", []) if r.get("object_type") == "subject"
        )
        return rid, subs, None

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for rid, subs, err in ex.map(one, queries):
            if err:
                errors.append(err)
            else:
                holders[rid] = subs
    elapsed = time.monotonic() - t0
    if errors:
        die(f"{len(errors)} role-holder queries failed, first: {errors[0]}")

    # invert role -> subjects into subject -> roles
    by_subject: dict[str, set[str]] = defaultdict(set)
    for rid in sorted(holders):
        for sid in holders[rid]:
            by_subject[sid].add(rid)

    # An account holds no role of its own; its authority is that of the principal the
    # directory believes it belongs to. The policy already applies that rule when deciding
    # `effective`, so the reported role set must apply it too or the two would contradict
    # each other. The bindings are read back OUT OF TOPAZ (paginated), not taken from the
    # projector's own input.
    bindings = read_all_relations(ds, "subject", "observed_principal")
    for account_id, principal_id in sorted(bindings.items()):
        inherited = by_subject.get(principal_id)
        if inherited:
            by_subject[account_id] |= inherited
    print(f"   applied {len(bindings)} account -> observed-principal bindings")

    role_sets = {sid: sorted(rs) for sid, rs in sorted(by_subject.items())}
    print(f"   {len(holders)} roles -> {len(role_sets)} subjects with >=1 role in {elapsed:.1f}s")
    return role_sets, elapsed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    summary = json.loads((IN / "PROJECTION-SUMMARY.json").read_text())
    requests = list(read_jsonl(IN / "requests" / "authz-requests.jsonl"))

    ds = Pool(DS_HOST, DS_PORT)
    az = Pool(AZ_HOST, AZ_PORT)
    wall0 = time.monotonic()

    info = step1_assert_up(ds, az)
    step2_policy(ds, az)
    load_counts, load_timings = step3_load(ds, args.workers)
    verification = step4_verify(ds, summary)
    results, decide_seconds = step5_decisions(az, requests, args.workers)

    role_sets, role_seconds = step5b_role_holders(ds, args.workers)
    normalized, errors = normalize(results)

    print("== 6/7/8. write results ==")
    (OUTDIR / "raw").mkdir(parents=True, exist_ok=True)
    (OUTDIR / "normalized").mkdir(parents=True, exist_ok=True)
    with (OUTDIR / "raw" / "decisions.jsonl").open("w", encoding="utf-8") as fh:
        for row in sorted(results, key=lambda r: r["cell_id"]):
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    (OUTDIR / "normalized" / "role-sets.json").write_text(
        json.dumps(role_sets, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUTDIR / "normalized" / "decisions.json").write_text(
        json.dumps({k: normalized[k] for k in sorted(normalized)}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    dist = {d: Counter(v[d] for v in normalized.values()) for d in DECISIONS}
    distribution = {
        d: {"allow": dist[d][True], "deny": dist[d][False]} for d in DECISIONS
    }
    # cross-tab: how final differs from effective, and why it can
    downgrades = sum(1 for v in normalized.values() if v["effective"] and not v["final"])
    rbac_downgrades = sum(
        1 for v in normalized.values() if v["effective"] and not v["rbac_final"]
    )

    # Independent cross-check: the projector evaluated the published ABAC deny rules in
    # Python; Rego evaluated the same published rules against the same published facts.
    # Agreement is evidence the guard is genuinely being evaluated rather than echoed.
    # Disagreement is a finding and is reported, not smoothed over.
    projector_deny = {
        r["cell_id"]: bool(r.get("projector_abac_deny")) for r in requests
    }
    abac_disagreements = sorted(
        cid
        for cid, v in normalized.items()
        if projector_deny.get(cid) is not None and projector_deny[cid] != v["abac_deny"]
    )
    # The published cross-tenant deny rule can only be expressed by cell scope (the ABAC
    # contract has no negated predicate). Rego derives the tenant comparison independently,
    # so compare that derivation against the rule's published scope.
    scoped_cross_tenant = {
        r["cell_id"]
        for r in requests
        if any(
            rule["rule_id"] == "abac-deny-cross-tenant"
            for rule in r["body"]["resource_context"].get("abac_rules_in_scope", [])
        )
    }
    derived_cross_tenant = {c for c, v in normalized.items() if v["cross_tenant"]}
    abac_cross_check = {
        "projector_vs_rego_abac_deny_disagreements": len(abac_disagreements),
        "projector_vs_rego_disagreeing_cells": abac_disagreements[:20],
        "cells_in_published_cross_tenant_rule_scope": len(scoped_cross_tenant),
        "cells_where_rego_derived_tenants_differ": len(derived_cross_tenant),
        "scope_and_derivation_agree": scoped_cross_tenant == derived_cross_tenant,
        "in_scope_but_tenants_match": len(scoped_cross_tenant - derived_cross_tenant),
        "tenants_differ_but_not_in_scope": len(derived_cross_tenant - scoped_cross_tenant),
    }

    report = {
        "topaz": {
            "version": info.get("version"), "commit": info.get("commit"),
            "date": info.get("date"), "os": info.get("os"), "arch": info.get("arch"),
            "authorizer": f"http://{AZ_HOST}:{AZ_PORT}",
            "directory": f"http://{DS_HOST}:{DS_PORT}",
        },
        "policy": {"path": POLICY_PACKAGE, "decisions": DECISIONS},
        "counts": {
            "objects_written": load_counts["objects"],
            "relations_written": load_counts["relations"],
            "objects_read_back": verification["objects_read_back"],
            "relations_read_back": verification["relations_read_back"],
            "cells_requested": len(requests),
            "cells_normalized": len(normalized),
            "subjects_with_roles": len(role_sets),
            "http_errors": len(errors),
        },
        "timings_seconds": {
            "load_objects": load_timings["objects"],
            "load_relations": load_timings["relations"],
            "decisions": decide_seconds,
            "wall_total": round(time.monotonic() - wall0, 3),
        },
        "decision_distribution": distribution,
        "effective_allow_but_final_deny": downgrades,
        "effective_allow_but_rbac_final_deny": rbac_downgrades,
        "abac_cross_check": abac_cross_check,
        "abac_guard_from_stage30": summary["abac_guard"],
        "smoke_checks": verification["smoke_checks"],
        "errors": errors[:20],
    }
    (OUTDIR / "run-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"   raw        : {OUTDIR / 'raw' / 'decisions.jsonl'}  ({len(results)} lines)")
    print(f"   normalized : {OUTDIR / 'normalized' / 'decisions.json'}  ({len(normalized)} cells)")
    print(f"   report     : {OUTDIR / 'run-report.json'}")
    print("\n   decision distribution")
    for d in DECISIONS:
        print(f"      {d:<11} allow {distribution[d]['allow']:>5}   "
              f"deny {distribution[d]['deny']:>5}")
    ds.close()
    az.close()
    if errors:
        die(f"{len(errors)} cells did not return all four decisions")
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
