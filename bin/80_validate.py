#!/usr/bin/env python3
"""Stage 80 - validation report: artifact counts and integrity checks across
every isolation zone.

Runs last. Reads everything, changes nothing. Exits non-zero if any invariant
fails, so it doubles as the experiment's self-test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent

EVALUATOR_TERMS = [
    "birthright_decision",
    "intended_decision",
    "effective_decision",
    "final_decision",
    "reconciliation",
    "binding_status",
    "lifecycle_status",
    "canonical-binding",
    "directory-rbac-truth",
    "abac-truth",
    "rebac-truth",
    "compiled-access-state",
]


class Report:
    def __init__(self) -> None:
        self.checks: list[dict] = []
        self.counts: dict = {}
        self.failed = 0

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"check": name, "pass": bool(ok), "detail": detail})
        if not ok:
            self.failed += 1
        return ok


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "reports/validation-report.json"))
    args = ap.parse_args()
    r = Report()

    # ---------------------------------------------------------------- zone 1
    topo = REPO / "01-source/topology/britannia_global_bank_topology.yaml"
    cfg = yaml.safe_load((REPO / "01-source/config/experiment.yaml").read_text("utf-8"))
    r.check(
        "source topology digest matches experiment.yaml",
        sha256_file(topo) == cfg["source"]["topology_sha256"],
        sha256_file(topo),
    )
    r.check(
        "source topology is byte-identical to the supplied file",
        sha256_file(topo) == sha256_file(REPO / "britannia_global_bank_topology.yaml"),
    )
    ledger = load(REPO / "01-source/generated/mapping-ledger.json")
    r.counts["topology_fields_classified"] = len(ledger["ledger"])
    by_class: dict[str, int] = {}
    for row in ledger["ledger"]:
        by_class[row["classification"]] = by_class.get(row["classification"], 0) + 1
    r.counts["fields_by_classification"] = dict(sorted(by_class.items()))
    r.counts["blueprint"] = ledger["counts"]
    r.check(
        "every ledger row carries a rationale",
        all(row["rationale"].strip() for row in ledger["ledger"]),
    )
    cb = load(REPO / "01-source/generated/cross-boundary-pairs.json")
    r.counts["cross_boundary_pairs"] = {
        "ownership": len(cb["ownership_pairs"]),
        "dependency": len(cb["dependency_pairs"]),
    }

    # ---------------------------------------------------------------- zone 2
    public = REPO / "02-synthworld-public"
    index = load(public / "PUBLIC-INDEX.json")["sha256"]
    r.counts["public_files"] = len(index)
    ok = True
    for rel, digest in sorted(index.items()):
        p = public / rel
        if not p.exists() or sha256_file(p) != digest:
            ok = False
    r.check("every public artifact matches its recorded digest", ok)

    evaluator_root = REPO / "06-evaluator/artifacts/synthworld"
    # Zone 2 must be a byte-identical copy of the public half of zone 6, and must
    # contain nothing else.
    mirror_ok = True
    for rel in sorted(index):
        tree, name = rel.split("/", 1)
        src = evaluator_root / tree / "public" / name
        if not src.exists() or sha256_file(src) != index[rel]:
            mirror_ok = False
    r.check("zone 2 is a byte-identical copy of zone 6 public files", mirror_ok)

    stray = sorted(
        p.relative_to(public).as_posix()
        for p in public.rglob("*")
        if p.is_file() and p.name != "PUBLIC-INDEX.json"
        and p.relative_to(public).as_posix() not in index
    )
    r.check("zone 2 contains no file outside the public inventory", not stray, str(stray))

    # Determinism: the compiled artifacts must reproduce the recorded digests.
    expected = cfg["determinism"].get("expected_digests", {})
    for artifact, tree, name in (
        ("identity_access_universe", "identity-access", "identity-access-universe.json"),
        ("evaluation_corpus", "evaluation-corpus", "evaluation-corpus.json"),
    ):
        want = expected.get(artifact)
        got = next(
            (
                a["digest"]["value"]
                for a in load(public / tree / "manifest.json")["artifacts"]
                if a["path"] == name
            ),
            None,
        )
        r.check(
            f"{artifact} reproduces its recorded digest",
            want is not None and want == got,
            f"expected {want} got {got}",
        )

    universe = load(public / "identity-access/identity-access-universe.json")
    corpus = load(public / "evaluation-corpus/evaluation-corpus.json")
    kernel = load(public / "directory-rbac/directory-rbac-kernel.json")
    r.counts["universe"] = {
        k: len(v) for k, v in sorted(universe.items()) if isinstance(v, list)
    }
    r.counts["corpus"] = {
        k: len(v) for k, v in sorted(corpus.items()) if isinstance(v, list)
    }
    r.counts["directory_kernel"] = {
        k: len(v) for k, v in sorted(kernel.items()) if isinstance(v, list)
    }

    # ------------------------------------------------- referential integrity
    subject_ids = {s["subject_id"] for s in universe["access_subjects"]}
    target_ids = {t["authorization_target_id"] for t in universe["authorization_targets"]}
    atom_ids = {a["access_atom_id"] for a in universe["access_atoms"]}
    perm_pairs = {
        (p["authorization_target_id"], p["action"]) for p in universe["permissions"]
    }
    r.check(
        "every access atom references a known subject",
        all(a["subject_id"] in subject_ids for a in universe["access_atoms"]),
    )
    r.check(
        "every access atom references a known authorization target",
        all(a["authorization_target_id"] in target_ids for a in universe["access_atoms"]),
    )
    r.check(
        "every access atom has a matching permission",
        all(
            (a["authorization_target_id"], a["action"]) in perm_pairs
            for a in universe["access_atoms"]
        ),
    )
    r.check(
        "every evaluation cell references a known access atom",
        all(c["access_atom_id"] in atom_ids for c in corpus["evaluation_cells"]),
    )
    cell_ids = [c["cell_id"] for c in corpus["evaluation_cells"]]
    r.check("cell ids are unique", len(cell_ids) == len(set(cell_ids)))
    r.check(
        "exactly one access request per cell",
        sorted(x["cell_id"] for x in corpus["access_requests"]) == sorted(cell_ids),
    )
    perm_ids = {p["permission_id"] for p in universe["permissions"]}
    r.check(
        "every role grant references a known permission",
        all(g["permission_id"] in perm_ids for g in kernel["role_grants"]),
    )
    r.check(
        "every account observation references a known account",
        all(
            o["account_id"] in {a["account_id"] for a in universe["accounts"]}
            for o in kernel["account_observations"]
        ),
    )

    # ---------------------------------------------------------------- zone 3
    z3 = REPO / "03-topaz-input"
    objects = z3 / "directory/objects.jsonl"
    relations = z3 / "directory/relations.jsonl"
    requests = z3 / "requests/authz-requests.jsonl"
    if objects.exists():
        n_obj = sum(1 for _ in objects.open())
        n_rel = sum(1 for _ in relations.open())
        n_req = sum(1 for _ in requests.open())
        r.counts["topaz_input"] = {
            "objects": n_obj,
            "relations": n_rel,
            "authz_requests": n_req,
        }
        r.check(
            "one authorization request per evaluation cell",
            n_req == len(cell_ids),
            f"{n_req} vs {len(cell_ids)}",
        )
        r.check("topaz model manifest present", (z3 / "model/manifest.yaml").exists())
        r.check(
            "rego policy present",
            (z3 / "policy/britannia/authz.rego").exists(),
        )
    else:
        r.check("zone 3 populated", False, "stage 30 has not run")

    # ---------------------------------------------------------------- zone 4
    raw = REPO / "04-topaz-results/raw/decisions.jsonl"
    norm = REPO / "04-topaz-results/normalized/decisions.json"
    if raw.exists() and norm.exists():
        n_raw = sum(1 for _ in raw.open())
        decisions = load(norm)
        r.counts["topaz_results"] = {
            "raw_lines": n_raw,
            "normalized_cells": len(decisions),
        }
        r.check(
            "a raw decision was recorded for every cell",
            n_raw == len(cell_ids),
            f"{n_raw} vs {len(cell_ids)}",
        )
        r.check(
            "every normalized decision maps to a public corpus cell",
            set(decisions) <= set(cell_ids),
        )
        dist: dict[str, dict[str, int]] = {}
        for d in decisions.values():
            for k, v in d.items():
                dist.setdefault(k, {})
                dist[k][str(v)] = dist[k].get(str(v), 0) + 1
        r.counts["decision_distribution"] = {
            k: dict(sorted(v.items())) for k, v in sorted(dist.items())
        }
    else:
        r.check("zone 4 populated", False, "stage 40 has not run")

    # ---------------------------------------------------------------- zone 5
    sub = REPO / "05-submission"
    if (sub / "SUBMISSION-DIGEST.json").exists():
        manifest = load(sub / "SUBMISSION-DIGEST.json")
        ok = True
        for name, digest in sorted(manifest["sha256"].items()):
            raw_bytes = (sub / name).read_bytes().rstrip(b"\n")
            if hashlib.sha256(raw_bytes).hexdigest() != digest:
                ok = False
        r.check("submission files match their sealed digests", ok)
        r.counts["submission"] = {
            "combined_sha256": manifest["combined_sha256"],
            "cells": manifest["cells_in_public_corpus"],
            "answered_by_topaz": manifest["cells_answered_by_topaz"],
            "defaulted_to_deny": manifest["cells_defaulted_to_deny"],
        }
        pred = load(sub / "directory-rbac-prediction.json")
        r.check(
            "submission covers every public corpus cell exactly once",
            sorted(c["cell_id"] for c in pred["cells"]) == sorted(cell_ids),
        )
    else:
        r.check("zone 5 populated", False, "stage 50 has not run")

    # ---------------------------------------------------------------- zone 6
    scoring = REPO / "06-evaluator/scoring/scoring-report.json"
    if scoring.exists():
        report = load(scoring)
        r.check(
            "scoring verified the submission digest before opening truth",
            report.get("submission_digest_verified_before_scoring") is True,
        )
        r.check(
            "scoring digest equals the sealed submission digest",
            report.get("submission_digest")
            == r.counts.get("submission", {}).get("combined_sha256"),
        )
        r.check(
            "no aggregate score was invented",
            report.get("aggregate") is None,
        )
        r.counts["scoring"] = {
            "scored_metrics": len(report.get("scored_metrics", [])),
            "not_publicly_winnable": len(report.get("not_publicly_winnable", [])),
            "world_property_metrics": len(
                report.get("world_property_metrics_not_scores", [])
            ),
        }
    else:
        r.check("zone 6 scoring present", False, "stage 60 has not run")

    # --------------------------------------------------- leakage: viz + zone 3
    viz = REPO / "viz/britannia-world.html"
    if viz.exists():
        text = viz.read_text("utf-8", errors="ignore")
        leaked = [t for t in EVALUATOR_TERMS if t in text]
        r.check(
            "HTML visualization contains no evaluator term",
            not leaked,
            f"leaked: {leaked}",
        )
        r.check(
            "HTML visualization carries the required label",
            "External experiment visualization - not a SynthWorld renderer" in text
            or "External experiment visualization — not a SynthWorld renderer" in text,
        )
        r.counts["visualization_bytes"] = viz.stat().st_size
    else:
        r.check("visualization present", False, "stage 70 has not run")

    # ------------------------------------------------- environment provenance
    import importlib.metadata as md

    installed = md.version("idcognito-synthworld")
    r.check(
        "installed SynthWorld distribution is exactly 0.15.0",
        installed == "0.15.0",
        installed,
    )
    # The wheel hash recorded in experiment.yaml must match what PyPI publishes for
    # 0.15.0. Recorded rather than re-downloaded so validation stays offline.
    r.check(
        "recorded wheel digest is a 64-char sha256",
        len(cfg["synthworld"]["wheel_sha256"]) == 64
        and all(c in "0123456789abcdef" for c in cfg["synthworld"]["wheel_sha256"]),
    )
    r.counts["synthworld"] = {
        "version": "0.15.0",
        "wheel_sha256": cfg["synthworld"]["wheel_sha256"],
    }

    compose = (REPO / "infra/docker-compose.yaml").read_text("utf-8")
    r.check("topaz image is pinned by digest", "@sha256:" in compose)
    r.check("no :latest tag in compose", ":latest" not in compose)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "checks": r.checks,
        "checks_total": len(r.checks),
        "checks_failed": r.failed,
        "counts": r.counts,
    }
    out.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", "utf-8")

    for c in r.checks:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['check']}"
              + (f"  -- {c['detail']}" if c["detail"] and not c["pass"] else ""))
    print(f"\n{len(r.checks) - r.failed}/{len(r.checks)} checks passed")
    print(f"report -> {out}")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
