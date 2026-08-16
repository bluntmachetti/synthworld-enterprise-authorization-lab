# Britannia Phase 2 — a Topaz authorization experiment on a released SynthWorld world

Compile `britannia_global_bank_topology.yaml` into a deterministic SynthWorld
enterprise identity/access world using only the released PyPI package
`idcognito-synthworld==0.15.0`, project the **public half** of that world into
Aserto Topaz, apply a real Rego policy, exercise Topaz's **authorization decision
API**, and score the decisions with SynthWorld's own benchmark scorers.

This phase tests **policy and authorization behaviour**. A successful directory
import is explicitly not the result — and in Topaz 0.33.16 it is not even evidence
of anything (see [`docs/limitations.md`](docs/limitations.md) §2).

---

## Ground rules this experiment was built under

- **Repository-independent, not documentation-only.** No local SynthWorld
  repository, editable install, source checkout, or unpublished API was used —
  everything came from the released wheel. But the public documentation was not
  sufficient to build against, so discovery read what the wheel itself ships:
  module source, pydantic schemas, function signatures, `__all__` exports, and the
  packaged reference bundles under `synthworld/benchmarks/`. That is legitimate for
  an outside consumer — it is all installed by `pip install` — but it is a weaker
  claim than "documentation only", and the gaps that forced it are enumerated in
  [`docs/limitations.md`](docs/limitations.md) §1.
- Where the released surface could not support a requirement, the gap is
  **documented**, not worked around with internals. There are 14 SynthWorld findings and 8 Topaz findings in
  [`docs/limitations.md`](docs/limitations.md).
- Container images pinned by immutable digest. Python dependencies pinned by hash.
  No `latest`.
- Nothing outside this directory is required except the supplied topology.

**Installed package, verified:**

| | |
|---|---|
| Distribution | `idcognito-synthworld==0.15.0` |
| Wheel SHA-256 | `f1b17f8254521d307e38cfc3a44d00844308dd36c7972da00b816b92e257ee60` |
| sdist SHA-256 | `c278758e47c4545b46a9f234dab53163a0899440fd55684805104087b8ca9d8c` |
| Source topology SHA-256 | `29ea8dd155ceed277eedf3f7261f0ba6844ff5a3e6c5a9c70164ae78b80871d1` |
| Topaz image | `ghcr.io/aserto-dev/topaz:0.33.16@sha256:835868c04bdd7129127ea43642ffff7363d0bd26d5e1a37631fa881431054360` |
| Topaz version reported at runtime | `0.33.16` (commit `81b8405`) |

> The prompt referred to `britannia_global_topology.yaml`; the file supplied in this
> directory is `britannia_global_bank_topology.yaml`. That is the file used.

---

## Isolation boundary

Six physically separate zones. Full design and the rules about who may cross the
line: [`docs/isolation-design.md`](docs/isolation-design.md).

```
01-source/              supplied topology, experiment config, adapter output
02-synthworld-public/   SynthWorld PUBLIC artifacts only (13 files, digest-indexed)
03-topaz-input/         Topaz model, Rego policy, directory records, request corpus
04-topaz-results/       raw + normalized Topaz decisions
05-submission/          blinded submission + its pre-scoring digest
06-evaluator/           intact SynthWorld trees (public + evaluator) and scoring output
```

Only zone 2 feeds the Topaz side. Stages 30, 40 and 50 read nothing else; stage 50
raises `ISOLATION VIOLATION` if a path resolves inside `06-evaluator/`. The
submission digest is sealed in `05-submission/SUBMISSION-DIGEST.json` **before**
stage 60 opens any answer key, and stage 60 aborts if that digest has moved.

**What that does and does not prove.** Stage 20 writes zone 6 before Topaz ever
starts, so the answer key is sitting on the same filesystem, readable, while the
system under test runs. The seal proves the submission was **not modified after
finalization**; it cannot prove no evaluator file was read beforehand, and the path
guard is a same-process convention, not a sandbox. So the isolation here is
**disciplined, not enforced** — the honest claim is auditability, not
impossibility. Making it enforceable means running stages 30–50 in a container or
process that cannot mount `06-evaluator/` at all; that is a Phase 3 change, not
something this run demonstrates. Full treatment in
[`docs/isolation-design.md`](docs/isolation-design.md).

Zone 6 holds the *intact* SynthWorld trees because the released evaluator loaders
refuse to read an evaluator directory in isolation — each one re-loads the sibling
public tree and cross-checks digests and file inventory. Zone 2 is a verified
byte-identical copy of only the public half, and stage 80 proves it file by file.

---

## Reproduce it

> **Status: locally source-controlled and clean-clone verified; not yet
> independently published.** The frozen baseline contains the topology, source
> scripts, configuration, lockfile and maintained documentation. Deterministic
> generated artifacts, evaluator truth, Topaz state, local environments and raw
> discovery scratch notes are deliberately excluded. A published remote and an
> independent reproduction are still required before making an unqualified
> public reproducibility claim. See
> [`docs/limitations.md`](docs/limitations.md) §3.12.

### One command, from the unpacked directory

```bash
cd agent-auth-2
bin/run_all.sh
```

That performs clean setup, deterministic generation, public-artifact validation,
Topaz startup and readiness, model/policy install, directory load with read-back
verification, authorization execution, blinded submission finalization, isolated
scoring, visualization, the validation report, and teardown.

Add `--keep-up` to leave Topaz running afterwards.

### Or step by step

```bash
# 0. clean setup — pinned venv from the hash-locked manifest
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python --require-hashes -r requirements.lock

# 1. deterministic generation
.venv/bin/python bin/10_map_topology.py            # topology  -> SynthWorld import
.venv/bin/synthworld validate-enterprise-access \
    --input 01-source/generated/britannia-identity-access-import.yaml --json
.venv/bin/python bin/20_build_world.py             # world, corpus, overlays, truth

# 2. public artifact validation
cat 02-synthworld-public/PUBLIC-INDEX.json         # sha256 per public file

# 3. Topaz projection
.venv/bin/python bin/30_project_topaz.py           # model, policy, directory, requests

# 4. Topaz startup and readiness
bin/topaz_up.sh                                    # polls BOTH gateways for 200

# 5-7. model/policy install, directory load, authorization execution
.venv/bin/python bin/40_run_topaz.py

# 8. blinded submission finalization (records the digest)
.venv/bin/python bin/50_build_submission.py

# 9. isolated scoring (verifies the digest, then opens evaluator truth)
.venv/bin/python bin/60_score.py

# 10. visualization + validation
.venv/bin/python bin/70_visualize.py
.venv/bin/python bin/80_validate.py

# 11. clean teardown
bin/topaz_down.sh                                  # docker compose down -v
```

Determinism: rerunning stages 1–3 from the same topology and config reproduces
byte-identical artifacts. Ids are `uuid5` over `id_namespace_salt` plus logical
keys; the seed only resolves count/fraction selectors.

---

## What was built

### Topology → SynthWorld mapping

The source is a **service/vendor/infrastructure topology** — services, vendors,
teams, domains, dependencies, deployments, data flows. SynthWorld's enterprise
importer wants an **identity/access blueprint** — tenants, organisations, units,
populations, groups, roles, resource sets, access-atom rules. Bridging that is the
substance of the mapping, and every field is classified in
[`docs/topology-mapping-report.md`](docs/topology-mapping-report.md).

The load-bearing decisions:

| Topology | SynthWorld | Kind |
|---|---|---|
| `organisation.metadata.legal_entity_footprint` (uk, europe, americas, apac_mea) | 4 tenants + 1 vendor tenant | documented transformation |
| `organisation.regions` | tenant assignment key | documented transformation |
| `domains[]` (7) | division units, replicated per tenant | direct |
| `teams[]` (15) | team units, in every tenant they have a location in | direct |
| `team_locations[]` (36) | populations, `count = ceil(headcount/50)` | **lossy**, factor recorded |
| `services[]` (35) | resource sets; `service_type` → `TargetKind` | partly approximate |
| `service_ownerships[].ownership_type` | role ladder owner > operator > contributor | documented transformation |
| `service_dependencies[]` (104) | workload-account access atoms | documented transformation |
| `services[].data_classification` | — | **not representable**: `ResourceSetTemplateV1` has no classification field |
| `domains[].parent_domain` | — | **not representable**: null on all 7 rows |
| SLA / latency / cost / encryption / GDPR transfer fields | — | **not representable**: no construct |

A constraint discovered empirically and not documented anywhere in the released
package: **the importer forbids cross-tenant declarations of every kind**
(`cross_tenant_access_declaration`, `cross_tenant_membership`,
`cross_tenant_role_assignment`, `cross_tenant_role_grant`). The Britannia topology
contains 135 team-owns-service pairs and 49 service-to-service calls that genuinely
straddle two legal entities. They are preserved in
`01-source/generated/cross-boundary-pairs.json` and drive the cross-boundary case
class through the ABAC layer instead.

### The compiled world

| | |
|---|---:|
| tenants / organisations / units | 5 / 5 / 80 |
| principals (employee 159, workload 101, supplier 38) | 298 |
| accounts (workload 490, workforce 104, agent 3) | 597 |
| access subjects | 895 |
| authorization targets | 101 |
| permissions | 404 |
| access atoms | 3 174 |
| evaluation cells (the unit of scoring) | 3 209 |

### The authorization policy

Six case classes. The mechanism each one actually resolves through — which is not
always the mechanism its name suggests:

| class | cells | expected | denied by | in which decision |
|---|---:|---|---|---|
| same-tenant allow | 2 754 | allow | — | — |
| deny: missing role or relation | 143 | deny | RBAC derivation finds no path | `rbac_final` **and** `final` |
| deny: scope exceeded | 164 | deny | ABAC guard — admin-class action outside the owning unit | `final` only |
| deny: cross-tenant boundary | 63 | deny | ABAC guard — rule scoped to those 63 cells | `final` only |
| deny: wrong principal binding | 15 | deny | **RBAC derivation finds no path** — *not* the binding gate | `rbac_final` and `final` |
| temporal, post-expiry | 35 | deny | lifecycle gate at the later tick | `rbac_final` and `final` |
| temporal, pre-expiry | 35 | control | matched half of the temporal pair | — |

Two of those rows need reading carefully, and both are expanded in
[`docs/results.md`](docs/results.md) §7:

- **The binding class does not test binding.** The policy sets
  `binding_gate_pass := true` unconditionally, because the canonical binding is
  evaluator-only. All 15 cells were denied because the RBAC derivation found no
  path — their truth carries zero `effective_path_ids`. The gate never fired, in
  this class or any other.
- **The two ABAC classes are denied only in the composed decision**, which
  SynthWorld ships no scorer for. In the directory-RBAC family — the one that *is*
  scored — the truth for all 227 of those cells is `allow`, and the submission
  predicted `allow`. The per-class `rbac_truth_final_deny` field in the scoring
  report is 0 for both, which is how to see this directly.
- **The cross-tenant rule is partly tautological.** The released ABAC vocabulary
  has no negation (`same_tenant` is positive-only), so a cross-tenant deny can only
  be written by enumerating cell ids — and the published rule does exactly that: it
  names all 63, under an `action_class_is` predicate that is true for every class.
  Rego *does* derive `cross_tenant` independently from the published tenant facts
  and agrees on all 63, but that derived decision is a **cross-check only**. It is
  not an input to `abac_deny`, and therefore not what drives `final`.

The temporal pair is the *same access atom* evaluated at tick 100 and tick 200, so
the revocation transition is observable rather than asserted. Suspended accounts
deny at both ticks; expiring accounts flip. That is a genuine temporal test built
on `AccountObservationV1.valid_until_tick` and `administrative_state`, which the
released contract does support.

The Rego policy reconstructs the effective decision by walking the Topaz directory:
subject → group memberships → **transitive** group nesting → roles → **transitive**
role hierarchy → role grants, plus direct entitlements, plus — for account subjects
— the authority of the principal the directory believes the account belongs to.
None of that is a single stored tuple.

---

## Results

Full breakdown in [`docs/results.md`](docs/results.md). Headline:

| | |
|---|---|
| Directory loaded and **verified by read-back** | 1 699 objects / 5 879 relations, all 8 types and 25 tuple shapes matching, 0 HTTP errors |
| Authorization decisions | 3 209 `POST /api/v2/authz/is`, seven decisions each |
| `rbac.effective_decision_accuracy` | **1.0000** (n=3 209) |
| `rbac.rbac_decision_accuracy` | **1.0000** (n=3 209) |
| `rbac.authorized_role_exact_match_rate` | **1.0000** (n=895) |
| `abac.abac_decision_accuracy` | **1.0000** (n=3 209) |
| `birthright.birthright_decision_accuracy` | **1.0000** (n=3 209) |
| Every one of the six case classes | 1.0000 on `effective` and on `rbac_final` — **both are directory-RBAC-family decisions**; the composed decision has no scorer |
| Validation | **32/32 checks pass** |

Submission sealed at `89099e3b5522…5a69f05` before any evaluator artifact was
opened; stage 60 re-verified it and would have aborted on drift.

Five metrics are reported separately as **not publicly winnable** (`intended`,
derivation paths, ABAC predicate ids, and both SoD metrics), two as **mechanisms
not exercised** (ReBAC), five as **world properties, not scores**, and six have a
zero denominator. See `docs/results.md` §5 and §7 — in particular, the binding gate
was **not tested at all**: the policy concedes it (`binding_gate_pass := true`) and
all 15 mismatch cells were already deny with no derivation path, so nothing in this
run exercises it.

Machine-readable outputs:

| Output | Path |
|---|---|
| Scoring report | `06-evaluator/scoring/scoring-report.json` |
| Validation report | `reports/validation-report.json` |
| Raw Topaz decisions | `04-topaz-results/raw/decisions.jsonl` |
| Blinded submission + seal | `05-submission/` |
| Public artifact digests | `02-synthworld-public/PUBLIC-INDEX.json` |
| HTML view | `viz/britannia-world.html` |

---

## Reading the scores honestly

The released scorers **deliberately emit no aggregate**, and the package ships no
scorer for the composed multi-mechanism decision at all. This experiment invents
neither. The scoring report separates three things that are easy to conflate:

- `scored_metrics` — genuine measurements of the policy.
- `not_publicly_winnable` — `intended_decision`, `effective_path_ids`, and the
  account binding gate. None is derivable from any public artifact, so these
  measure information limits, not policy quality.
- `world_property_metrics_not_scores` — five metrics (`sprawl.*`,
  `birthright_breadth.*`, `redundancy.*`, `accumulation.*`) that the released
  scorer computes from truth alone and that ignore the submission entirely.
  Verified by degrading a prediction and observing they do not move.

A fourth thing is easy to conflate and is worth stating on its own: **nothing in
the scoring report scores the composed decision.** `per_case_class` reports
`effective_accuracy` and `rbac_final_accuracy`, both from the directory-RBAC
family, and carries `composed_decision_scored: false` on every class. The composed
`final` — the one the ABAC guard participates in, and the one an authorization
system actually returns — appears only descriptively, in `docs/results.md` §4 and
in `04-topaz-results/`. That is a gap in the released package (`docs/limitations.md`
§1.1), not a choice made here, but it means the 1.0000 on `deny: cross-tenant
boundary` and `deny: scope exceeded` is a score on an **allow**.

---

## Visualization

`viz/britannia-world.html` is built by `bin/70_visualize.py` from public artifacts
only and is labelled:

> **External experiment visualization — not a SynthWorld renderer**

SynthWorld 0.15.0 ships **no** generic enterprise-world renderer and no HTML
command. `synthworld.explorer` exports exactly one projector,
`project_asteria_agent_authority_v1`, which takes an `AgenticPublicBundle` and is
specific to the Asteria agentic world. Presenting it as a renderer for the
Britannia enterprise world would be false, so this view is experiment-owned. Stage
80 greps the rendered file for evaluator vocabulary and fails the run if any
appears.

---

## Repository layout

```
britannia_global_bank_topology.yaml   the supplied source (never modified)
requirements.lock                     hash-pinned Python dependencies
bin/                                  stage scripts, in execution order
  10_map_topology.py                  topology -> SynthWorld import (+ mapping ledger)
  20_build_world.py                   world, corpus, overlays, truth  [GENERATOR]
  30_project_topaz.py                 public artifacts -> Topaz model/policy/data
  40_run_topaz.py                     load, verify, decide
  50_build_submission.py              blinded submission + digest seal
  60_score.py                         the only stage that opens evaluator truth
  70_visualize.py                     public-only HTML view
  80_validate.py                      counts + integrity checks, exits non-zero on failure
  topaz_up.sh / topaz_down.sh         pinned stack lifecycle
  run_all.sh                          full reproduction
infra/                                pinned compose, Topaz config, policy bundle
  VERIFICATION.md                     verbatim proof the stack works
docs/                                 mapping report, isolation design, limitations,
                                      phase 1 contrast, results
```

## Related documents

- [`docs/topology-mapping-report.md`](docs/topology-mapping-report.md) — field-by-field mapping
- [`docs/isolation-design.md`](docs/isolation-design.md) — the public/evaluator boundary
- [`docs/limitations.md`](docs/limitations.md) — SynthWorld and Topaz API/doc gaps
- [`docs/phase1-vs-phase2.md`](docs/phase1-vs-phase2.md) — what this tests that the tuple round-trip did not
- `03-topaz-input/MAPPING.md` — generated during stage 30: public artifact → Topaz construct mapping
- [`infra/VERIFICATION.md`](infra/VERIFICATION.md) — verified Topaz stack behaviour

## Discovery notes

Raw discovery notes are not part of the frozen baseline. They contained paths to
temporary probes and a machine-readable companion that were not retained, so they
were unsuitable as publishable evidence. The maintained documents above record
the findings that affect the experiment, and the executable scripts are the
canonical account of the released-package and Topaz integration.
