#!/usr/bin/env python3
"""Stage 20 - compile the SynthWorld enterprise identity/access world, the
evaluation corpus, the three authorization families, and the evaluator truth.

ZONE MODEL
----------
This stage is the WORLD GENERATOR. A generator legitimately handles both public
and evaluator material - that is what "generator" means. It writes:

  06-evaluator/artifacts/synthworld/   the intact SynthWorld trees (public/ +
                                       evaluator/ side by side, which is what the
                                       released loaders require)
  02-synthworld-public/                byte-identical copies of ONLY the public
                                       files, and nothing else

Every later stage that touches Topaz (30, 40, 50) reads 02 exclusively and is
hard-guarded against opening anything under 06. Stage 60 is the only consumer of
evaluator material, and it runs after the submission digest is recorded.

CONSTRUCTION STYLE
------------------
Every released operator-input model is pydantic `strict=True` with `extra=forbid`,
and neither the nested record classes nor the enums are exported from
`synthworld.enterprise.__all__`. The only public construction path is therefore
JSON mode: build a plain dict, then `Model.model_validate_json(json.dumps(doc))`.
That is what `_from_json` does throughout.

Digests: several input models require a `SyntheticDigestV1` of an artifact, but
the canonical-digest helpers are not exported. The released exporters write a
`manifest.json` carrying exactly that digest, so this stage exports first and
reads the digest back out. This forces a disk round-trip between steps.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml
from synthworld.enterprise.consumer import (
    AuthorizationEvaluationProfileV1,
    EnterpriseAbacIntentOverlayV1,
    EnterpriseAbacStateOverlayV1,
    EnterpriseAuthorizationEvaluationScopeV1,
    EnterpriseAuthorizationEvaluatorArtifactsV1,
    EnterpriseAuthorizationPublicArtifactsV1,
    EnterpriseDirectoryRbacIntentOverlayV1,
    EnterpriseEvaluationCorpusConfigV1,
    EnterpriseIdentityAccessImportV1,
    EnterpriseRbacSessionStateInputV1,
    EnterpriseRebacIntentOverlayV1,
    EnterpriseRebacStateOverlayV1,
    compile_enterprise_abac_truth,
    compile_enterprise_access_state,
    compile_enterprise_authorization_kernel,
    compile_enterprise_directory_rbac_kernel,
    compile_enterprise_directory_rbac_truth,
    compile_enterprise_evaluation_corpus,
    compile_enterprise_identity_access_universe,
    compile_enterprise_rebac_truth,
    compose_enterprise_authorization,
    digest_enterprise_model,
    export_enterprise_authorization,
    export_enterprise_directory_rbac,
    export_enterprise_evaluation_corpus,
    export_enterprise_identity_access_compile_result,
    load_enterprise_identity_access_import,
    load_public_enterprise_evaluation_corpus,
    load_public_enterprise_identity_access_universe,
    validate_enterprise_identity_access,
)

REPO = Path(__file__).resolve().parent.parent

# Public files, per released tree. Copied verbatim into zone 02.
PUBLIC_INVENTORY = {
    "identity-access": ["identity-access-universe.json", "manifest.json"],
    "evaluation-corpus": ["evaluation-corpus.json", "manifest.json"],
    "directory-rbac": ["directory-rbac-kernel.json", "manifest.json"],
    "authorization": [
        "abac-intent.json",
        "abac-state.json",
        "rebac-intent.json",
        "rebac-state.json",
        "authorization-composition.json",
        "authorization-evaluation-scope.json",
        "authorization-kernel.json",
        "manifest.json",
    ],
}

CASE_LABELS = {
    "A": "same-tenant-allow",
    "B": "deny-missing-role-or-relation",
    "C": "deny-cross-tenant-boundary",
    "D": "deny-scope-exceeded",
    "E": "deny-wrong-principal-binding",
    "F": "temporal-revocation",
}


def _from_json(model: Any, document: dict) -> Any:
    """Only public construction path - see module docstring."""
    return model.model_validate_json(json.dumps(document))


def _manifest_digest(tree: Path, visibility: str, filename: str) -> dict:
    manifest = json.loads((tree / visibility / "manifest.json").read_text("utf-8"))
    for artifact in manifest["artifacts"]:
        if artifact["path"] == filename:
            return artifact["digest"]
    raise SystemExit(f"no digest for {filename} in {tree}/{visibility}/manifest.json")


def _pick(identifier: str, modulus: int) -> int:
    """Deterministic bucket for an opaque id. Replaces any use of randomness so
    the world is a pure function of its inputs."""
    return int.from_bytes(hashlib.sha256(identifier.encode()).digest()[:8], "big") % modulus


def _rev(*parts: str) -> str:
    return "rev-" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


class WorldBuilder:
    def __init__(self, config: dict, import_path: Path, out_root: Path) -> None:
        self.c = config
        self.import_path = import_path
        self.root = out_root
        self.seed = int(config["determinism"]["seed"])
        self.base_tick = int(config["temporal"]["base_tick"])
        self.expired_tick = int(config["temporal"]["expired_tick"])
        self.stats: dict[str, Any] = {}
        self.case_assignment: dict[str, str] = {}  # cell_key -> case class letter

    # ---------------------------------------------------------------- step 1-3

    def compile_universe(self) -> None:
        base = load_enterprise_identity_access_import(self.import_path)
        report = validate_enterprise_identity_access(base)
        if not report.valid:
            raise SystemExit(f"import invalid: {[d.code for d in report.diagnostics][:10]}")

        # Pass 1. account_observations and direct_entitlements reference COMPILED
        # ids, which do not exist until the universe is frozen. Compile once to
        # learn the ids, enrich, then compile again. The released compiler
        # re-freezes an identical universe and the kernel compiler independently
        # verifies that (`kernel_universe_mapping_mismatch`).
        first = compile_enterprise_identity_access_universe(import_model=base, seed=self.seed)
        u1 = first.public_universe
        canonical = {
            b.account_id: b.principal_id for b in first.evaluator_canonical_binding_truth.bindings
        }

        document = json.loads(base.model_dump_json())
        document["directory_rbac_state"]["account_observations"] = self._account_observations(
            u1, canonical
        )
        enriched = _from_json(EnterpriseIdentityAccessImportV1, document)

        report2 = validate_enterprise_identity_access(enriched)
        if not report2.valid:
            raise SystemExit(
                "enriched import invalid: "
                f"{[(d.code, d.logical_key) for d in report2.diagnostics][:10]}"
            )

        result = compile_enterprise_identity_access_universe(import_model=enriched, seed=self.seed)
        export_enterprise_identity_access_compile_result(self.root / "identity-access", result)
        self.enriched_import = enriched
        self.universe = load_public_enterprise_identity_access_universe(
            self.root / "identity-access"
        )
        self.binding_truth = result.evaluator_canonical_binding_truth
        self.universe_digest = _manifest_digest(
            self.root / "identity-access", "public", "identity-access-universe.json"
        )

        # public indexes used everywhere below
        self.subject_by_id = {s.subject_id: s for s in self.universe.access_subjects}
        self.principal_by_id = {p.principal_id: p for p in self.universe.principals}
        self.account_by_id = {a.account_id: a for a in self.universe.accounts}
        self.target_by_id = {
            t.authorization_target_id: t for t in self.universe.authorization_targets
        }
        self.unit_by_id = {u.unit_id: u for u in self.universe.units}
        self.tenant_ids = sorted(t.tenant_id for t in self.universe.tenants)
        self.perm_by_id = {p.permission_id: p for p in self.universe.permissions}
        self.stats["universe"] = {
            "tenants": len(self.universe.tenants),
            "units": len(self.universe.units),
            "principals": len(self.universe.principals),
            "accounts": len(self.universe.accounts),
            "access_subjects": len(self.universe.access_subjects),
            "authorization_targets": len(self.universe.authorization_targets),
            "permissions": len(self.universe.permissions),
            "access_atoms": len(self.universe.access_atoms),
        }

    def _account_observations(self, universe: Any, canonical: dict) -> list[dict]:
        """Observed directory bindings. Most are correct; a deterministic slice is
        deliberately wrong (case E) or time-bounded / suspended (case F).

        This is generator-side authoring. The *canonical* binding stays evaluator
        truth; what goes into the public kernel is only the OBSERVED binding, which
        is exactly the question `binding_status` asks.
        """
        rows: list[dict] = []
        accounts = sorted(universe.accounts, key=lambda a: a.account_id)
        principals_by_tenant: dict[str, list[str]] = {}
        for p in sorted(universe.principals, key=lambda p: p.principal_id):
            principals_by_tenant.setdefault(p.tenant_id, []).append(p.principal_id)

        self.mismatch_accounts: set[str] = set()
        self.suspended_accounts: set[str] = set()
        self.expiring_accounts: set[str] = set()

        for acct in accounts:
            aid = acct.account_id
            bucket = _pick(aid, 20)
            observed = canonical.get(aid)
            state = "active"
            valid_until: int | None = None

            if bucket == 0:
                # Case E: the directory has this account bound to the wrong human.
                pool = principals_by_tenant.get(acct.tenant_id, [])
                alt = [p for p in pool if p != observed]
                if alt:
                    observed = alt[_pick(aid + ":alt", len(alt))]
                    self.mismatch_accounts.add(aid)
            elif bucket == 1:
                # Case F: administratively suspended but never de-provisioned.
                state = "suspended"
                self.suspended_accounts.add(aid)
            elif bucket == 2:
                # Case F: entitlement with an expiry that lapses between the two
                # evaluation ticks.
                valid_until = (self.base_tick + self.expired_tick) // 2
                self.expiring_accounts.add(aid)

            rows.append(
                {
                    "account_id": aid,
                    "observed_principal_id": observed,
                    "administrative_state": state,
                    "valid_from_tick": 0,
                    "valid_until_tick": valid_until,
                    "revision_id": _rev("acctobs", aid),
                }
            )
        return rows

    # ------------------------------------------------------------------ step 4

    def compile_kernel(self) -> None:
        """The RBAC kernel must exist BEFORE the corpus: the corpus needs role ids,
        and the public universe anonymises role display labels. The only public
        route from a role id to its meaning is kernel.role_grants joined to
        universe.permissions."""
        self.kernel = compile_enterprise_directory_rbac_kernel(
            import_model=self.enriched_import, universe=self.universe
        )
        # role_id -> set of actions it grants (public derivation)
        self.role_actions: dict[str, set[str]] = {}
        self.role_targets: dict[str, set[str]] = {}
        for g in self.kernel.role_grants:
            perm = self.perm_by_id[g.permission_id]
            self.role_actions.setdefault(g.role_id, set()).add(perm.action)
            self.role_targets.setdefault(g.role_id, set()).add(perm.authorization_target_id)
        self._build_derivation_index()
        self.stats["kernel"] = {
            "memberships": len(self.kernel.memberships),
            "group_nesting": len(self.kernel.group_nesting),
            "group_role_assignments": len(self.kernel.group_role_assignments),
            "subject_role_assignments": len(self.kernel.subject_role_assignments),
            "role_hierarchy": len(self.kernel.role_hierarchy),
            "role_grants": len(self.kernel.role_grants),
            "account_observations": len(self.kernel.account_observations),
            "direct_entitlements": len(self.kernel.direct_entitlements),
        }

    def _build_derivation_index(self) -> None:
        """Resolve, for every subject, the set of permissions the OBSERVED
        directory actually derives.

        This uses only the public kernel and the public universe, and it is the
        same traversal the Rego policy performs independently in stage 30:
          subject -> direct group memberships
                  -> transitive parent groups (group_nesting)
                  -> roles (direct assignment + group role assignment)
                  -> junior roles (role_hierarchy, senior inherits junior)
                  -> permissions (role_grants)
                  + direct entitlements
        Used here only to label case classes accurately. The Rego implementation
        is written from the public artifacts, not from this code.
        """
        parents: dict[str, set[str]] = {}
        for n in self.kernel.group_nesting:
            parents.setdefault(n.child_group_id, set()).add(n.parent_group_id)
        juniors: dict[str, set[str]] = {}
        for h in self.kernel.role_hierarchy:
            juniors.setdefault(h.senior_role_id, set()).add(h.junior_role_id)
        group_roles: dict[str, set[str]] = {}
        for a in self.kernel.group_role_assignments:
            group_roles.setdefault(a.group_id, set()).add(a.role_id)
        role_perms: dict[str, set[str]] = {}
        for g in self.kernel.role_grants:
            role_perms.setdefault(g.role_id, set()).add(g.permission_id)

        direct_groups: dict[str, set[str]] = {}
        for m in self.kernel.memberships:
            direct_groups.setdefault(m.subject_id, set()).add(m.group_id)
        self.subject_roles: dict[str, set[str]] = {}
        for a in self.kernel.subject_role_assignments:
            self.subject_roles.setdefault(a.subject_id, set()).add(a.role_id)

        def close(seed: set[str], edges: dict[str, set[str]]) -> set[str]:
            seen, stack = set(seed), list(seed)
            while stack:
                cur = stack.pop()
                for nxt in edges.get(cur, ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            return seen

        self.permission_id_by_pair = {
            (p.authorization_target_id, p.action): p.permission_id
            for p in self.universe.permissions
        }
        direct_ent: dict[str, set[str]] = {}
        for e in self.kernel.direct_entitlements:
            direct_ent.setdefault(e.subject_id, set()).add(e.permission_id)

        def perms_for(sid: str) -> set[str]:
            groups = close(direct_groups.get(sid, set()), parents)
            roles = set(self.subject_roles.get(sid, set()))
            for g in groups:
                roles |= group_roles.get(g, set())
            roles = close(roles, juniors)
            out: set[str] = set(direct_ent.get(sid, set()))
            for r in roles:
                out |= role_perms.get(r, set())
            return out

        # An account carries no roles of its own: its authority is the authority of
        # the principal the directory believes it belongs to. That is exactly why
        # `binding_status` is a scored question - if the observed binding points at
        # the wrong human, the account inherits the wrong authority.
        self.observed_principal_of: dict[str, str] = {
            o.account_id: o.observed_principal_id
            for o in self.kernel.account_observations
            if o.observed_principal_id is not None
        }
        self.derived_permissions: dict[str, set[str]] = {}
        for subject in self.universe.access_subjects:
            sid = subject.subject_id
            perms = perms_for(sid)
            if subject.subject_kind == "account":
                bound = self.observed_principal_of.get(sid)
                if bound:
                    perms |= perms_for(bound)
            if perms:
                self.derived_permissions[sid] = perms

    def _derives(self, atom: Any) -> bool:
        pid = self.permission_id_by_pair.get((atom.authorization_target_id, atom.action))
        if pid is None:
            return False
        return pid in self.derived_permissions.get(atom.subject_id, ())

    # ------------------------------------------------------------------ step 5

    def _subject_tenant(self, subject_id: str) -> str:
        return self.subject_by_id[subject_id].tenant_id

    def _subject_unit(self, subject_id: str) -> str | None:
        p = self.principal_by_id.get(subject_id)
        if p is not None:
            return p.unit_id
        acct = self.account_by_id.get(subject_id)
        if acct is None:
            return None
        target = self.target_by_id.get(acct.authorization_target_id)
        return target.owner_unit_id if target else None

    def _classify(self, atom: Any, tick: int) -> str:
        """Assign one of the six case classes to a cell, using ONLY public
        structure. Order matters: the first matching class wins."""
        sid = atom.subject_id
        target = self.target_by_id[atom.authorization_target_id]
        subject = self.subject_by_id[sid]
        is_account = subject.subject_kind == "account"

        # Runtime gates first: a bad binding or a lapsed entitlement decides the
        # cell regardless of what the role graph says.
        if is_account and sid in self.mismatch_accounts:
            return "E"
        if is_account and (sid in self.suspended_accounts or sid in self.expiring_accounts):
            return "F"
        # No derivable role path at all -> the principal genuinely lacks the
        # required role or relation. Checked BEFORE the guard classes so a cell is
        # never labelled "denied by the scope guard" when RBAC already denies it.
        if not self._derives(atom):
            return "B"
        if sid in self.cross_tenant_cells_subjects and atom.action != "deploy":
            return "C"
        if atom.action == "deploy" and self._subject_unit(sid) != target.owner_unit_id:
            return "D"
        return "A"

    def build_corpus(self, max_cells: int | None) -> None:
        atoms = sorted(self.universe.access_atoms, key=lambda a: a.access_atom_id)
        if max_cells is not None:
            atoms = atoms[:max_cells]

        # Case C selection: principals whose tenant differs from the tenant we will
        # assert for the resource. Chosen deterministically from principal subjects
        # that sit in a tenant with at least one other tenant available.
        self.cross_tenant_cells_subjects = {
            s.subject_id
            for s in sorted(self.universe.access_subjects, key=lambda s: s.subject_id)
            if s.subject_kind == "principal" and _pick(s.subject_id + ":ct", 12) == 0
        }

        contexts = [{"context_key": "ctx-internal"}, {"context_key": "ctx-partner"}]
        cells: list[dict] = []
        requests: list[dict] = []
        self.cell_meta: dict[str, dict] = {}

        for atom in atoms:
            sid = atom.subject_id
            ctx = (
                "ctx-partner"
                if self.subject_by_id[sid].subject_kind == "account"
                else "ctx-internal"
            )
            key = f"cell-{atom.access_atom_id}-t{self.base_tick}"
            cells.append(
                {
                    "cell_key": key,
                    "access_atom_id": atom.access_atom_id,
                    "context_key": ctx,
                    "session_state_key": None,
                    "tick": self.base_tick,
                }
            )
            requests.append({"request_key": f"req-{key}", "cell_key": key})
            cls = self._classify(atom, self.base_tick)
            self.case_assignment[key] = cls
            self.cell_meta[key] = {
                "atom": atom,
                "tick": self.base_tick,
                "context": ctx,
                "case": cls,
            }

            # Second evaluation tick for the temporal cohort: same atom, later
            # tick, so the revocation/expiry transition is observable.
            if sid in self.expiring_accounts or sid in self.suspended_accounts:
                key2 = f"cell-{atom.access_atom_id}-t{self.expired_tick}"
                cells.append(
                    {
                        "cell_key": key2,
                        "access_atom_id": atom.access_atom_id,
                        "context_key": ctx,
                        "session_state_key": None,
                        "tick": self.expired_tick,
                    }
                )
                requests.append({"request_key": f"req-{key2}", "cell_key": key2})
                self.case_assignment[key2] = "F"
                self.cell_meta[key2] = {
                    "atom": atom,
                    "tick": self.expired_tick,
                    "context": ctx,
                    "case": "F",
                }

        evaluator_cases = []
        for k in sorted(self.case_assignment):
            labels = [CASE_LABELS[self.case_assignment[k]], "directory-rbac"]
            # The temporal cohort is a matched pair on the same access atom: one
            # cell before the entitlement lapses and one after. Label the phase so
            # the transition can be sliced, rather than pretending the pre-expiry
            # cell is a denial.
            if self.case_assignment[k] == "F":
                labels.append(
                    "post-expiry"
                    if self.cell_meta[k]["tick"] == self.expired_tick
                    else "pre-expiry"
                )
            evaluator_cases.append(
                {
                    "case_key": f"case-{k}",
                    "target_kind": "access_cell",
                    "target_key": k,
                    "labels": labels,
                }
            )

        cfg = _from_json(
            EnterpriseEvaluationCorpusConfigV1,
            {
                "identity_access_universe_digest": self.universe_digest,
                "contexts": contexts,
                "evaluation_cells": cells,
                "access_requests": requests,
                "evaluator_cases": evaluator_cases,
            },
        )
        result = compile_enterprise_evaluation_corpus(universe=self.universe, corpus_config=cfg)
        export_enterprise_evaluation_corpus(self.root / "evaluation-corpus", result)
        self.corpus = load_public_enterprise_evaluation_corpus(self.root / "evaluation-corpus")
        self.corpus_digest = _manifest_digest(
            self.root / "evaluation-corpus", "public", "evaluation-corpus.json"
        )

        # cell_key -> cell_id.
        #
        # The compiler does NOT preserve the declared cell order, and cell_id is
        # uuid5 over a namespace constant that is not public, so neither ordering
        # nor re-derivation is safe. Recover the mapping from the corpus itself:
        # (access_atom_id, context_id, session_state_id, tick) is unique by
        # construction - the compiler enforces it as
        # `duplicate_evaluation_cell_tuple` - and this experiment uses exactly one
        # context per atom, so (access_atom_id, tick) is a sufficient key and
        # matches the cell_key format used above.
        self.cell_id_by_key = {
            f"cell-{c.access_atom_id}-t{c.tick}": c.cell_id for c in self.corpus.evaluation_cells
        }
        if len(self.cell_id_by_key) != len(self.corpus.evaluation_cells):
            raise SystemExit(
                "cell key collision: (access_atom_id, tick) is not unique; "
                "the cell_key scheme must be widened"
            )
        missing = set(self.case_assignment) - set(self.cell_id_by_key)
        if missing:
            raise SystemExit(f"{len(missing)} declared cells missing from corpus")
        self.cell_key_by_id = {v: k for k, v in self.cell_id_by_key.items()}
        self.cell_by_id = {c.cell_id: c for c in self.corpus.evaluation_cells}
        self.case_by_cell_id = {self.cell_id_by_key[k]: v for k, v in self.case_assignment.items()}
        counts: dict[str, int] = {}
        for v in self.case_assignment.values():
            counts[CASE_LABELS[v]] = counts.get(CASE_LABELS[v], 0) + 1
        self.stats["corpus"] = {
            "contexts": len(self.corpus.contexts),
            "evaluation_cells": len(self.corpus.evaluation_cells),
            "access_requests": len(self.corpus.access_requests),
            "evaluator_cases": len(evaluator_cases),
            "case_class_counts": dict(sorted(counts.items())),
        }

    # ------------------------------------------------------------------ step 6

    def build_rbac_truth(self) -> None:
        """Intent overlay mirrors the observed directory except for a deliberate,
        deterministic slice of sprawl. It is EXPERIMENT-OWNED and never published:
        `intended_decision` is consequently not derivable from any public artifact.
        See the limitations report."""
        drop_grant = {
            g.edge_id for g in self.kernel.role_grants if _pick(g.edge_id + ":sprawl", 25) == 0
        }
        intent = {
            "identity_access_universe_digest": self.universe_digest,
            "evaluation_corpus_digest": self.corpus_digest,
            "intended_memberships": [
                {"subject_id": m.subject_id, "group_id": m.group_id}
                for m in self.kernel.memberships
            ],
            "intended_group_nesting": [
                {
                    "child_group_id": n.child_group_id,
                    "parent_group_id": n.parent_group_id,
                }
                for n in self.kernel.group_nesting
            ],
            "intended_group_role_assignments": [
                {"group_id": a.group_id, "role_id": a.role_id}
                for a in self.kernel.group_role_assignments
            ],
            "intended_subject_role_assignments": [
                {"subject_id": a.subject_id, "role_id": a.role_id}
                for a in self.kernel.subject_role_assignments
            ],
            "intended_role_hierarchy": [
                {"senior_role_id": h.senior_role_id, "junior_role_id": h.junior_role_id}
                for h in self.kernel.role_hierarchy
            ],
            "intended_role_grants": [
                {"role_id": g.role_id, "permission_id": g.permission_id}
                for g in self.kernel.role_grants
                if g.edge_id not in drop_grant
            ],
            "ssd_constraints": self._ssd_constraints(),
        }
        self.rbac_intent = _from_json(EnterpriseDirectoryRbacIntentOverlayV1, intent)
        self.session_state = _from_json(
            EnterpriseRbacSessionStateInputV1,
            {"evaluation_corpus_digest": self.corpus_digest, "sessions": []},
        )
        self.rbac_truth = compile_enterprise_directory_rbac_truth(
            universe=self.universe,
            canonical_binding_truth=self.binding_truth,
            corpus=self.corpus,
            directory_rbac_kernel=self.kernel,
            session_state=self.session_state,
            directory_rbac_intent=self.rbac_intent,
        )
        self.stats["rbac_truth_cells"] = len(self.rbac_truth.cells)
        self.stats["intent_grants_dropped"] = len(drop_grant)

    def _ssd_constraints(self) -> list[dict]:
        """Three-lines-of-defence segregation: no subject should hold both an
        operating role and the oversight role for the same domain. Grounded in
        organisation.metadata.lines_of_defence in the source topology.

        Selected structurally: within a tenant, pair roles that grant `deploy`
        with roles that grant only `read` over an overlapping target set.
        """
        out: list[dict] = []
        by_tenant: dict[str, list[str]] = {}
        for role in sorted(self.universe.roles, key=lambda r: r.role_id):
            by_tenant.setdefault(role.tenant_id, []).append(role.role_id)
        for tenant, roles in sorted(by_tenant.items()):
            admin = [r for r in roles if "deploy" in self.role_actions.get(r, set())]
            audit = [r for r in roles if self.role_actions.get(r) == {"read"}]
            for i, (a, b) in enumerate(zip(sorted(admin), sorted(audit), strict=False)):
                if self.role_targets.get(a, set()) & self.role_targets.get(b, set()):
                    out.append(
                        {
                            "constraint_id": f"ssd-{tenant}-{i}",
                            "tenant_id": tenant,
                            "role_ids": [a, b],
                            "cardinality": 2,
                        }
                    )
                if len(out) >= 40:
                    break
        return out

    # ------------------------------------------------------------------ step 7

    def build_abac(self) -> None:
        """Per-cell attribute facts plus a small, explicit rule set.

        ABAC facts are cell-scoped assertions about the decision context, not a
        mirror of the universe: `value` is validated for existence only. That is
        the mechanism the released contract provides for expressing a boundary
        violation, and it is what case C uses - the asserted resource tenant is a
        real, different tenant, standing for a request served by a deployment
        outside the subject's legal entity.
        """
        action_class = self.c["resources"]["action_to_action_class"]
        facts: list[dict] = []
        allow_cells: list[str] = []
        deny_cross: list[str] = []
        deny_scope: list[str] = []

        for cell in self.corpus.evaluation_cells:
            cid = cell.cell_id
            case = self.case_by_cell_id[cid]
            meta_key = self.cell_key_by_id[cid]
            atom = self.cell_meta[meta_key]["atom"]
            sid = atom.subject_id
            target = self.target_by_id[atom.authorization_target_id]
            subj_tenant = self._subject_tenant(sid)

            res_tenant = target.tenant_id
            if case == "C":
                others = [t for t in self.tenant_ids if t != subj_tenant]
                res_tenant = others[_pick(cid + ":rt", len(others))]
                deny_cross.append(cid)
            elif case == "D":
                deny_scope.append(cid)
            else:
                allow_cells.append(cid)

            def fact(
                kind: str,
                key: str,
                category: str,
                value: Any,
                cell_id: str = cid,
            ) -> dict:
                return {
                    "kind": kind,
                    "category": category,
                    "attribute_key": key,
                    "fact_id": f"f-{kind}-{cell_id}",
                    "cell_id": cell_id,
                    "value_state": "known",
                    "value": value,
                    "revision_id": _rev(kind, cell_id),
                    "valid_from_tick": 0,
                    "valid_until_tick": None,
                }

            facts.extend(
                [
                    fact("subject_tenant_id", "tenant_id", "subject", subj_tenant),
                    fact("resource_tenant_id", "tenant_id", "resource", res_tenant),
                    fact("action_id", "action_id", "action", atom.action),
                    fact(
                        "action_class",
                        "action_class",
                        "action",
                        action_class[atom.action],
                    ),
                    fact(
                        "resource_target_kind",
                        "target_kind",
                        "resource",
                        target.target_kind,
                    ),
                    fact(
                        "environment_network_zone",
                        "network_zone",
                        "environment",
                        "partner"
                        if self.subject_by_id[sid].subject_kind == "account"
                        else "internal",
                    ),
                ]
            )

        rules: list[dict] = []
        if allow_cells:
            rules.append(
                {
                    "rule_id": "abac-allow-same-tenant",
                    "revision_id": _rev("abac", "allow"),
                    "effect": "allow",
                    "operator": "all",
                    "cell_ids": sorted(allow_cells),
                    "predicates": [{"kind": "same_tenant"}],
                    "valid_from_tick": 0,
                    "valid_until_tick": None,
                }
            )
        if deny_cross:
            rules.append(
                {
                    "rule_id": "abac-deny-cross-tenant",
                    "revision_id": _rev("abac", "cross"),
                    "effect": "deny",
                    "operator": "any",
                    "cell_ids": sorted(deny_cross),
                    "predicates": [
                        {
                            "kind": "action_class_is",
                            "values": ["read", "write", "execute", "admin"],
                        }
                    ],
                    "valid_from_tick": 0,
                    "valid_until_tick": None,
                }
            )
        if deny_scope:
            rules.append(
                {
                    "rule_id": "abac-deny-scope-exceeded",
                    "revision_id": _rev("abac", "scope"),
                    "effect": "deny",
                    "operator": "all",
                    "cell_ids": sorted(deny_scope),
                    "predicates": [{"kind": "action_class_is", "values": ["admin"]}],
                    "valid_from_tick": 0,
                    "valid_until_tick": None,
                }
            )

        payload = {
            "identity_access_universe_digest": self.universe_digest,
            "evaluation_corpus_digest": self.corpus_digest,
            "attribute_facts": facts,
            "rules": rules,
        }
        self.abac_state = _from_json(EnterpriseAbacStateOverlayV1, payload)
        self.abac_intent = _from_json(EnterpriseAbacIntentOverlayV1, payload)
        self.abac_truth = compile_enterprise_abac_truth(
            universe=self.universe,
            corpus=self.corpus,
            abac_state=self.abac_state,
            abac_intent=self.abac_intent,
        )
        self.stats["abac"] = {
            "facts": len(facts),
            "rules": len(rules),
            "allow_cells": len(allow_cells),
            "deny_cross_tenant_cells": len(deny_cross),
            "deny_scope_cells": len(deny_scope),
        }

    # ------------------------------------------------------------------ step 8

    def build_rebac(self) -> None:
        """Relationship layer. The released relation type matrix is closed:
        member_of: principal|account -> group; owns: principal|unit -> target;
        collaborates_on: principal|account|group -> target; manages: human
        principal -> human principal.
        """
        tuples: list[dict] = []
        owns_cells: list[str] = []
        for cell in self.corpus.evaluation_cells:
            cid = cell.cell_id
            meta_key = self.cell_key_by_id[cid]
            atom = self.cell_meta[meta_key]["atom"]
            sid = atom.subject_id
            target_id = atom.authorization_target_id
            subject = self.subject_by_id[sid]
            relation = "owns" if subject.subject_kind == "principal" else "collaborates_on"
            tuples.append(
                {
                    "tuple_id": f"rt-{cid}",
                    "tenant_id": subject.tenant_id,
                    "subject_entity_id": sid,
                    "relation": relation,
                    "object_entity_id": target_id,
                    "snapshot_id": "snap-1",
                    "revision_id": _rev("rebac", cid),
                    "valid_from_tick": 0,
                    "valid_until_tick": None,
                }
            )
            owns_cells.append(cid)

        rules = [
            {
                "template": "direct_subject_relation",
                "rule_id": "rebac-direct",
                "revision_id": _rev("rebac", "direct"),
                "effect": "allow",
                "cell_ids": sorted(owns_cells),
                "valid_from_tick": 0,
                "valid_until_tick": None,
                "relation": "owns",
            }
        ]
        payload = {
            "identity_access_universe_digest": self.universe_digest,
            "evaluation_corpus_digest": self.corpus_digest,
            "relation_tuples": tuples,
            "rules": rules,
        }
        self.rebac_state = _from_json(EnterpriseRebacStateOverlayV1, payload)
        self.rebac_intent = _from_json(EnterpriseRebacIntentOverlayV1, payload)
        self.rebac_truth = compile_enterprise_rebac_truth(
            universe=self.universe,
            corpus=self.corpus,
            rebac_state=self.rebac_state,
            rebac_intent=self.rebac_intent,
        )
        self.stats["rebac"] = {"relation_tuples": len(tuples), "rules": len(rules)}

    # ------------------------------------------------------------------ step 9

    def compose_and_export(self) -> None:
        composition = compose_enterprise_authorization(
            directory_rbac_truth=self.rbac_truth,
            abac_truth=self.abac_truth,
            rebac_truth=self.rebac_truth,
        )
        profile_kind = self.c["authorization"]["evaluation_profile"]
        profile = _from_json(
            AuthorizationEvaluationProfileV1,
            {
                "evaluation_corpus_digest": self.corpus_digest,
                "cells": [
                    {"cell_id": c.cell_id, "profile": profile_kind}
                    for c in self.corpus.evaluation_cells
                ],
            },
        )
        authorization_kernel = compile_enterprise_authorization_kernel(
            universe=self.universe,
            corpus=self.corpus,
            composition=composition,
            evaluation_profile=profile,
        )
        atoms = {item.access_atom_id: item for item in self.universe.access_atoms}
        evaluation_scope = _from_json(
            EnterpriseAuthorizationEvaluationScopeV1,
            {
                "evaluation_corpus_digest": self.corpus_digest,
                "authorization_kernel_digest": digest_enterprise_model(
                    authorization_kernel
                ).model_dump(mode="json"),
                "cells": [
                    {
                        "cell_id": cell.cell_id,
                        "scored_dimensions": [
                            "effective_decision",
                            "final_decision",
                            "policy_conflict",
                            *(
                                ["lifecycle_status"]
                                if self.subject_by_id[
                                    atoms[cell.access_atom_id].subject_id
                                ].subject_kind
                                == "account"
                                else []
                            ),
                        ],
                    }
                    for cell in self.corpus.evaluation_cells
                ],
            },
        )
        access_state = compile_enterprise_access_state(
            universe=self.universe,
            canonical_binding_truth=self.binding_truth,
            corpus=self.corpus,
            composition=composition,
            directory_rbac_truth=self.rbac_truth,
            evaluation_profile=profile,
            abac_truth=self.abac_truth,
            rebac_truth=self.rebac_truth,
        )
        export_enterprise_directory_rbac(
            self.root / "directory-rbac", kernel=self.kernel, truth=self.rbac_truth
        )
        export_enterprise_authorization(
            self.root / "authorization",
            public=EnterpriseAuthorizationPublicArtifactsV1(
                abac_state=self.abac_state,
                abac_intent=self.abac_intent,
                rebac_state=self.rebac_state,
                rebac_intent=self.rebac_intent,
                composition=composition,
                evaluation_scope=evaluation_scope,
                kernel=authorization_kernel,
            ),
            evaluator=EnterpriseAuthorizationEvaluatorArtifactsV1(
                abac_truth=self.abac_truth,
                rebac_truth=self.rebac_truth,
                access_state=access_state,
            ),
        )
        self.stats["evaluation_profile"] = profile_kind

    # ----------------------------------------------------------------- step 10

    def publish_public_copies(self, public_root: Path) -> dict:
        """Copy ONLY the public files into zone 02 and record a digest for each so
        the isolation boundary is verifiable, not merely asserted."""
        if public_root.exists():
            # The root is a Compose bind-mount in the reference lab and therefore
            # cannot itself be removed. Clear only its generated children.
            for child in public_root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        index: dict[str, str] = {}
        for tree, files in sorted(PUBLIC_INVENTORY.items()):
            src = self.root / tree / "public"
            dst = public_root / tree
            dst.mkdir(parents=True, exist_ok=True)
            present = sorted(p.name for p in src.iterdir())
            if present != sorted(files):
                raise SystemExit(
                    f"public inventory mismatch for {tree}: {present} != {sorted(files)}"
                )
            for name in files:
                data = (src / name).read_bytes()
                (dst / name).write_bytes(data)
                index[f"{tree}/{name}"] = hashlib.sha256(data).hexdigest()
        (public_root / "PUBLIC-INDEX.json").write_text(
            json.dumps({"sha256": index}, indent=1, sort_keys=True) + "\n", "utf-8"
        )
        return index


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(REPO / "01-source/config/experiment.yaml"))
    ap.add_argument(
        "--import-file",
        default=str(REPO / "01-source/generated/britannia-identity-access-import.yaml"),
    )
    ap.add_argument("--out", default=str(REPO / "06-evaluator/artifacts/synthworld"))
    ap.add_argument("--public", default=str(REPO / "02-synthworld-public"))
    ap.add_argument("--max-cells", type=int, default=None)
    args = ap.parse_args()

    config = yaml.safe_load(Path(args.config).read_text("utf-8"))
    root = Path(args.out)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    b = WorldBuilder(config, Path(args.import_file), root)
    b.compile_universe()
    b.compile_kernel()
    b.build_corpus(args.max_cells)
    b.build_rbac_truth()
    b.build_abac()
    b.build_rebac()
    b.compose_and_export()
    index = b.publish_public_copies(Path(args.public))

    b.stats["public_files"] = len(index)
    report = REPO / "06-evaluator/artifacts/world-build-stats.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(b.stats, indent=1, sort_keys=True) + "\n", "utf-8")
    print(json.dumps(b.stats, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
