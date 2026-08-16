# Phase 1 vs Phase 2 — what this phase tests that the tuple round-trip did not

Phase 1 lives at `~/Projects/agent-auth`. It was read only, never executed or
modified. Every Phase 1 claim below is quoted from its own files.

## The short version

Phase 1 proved that **Topaz's directory stores and returns the tuples you write
into it**. Phase 2 tests whether **a real authorization policy, given only the
public half of a generated world, can derive decisions that were never written
down** — and scores those decisions against an answer key it never saw.

Phase 1's headline result was `accuracy: 1.0` over 6 880 checks. That number is
tautological, and Phase 1's own code shows why.

## Why Phase 1's 1.0000 could not have been anything else

Three facts from the Phase 1 tree, together, make the result unfalsifiable:

1. **Every permission was a one-to-one alias of a single directly-written
   relation.** From `topaz/model/manifest.yaml`:

   ```yaml
   permissions:
     can_read: read
     can_write: write
     can_operate: operate
     can_integrate: integrate
     can_administer: administer
   ```

   No unions, no arrow/inherited permissions, no computed relations. A `can_operate`
   check succeeds exactly when the `operate` tuple exists.

2. **One relation was written per compiled access atom**, from
   `src/build_topaz_directory.py`:

   ```python
   for a in u["access_atoms"]:
       sid, act, tid = a["subject_id"], a["action"], a["authorization_target_id"]
       rel("resource", tid, act, tp(sid), sid)
       allow.add((sid, act, tid))
   ```

3. **The expected answer was computed from that same in-memory set**:

   ```python
   "expected": (sid, act, tid) in allow,
   ```

The oracle and the loaded data have one source. No Phase 1 assertion depends on
Topaz deriving anything. The 139 structural tuples it loaded
(`organisation.parent`, `unit.member`, `group.owner`, `role.owner`, …) are
referenced by no permission at all — Phase 1's own manifest comment calls them
`# --- structural / org backbone (context for the graph & console) ---`.

## No policy was evaluated in Phase 1

- `topaz/policy/` is an **empty directory**. There is no `.rego` file anywhere in
  the Phase 1 tree.
- `topaz/config/local.yaml` disables bundles outright: `local_bundles: paths: []`.
- The **Authorizer service is not configured at all** — `api.services` declares
  only `console`, `reader`, `writer`, `model`, `exporter`, `importer`. So
  `/api/v2/authz/*` was not even reachable.
- The complete set of endpoints Phase 1 touched:
  `/api/v3/directory/manifest`, `/api/v3/directory/object`,
  `/api/v3/directory/relation`, `/api/v3/directory/check`. All four are Directory
  APIs.

## Side by side

| | Phase 1 | Phase 2 |
|---|---|---|
| Topaz endpoint | `/api/v3/directory/check` (Directory) | `/api/v2/authz/is` (**Authorizer**) |
| Authorizer service | not configured | configured; readiness polled on `/api/v2/policies` |
| Rego policy | none — empty dir, `paths: []` | real policy; compilation proven by a non-empty `ast` in `GET /api/v2/policies` |
| Decision depth | 1 hop (permission = one written relation) | multi-hop: subject → groups → **transitive** group nesting → roles → **transitive** role hierarchy → grants, plus account→principal binding |
| Structural tuples | 139 loaded, used by **no** permission | used by the derivation itself |
| Decisions per query | 1 boolean | 4 (`birthright`, `intended`, `effective`, `final`) plus ABAC and ReBAC mechanism outcomes |
| Actions exercised | 2 of 5 declared (`write` and `administer` were **never queried** — a latent loop bug) | all 4 declared actions |
| Oracle | the same in-memory `allow` set that produced the writes | SynthWorld evaluator truth, generated independently of the policy |
| Blinding | none needed — no independent truth existed | submission SHA-256 sealed before any evaluator file is opened; scoring aborts on drift |
| Scorer | bespoke accuracy/precision/recall in the repo | released `evaluate_enterprise_directory_rbac`, `evaluate_enterprise_abac`, `evaluate_enterprise_rebac` |
| Topaz image | `ghcr.io/aserto-dev/topaz:latest`, **unpinned** — the version that produced the score is unrecoverable | `0.33.16@sha256:835868c0…54360`, index digest, reproducible on amd64 and arm64 |
| Negative cases | combinatorial complement of what was written | six engineered classes, each denied by a *named mechanism* |

## What Phase 2 adds that is genuinely new

1. **A policy that can be wrong.** The Rego policy must reconstruct the effective
   decision by walking the directory graph — transitive group nesting, transitive
   role hierarchy, role grants, direct entitlements, and the account→principal
   binding. None of that is a single stored tuple. A bug in the traversal shows up
   as a wrong decision.

2. **An independent oracle.** The truth is compiled by SynthWorld from an intent
   overlay and a canonical binding the Topaz side never receives. The submission is
   digest-sealed before scoring. Phase 1 could not do this because it had no
   independent truth to withhold.

3. **Six denial classes, each attributable to a mechanism** — with the attribution
   traced rather than assumed, which is how two of the six turned out not to hold:

   | class | cells | outcome | denied by | in which decision |
   |---|---:|---|---|---|
   | same-tenant allow | 2 754 | allow (100%) | — | — |
   | missing role or relation | 143 | deny (100%) | RBAC derivation finds no path | `rbac_final`, `final` |
   | scope exceeded | 164 | deny (100%) | ABAC guard, admin-class action outside the owning unit | `final` only — **unscored** |
   | cross-tenant boundary | 63 | deny (100%) | ABAC guard, rule scoped to those 63 cell ids | `final` only — **unscored** |
   | wrong principal binding | 15 | deny (100%) | **RBAC derivation finds no path**, not the binding gate | `rbac_final`, `final` |
   | temporal, post-expiry | 35 | deny (100%) | lifecycle gate at the later tick | `rbac_final`, `final` |
   | temporal, pre-expiry | 35 | allow 8 / deny 27 | the matched control half | — |

   The temporal pair is the same access atom evaluated at two ticks, so the
   transition itself is observable rather than asserted.

   The two corrections in that table are Phase 2 findings in their own right, and
   both are expanded in `docs/results.md` §7:
   - The binding class is decided by the missing derivation. The gate is conceded
     (`binding_gate_pass := true`) and never fires; all 15 cells carry zero
     `effective_path_ids` in truth.
   - The two ABAC classes deny only in the composed decision, and SynthWorld ships
     no scorer for it. In the family that *is* scored, their truth is `allow`.

4. **Runtime gates that override the graph.** `final_decision` differs from
   `effective_decision` only when an account's binding or lifecycle fails. Phase 1
   had no concept of a decision being overturned at runtime.

5. **Reproducibility that survives the run.** Phase 1's `topaz:latest` means its
   score cannot be reproduced — the binary that produced it is not identified.
   Phase 2 pins the image by index digest and the Python dependencies by hash, and a
   clean run reproduces the submission digest byte for byte. That is reproducibility
   *of the run*; it is not yet reproducibility *by a third party*, since the
   directory is unpublished and not under version control.

## What Phase 2 still does not prove

Stated here so the contrast is not overclaimed:

- It does not prove Topaz is correct in general. It proves this policy, over this
  directory, reproduces this world's decisions.
- `intended_decision` is not derivable from public artifacts, so that metric
  measures world drift, not policy quality. See `docs/limitations.md`.
- The account binding gate is not publicly checkable, so the policy cannot detect a
  mismatched binding and takes the loss on that cohort by design. The loss was zero
  here only because those cells were already denied by RBAC, so **the gate is
  untested, not validated**.
- The composed decision — the one the ABAC guard participates in — is produced on
  all 3 209 cells but scored by nothing, because the released package has no scorer
  for it. 227 ABAC downgrades are reported and never measured.
- The isolation is audited discipline, not an enforced boundary: the evaluator tree
  is written before Topaz starts and stays readable throughout. See
  `docs/isolation-design.md`.
- Reproducibility is demonstrated on the machine that built it. This directory is
  not a Git repository and has never been published, so independent reproduction has
  not been demonstrated.
- Phase 1's field-coverage work (`docs/UNREPRESENTABLE_FIELDS.md`) and Phase 2's
  mapping report cover the same topology; Phase 2's mapping is different in
  structure (it must satisfy the importer's single-tenant constraint), not
  necessarily more complete in coverage.
