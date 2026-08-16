# Limitations, and gaps in the released SynthWorld API and documentation

Everything here was found by consuming the released wheel
`idcognito-synthworld==0.15.0` as an outside consumer. No local SynthWorld
repository, editable install, source checkout, or unpublished API was used.

The released *documentation* was not sufficient on its own — the gaps below are
why — so discovery also read what the wheel ships: module source, pydantic
schemas, function signatures, `__all__` exports, and the packaged reference
bundles under `synthworld/benchmarks/`. Everything consulted arrives with
`pip install`. See §3.13 for why that distinction is worth stating. Where a
requirement could not be met from the released surface, it is recorded as a gap
rather than worked around.

---

## 1. Gaps in the released SynthWorld public API

### 1.1 There is no scorer for the composed authorization decision

`compile_enterprise_access_state` produces `CompiledEnterpriseAccessStateV1` — the
per-cell composition of RBAC, ABAC and ReBAC into `effective_decision`,
`final_decision`, `reconciliation` and `policy_conflicts`. That is the decision an
authorization system actually makes.

**No prediction model and no `evaluate_*` function exists for it.** The released
scorers are per-mechanism only: `evaluate_enterprise_directory_rbac`,
`evaluate_enterprise_abac`, `evaluate_enterprise_rebac`. So the composed decision —
the thing the `rbac_with_abac_guard` profile exists to express — can be compiled
and inspected but not scored.

*Consequence for this experiment:* the submission carries three separate
per-mechanism predictions. The composed decision is reported descriptively from
the raw Topaz results and never presented as a score.

This has a sharper edge than it first appears, and it is easy to miss when reading
the per-case-class table. Those rows are scored against
`DirectoryRbacCellTruthV1.final_decision`, which is `effective` gated by binding and
lifecycle **only**. So for the two classes whose deny comes from the ABAC guard —
`deny-scope-exceeded` (164) and `deny-cross-tenant-boundary` (63) — the RBAC-family
truth is `allow`, the submission predicted `allow`, and the 1.0000 is a correct
prediction of an allow. The deny those classes are named for exists only in the
composed decision, which nothing scores. The scoring report now carries
`rbac_truth_final_deny` per class and `composed_decision_scored: false` so this is
visible in the artifact rather than only in prose.

### 1.2 No public digest helper, so every overlay requires a disk round-trip

Almost every operator-input model has a required `SyntheticDigestV1` field
(`identity_access_universe_digest`, `evaluation_corpus_digest`, …), and the digest
must be exactly `synthetic_digest(canonical_json_bytes(model))`. Both helpers, and
`SyntheticDigestV1` itself, live in `synthworld.enterprise.canonical` and are **not
re-exported** from `synthworld.enterprise.__all__`.

The only public route is to export the artifact to disk and read the digest back
out of the exporter's `manifest.json`. That is what `bin/20_build_world.py` does.
It means **you cannot construct any overlay in memory without first writing files**.

### 1.3 Strict mode plus unexported enums makes Python construction impossible

`EnterpriseOperatorModel` sets `ConfigDict(extra="forbid", frozen=True, strict=True)`.
Under strict mode a `list` is rejected where `tuple[...]` is declared, and a `str`
is rejected where a `StrEnum` is declared. But **none of the enums and none of the
nested record types are exported** — not `PrincipalKind`, not `RuleEffect`, not
`AccessEvaluationCellTemplateV1`, not `AbacRuleV1`, not the prediction item types
(`DirectoryRbacCellPredictionV1`, `AbacCellPredictionV1`, `RebacCellPredictionV1`).

So a strictly-public consumer cannot obtain the enum instances that strict
construction demands. The only working path is
`Model.model_validate_json(json.dumps(document))`, which coerces strings to enums
and arrays to tuples. That works, but it means authoring with **magic string
literals for which no public vocabulary is published** — you have to read the
shipped source to learn that `target_kind` is `"access_cell"`/`"activation_request"`,
that profiles are `"rbac_with_abac_guard"`, and so on.

### 1.4 No public logical-key → compiled-identifier index

The compiled universe is deliberately opaque: ids are UUIDs and `display_label` is
anonymised (`"Example Authorization Target 000085"`). That is correct for a
product-safe projection. But **the released API exposes no way to map a blueprint
logical key to the identifier it compiled to.**
`EnterpriseIdentityAccessCompileResultV1` carries only `public_universe` and
`evaluator_canonical_binding_truth`. `stable_enterprise_id` exists in
`synthworld.enterprise.canonical` but requires the internal namespace constants and
key-component conventions, which are not published — reconstructing them would be
reverse-engineering internals, so it was not attempted.

*Consequence:* the experiment cannot correlate a compiled artifact back to
`payments-orchestration-hub`. Everything downstream — the Topaz projection, the
case selection, the HTML view — is built from **structure only** (tenant, unit,
owner unit, target kind, actions, atoms). This turned out to strengthen the
isolation guarantee, but it is a real gap for anyone who needs traceability.

A related consequence: **role semantics are not recoverable from the universe
alone.** The only public route from a role id to what it means is to compile the
RBAC kernel first and join `kernel.role_grants` to `universe.permissions`. That
inverts the natural step order, because the evaluation corpus needs role ids.

### 1.5 Cross-tenant access cannot be declared at all

Empirically confirmed against the released validator with a minimal two-tenant
blueprint. Every relation type is blocked:

| declaration | diagnostic |
|---|---|
| access atom rule spanning tenants | `cross_tenant_access_declaration` |
| account allocation spanning tenants | `cross_tenant_access_declaration` |
| group membership spanning tenants | `cross_tenant_membership` |
| role assignment spanning tenants | `cross_tenant_role_assignment` |
| role grant spanning tenants | `cross_tenant_role_grant` |

This is not documented in the scaffold, in `--help`, or in the PyPI README.

*Consequence:* the Britannia topology contains **135 team-owns-service pairs and 49
service-to-service calls that genuinely straddle two legal entities**. None can be
declared. They are captured in
`01-source/generated/cross-boundary-pairs.json` and are the empirical motivation
for the cross-boundary case class, which is expressed through the ABAC layer
instead (see §3.3).

### 1.6 Undocumented input constraints

- **`id_namespace_salt` must be 64 lowercase hex characters.** Violating it yields
  `id_namespace_salt_invalid` with the unhelpful hint "Match the independently
  versioned v1 component schema." The scaffold emits a conforming value but never
  states the rule.
- **YAML anchors and aliases are rejected** (`yaml_alias_forbidden`, "Use the
  restricted JSON-compatible YAML subset"). PyYAML emits an alias whenever the same
  list object is referenced twice, which happens naturally when many resource sets
  share one action list. Not documented.
- **A team holding two ownership roles on one service** produces a duplicate
  `(subject, target, action)` and fails with `duplicate_access_atom_declaration`.
  The adapter deduplicates by seniority.
- **Exporters refuse to write into an existing root** (`enterprise artifact root
  must not already exist`), so every stage must clear its output tree first.

### 1.7 The compiler does not preserve declared cell order

`compile_enterprise_evaluation_corpus` returns cells in a different order from the
config, and `cell_id` is `uuid5` over a namespace constant that is not public. So
neither positional zip nor re-derivation is a safe way to map a `cell_key` to a
`cell_id`. This caused a real bug during the build: ABAC rules were attached to the
wrong cells, which showed up as 194 wrongly-denied cells in the allow class.

The safe public mapping is the cell's own tuple —
`(access_atom_id, context_id, session_state_id, tick)` — which the compiler
guarantees unique via `duplicate_evaluation_cell_tuple`.

### 1.8 ABAC and ReBAC are documented as optional but are mandatory

`compose_enterprise_authorization` and `compile_enterprise_access_state` both accept
`abac_truth=None` and `rebac_truth=None`. But `export_enterprise_authorization`
requires all six public and three evaluator payloads, and
`load_evaluator_enterprise_authorization` raises if
`composition.abac is None or composition.rebac is None`. **An RBAC-only benchmark is
compilable but not shippable.**

### 1.9 The CLI stops after three steps

`scaffold-enterprise-access`, `validate-enterprise-access` and
`compile-enterprise-access` exist. Corpus compilation, the RBAC kernel, B/I/E/F
truth, ABAC, ReBAC, composition, access state, artifact export and **all scoring**
are Python-API only. `synthworld evaluate` exposes ten tasks and none of them
accepts enterprise identity/access authorization predictions — the two
`enterprise-*` tasks dispatch to the unrelated agentic JSONL-trace subsystem.

### 1.10 The Explorer has no generic enterprise renderer

`synthworld.explorer.__all__` exports exactly one projector:
`project_asteria_agent_authority_v1(public: AgenticPublicBundle, *, public_artifact_set_digest: str)`.
It takes an `AgenticPublicBundle` and is specific to the Asteria agentic world.
There is **no HTML command anywhere in the CLI** and no projector that accepts an
`EnterpriseIdentityAccessUniverseV1`.

*Consequence:* the HTML view in `viz/` is entirely experiment-owned and is labelled
**"External experiment visualization — not a SynthWorld renderer"**. Presenting the
Asteria projector as a generic renderer for the Britannia world would be false.

### 1.11 The ABAC predicate vocabulary has no negation

`SameTenantV1` is a **positive** predicate. There is no `not`, no
`different_tenant`, and no rule-level negation operator (`FlatRuleOperator` is
`all` | `any` only). So "deny unless the subject and resource share a tenant" —
the single most obvious boundary control — **cannot be written as a predicate at
all.** A cross-tenant deny rule can only be expressed by enumerating the offending
`cell_ids`.

That makes the published rule tautological with respect to its own scope: it denies
the cells it was told to deny. Concretely, the compiled `abac-deny-cross-tenant`
rule carries `cell_ids` listing all 63 affected cells and one predicate,
`action_class_is: [admin, execute, read, write]`, under operator `any` — which
holds for every cell in the scope. Nothing about tenancy is evaluated.

This experiment mitigates but does not fix that. The Rego policy *also* derives the
tenant comparison independently from the published attribute facts and exposes it
as its own decision (`cross_tenant`), and the two agree on all 63 cells. That is
worth having — it shows the boundary condition is computable from public facts and
that the published scope is right. But it is a **cross-check running beside the
decision, not inside it**: `abac_deny` iterates the rules in scope, and `final` is
`rbac_final ∧ ¬abac_deny`. Neither consults `cross_tenant`. Deleting the
`cross_tenant` rule would change no decision. The agreement is evidence supplied by
the experiment, not enforcement supplied by the contract.

### 1.12 Prediction identifiers are evaluator-side, so two dimensions are unsubmittable

- `AbacPredicatePredictionV1` is keyed by `truth_id`, which is minted inside the
  compiled ABAC truth. The predicate *outcomes* are fully derivable from the public
  facts, but the identifiers needed to submit them exist only in the evaluator
  tree, so `abac.predicate_outcome_accuracy` cannot be won by any public consumer.
- `DirectoryRbacCellPredictionV1.effective_path_ids` has the same problem for
  `rbac.rbac_derivation_path_exact_match_rate`.

In both cases the information is knowable and the identifier is not.

### 1.13 SoD constraints are policy but are shipped as truth

`ssd_constraints` and `dsd_constraints` are declared on
`EnterpriseDirectoryRbacIntentOverlayV1`, which is exported to neither the public
nor the evaluator tree. They are *policy* — which roles must not be held together —
yet a consumer is scored on detecting violations of constraints it is never told.
`ssd.ssd_violation_detection_rate` is therefore unwinnable, and the companion
`ssd_violation_false_positive_rate` reads as a perfect 0.0 for the trivial reason
that nothing was submitted.

### 1.14 Other surface defects

- `EnterpriseAuthorizationPublicArtifactsV1` / `EnterpriseAuthorizationEvaluatorArtifactsV1`
  are the required argument shapes of the exported `export_enterprise_authorization`,
  yet are absent from `synthworld.enterprise.__all__`.
- `perfect_enterprise_directory_rbac_prediction` — the obvious smoke-test oracle —
  is likewise not re-exported at top level.
- `EnterpriseIdentityAccessImportLimitsV1` and `EnterpriseAbacCompileLimitsV1` are
  parameters of six public functions but are not public names.
- No accessor exists for a compiled artifact's *own* canonical digest, which is
  what downstream overlays require — hence §1.2's disk round-trip.
- **The seed is low-entropy.** Ids are `uuid5` over `id_namespace_salt` plus logical
  keys, not over the seed. The seed only resolves `CountSelectorV1` /
  `FractionSelectorV1`. Two different seeds frequently produce identical universes.

---

## 2. Gaps and traps in Topaz 0.33.16

Verified against a live pinned container.

- **`topaz directory import` silently drops every relation.** Exit code 0, no
  stderr, progress line still prints, and afterwards `/relations` returns
  `{"results":[]}`. This is the single most important operational finding, and it
  means *a successful directory import is not evidence of anything*. Root causes in
  the shipped client: `import.go` requires exactly one top-level key per file and
  silently skips combined files; `-f` is not repeatable and silently uses only the
  last value; the JSONL path tries `Unmarshal(line, &Object{})` first and relation
  JSON does not reliably error; and the client's `recv()` discards
  `ImportResponse_Status`, so server-side rejections never surface.
  *This experiment loads every record over `POST /api/v3/directory/relation` and
  verifies counts by read-back before making any decision.*
- **There is no REST bulk-import endpoint.** `/api/v3/directory/import` returns 404;
  the importer is gRPC-only (bidirectional streaming), which grpc-gateway does not
  expose.
- **`insecure` defaults to `true` and is mutually exclusive with `no_tls`.** You
  must write `insecure: false` *explicitly* alongside `no_tls: true`, or the
  container refuses to boot.
- **The container exits silently on a config error**, after a clean-looking
  shutdown sequence. `docker compose ps` shows nothing; the real error is the last
  log line.
- **Port 9494 is gRPC health, not HTTP**, and the image ships no `curl`,
  `grpcurl` or `grpc-health-probe`, so a container-internal healthcheck is
  impractical. Readiness is polled from the host on both REST gateways.
- **`PUT /api/v3/directory/manifest` returns 501.** Use `POST`.
- **The negative `context.reason` from `/api/v3/directory/check` is misleading** —
  it reports `object not found` when the real cause is a missing relation.
- **`page.size` on `/api/v3/directory/relations` silently returns zero rows when
  set too high.** `page.size=1000` yields `{"results": []}` with no error and no
  `page.next_token`, which reads exactly like "there are no relations". `page.size=100`
  works and pages correctly via `next_token` (597 rows over 6 pages here). A caller
  that trusts a single large page will silently conclude the directory is empty —
  the same failure mode as the CLI importer, and the second place in this version
  where an empty result masquerades as success.

---

## 3. Limitations of this experiment

### 3.1 Three dimensions are not winnable from public artifacts

Reported in a separate `not_publicly_winnable` block in the scoring report rather
than folded into headline numbers:

- **`intended_decision`.** The RBAC intent overlay is an experiment-owned input and
  is exported to neither the public nor the evaluator tree. The submission predicts
  `intended == effective`, so this metric measures declared-vs-intended drift in the
  generated world, not policy accuracy.
- **`effective_path_ids`.** Internal SynthWorld derivation-path identifiers that
  appear in no public artifact. Submitted empty, so
  `rbac_derivation_path_exact_match_rate` cannot exceed the empty-path rate.
- **The account binding gate.** A consumer sees the *observed* binding but has
  nothing to compare it to; the canonical binding is evaluator-only. The policy does
  not guess and accepts the loss on the mismatched cohort.

  The concession cost nothing here, and that is itself a finding rather than a
  result: the `deny-wrong-principal-binding` class scored 1.0000, but all 15 of its
  cells carry zero `effective_path_ids` in truth, so the RBAC derivation had already
  denied them before any gate ran. `binding_gate_pass := true` means the gate never
  fires anywhere in this run — deleting it from the policy would change no decision.
  **The class does not test what it is named for**, and no case in this corpus does.
  A real test needs a mis-bound account whose observed principal holds authority the
  canonical one does not; constructing one is possible (stage 20 authors the wrong
  bindings and could target them at authority-bearing principals) but was not done.

### 3.2 Four of the nineteen RBAC metrics are not scores

`sprawl.effective_outside_intent_rate`, `sprawl.missing_intended_access_rate`,
`birthright_breadth.effective_outside_birthright_rate`,
`redundancy.redundant_derivation_cell_rate` and
`accumulation.privilege_accumulation_subject_rate` are computed from `truth` alone
and ignore the submission entirely. Verified by degrading a prediction and observing
they do not move. They describe the generated world. The scoring report segregates
them under `world_property_metrics_not_scores`.

### 3.3 The cross-boundary case is expressed through ABAC, not through declarations

Because §1.5 forbids declaring cross-tenant access, the cross-boundary denial is
asserted as a per-cell ABAC fact (`resource_tenant_id` naming a different real
tenant). ABAC facts are cell-scoped assertions about the decision context and their
values are validated for existence only, so this is the mechanism the released
contract provides. It is a faithful model of a request served by a deployment
outside the subject's legal entity — but it is **not** the same thing as a
cross-tenant edge existing in the directory, and should not be read as such.

Two further qualifications, both consequences of §1.11:

- **The deny rule is not guarded by `same_tenant`.** It cannot be: `same_tenant` is
  positive-only, so it appears on the *allow* rule (2 982 cells) instead. The
  cross-tenant deny rule enumerates its 63 cell ids and carries a single
  `action_class_is` predicate listing all four action classes, under operator
  `any` — a predicate true for every cell in its own scope. The rule is therefore
  **decided entirely by its scope**, and evaluating it can return nothing else.
- **The independent check does not drive the decision.** The Rego policy derives
  `cross_tenant` from the published tenant facts and agrees with the rule scope on
  all 63 cells, which is real evidence that the boundary condition is computable
  from public facts and that the scope is correct. But `cross_tenant` is emitted as
  its own decision; `abac_deny` and `final` do not consult it. The PDP under test
  enforces the enumeration, and the experiment supplies the check alongside.

### 3.4 Population counts are scaled

`team_locations[].headcount_in_region` sums to 7 150 real staff. Compiling one
principal per head produces a directory too large to load and score in a single
reproducible run, so counts are divided by 50 (ceiling, minimum 1), giving 298
principals. The original headcounts are preserved verbatim in the mapping report,
and setting `scaling.population_divisor: 1` in `01-source/config/experiment.yaml`
reproduces the full-scale world.

### 3.5 Session, activation and dynamic-SoD dimensions are declared but not exercised

The corpus declares no `session_slots` and no `role_activation_requests`, so
`activation_decision_accuracy`, `activated_role_exact_match_rate`, the two
`activation_safety` metrics and `dsd_constraint_outcome_accuracy` all have a zero
denominator and report `null`. Static SoD constraints *are* declared (derived from
the topology's three-lines-of-defence structure). Exercising activation would
require modelling just-in-time role elevation, which the source topology does not
describe; inventing it would not be grounded in the supplied data.

### 3.7 A designed clearance model could not be built

`services[].data_classification` (internal / confidential / restricted) maps 1:1 onto
SynthWorld's `InformationClassification`, and the ABAC layer has
`ResourceClassificationFactV1`, `SubjectClearanceFactV1` and a
`classification_within_clearance` predicate. But **`ResourceSetTemplateV1` has no
classification field**, so the value cannot cross the blueprint boundary into the
compiled universe, and stage 20 builds the ABAC facts from the compiled universe
alone. The clearance model in `01-source/config/experiment.yaml` is therefore
recorded as designed-but-not-realised, and the field is classified
`not_representable`.

This one is worth flagging because of how it was caught: the mapping report's own
coverage audit found that the ledger *claimed* the mapping while the built artifacts
contained no such fact. The adapter was corrected rather than the claim retained. The
audit trail is preserved in `docs/topology-mapping-report.md` §3.3.

### 3.8 The mapping ledger is coarser than the topology in places

The ledger names 100 field paths; a recursive walk of the topology yields 150. No leaf
is unaccounted for, but 40 leaves are covered only *collectively* by a coarser ancestor
row (`vendors[].metadata`, `organisation.metadata.regulatory_structure`,
`vendors[].ownership_structure` and similar). A blanket row asserts that none of the
object's sub-keys is used; that assertion is true here and was verified independently,
but the ledger does not itself prove it, and a future edit that started consuming one of
those sub-keys would not change a single ledger row. `Ledger.note()` should be called
per leaf for those container rows.

### 3.9 What the result does and does not establish

It establishes that this Rego policy, over this directory, reproduces this world's
per-mechanism decisions to the measured accuracy. It does not establish that Topaz
is correct in general, that the policy would generalise to another world, or that
the Britannia topology is representative of a real bank.

### 3.10 The composed decision is exercised but not measured

Restating §1.1 as a limitation of this experiment rather than of the package,
because it bounds what the headline numbers mean. Topaz produces the composed
decision on every one of the 3 209 cells and the ABAC guard downgrades 227 of them.
**None of those 227 downgrades is compared to truth by anything.** The ABAC scorer
measures the guard's per-cell verdict; the RBAC scorer measures a decision the
guard is not part of; no scorer joins them. The composed column in
`docs/results.md` §4 is descriptive, and the honest reading of the per-case-class
table is "the directory-RBAC family was reproduced exactly", not "every case class
was decided correctly".

### 3.11 Isolation is disciplined, not enforced

The evaluator tree is written by stage 20, before Topaz starts. It therefore sits
on the same filesystem, readable by the same user, for the entire run of the system
under test. Three mechanisms give the isolation claim its weight, and each has a
precise limit:

| mechanism | proves | does not prove |
|---|---|---|
| digest seal (`SUBMISSION-DIGEST.json`) | the submission was not modified after finalization | that no evaluator file was read before finalization |
| `ISOLATION VIOLATION` path guard in stage 50 | that stage's own path resolutions stay out of zone 6 | anything about stages 30/40, or about reads by any other means |
| stage 80 leak scan | no evaluator vocabulary reached the HTML view | that no evaluator value influenced a decision |

The `"evaluator_artifacts_read": false` field in the seal is an **assertion by the
stage that writes it**, not a measurement. Nothing in this design could detect a
read that happened and was not recorded.

That is not a claim that a read occurred — the stage sources are short, they are
auditable, and `grep -rn "06-evaluator" bin/30_project_topaz.py bin/40_run_topaz.py`
comes back clean. It is a claim about what kind of guarantee this is: **auditable
discipline, verifiable by inspection, not an enforced boundary.** The fix is
structural rather than procedural — run stages 30–50 in a container or process
whose filesystem view does not include `06-evaluator/` at all, so that reading it is
impossible rather than merely absent. That is a Phase 3 change.

### 3.12 Locally reproducible, not independently published

The source-only baseline is under Git and a clean local clone has completed the
full run. The commit intentionally excludes deterministic generated artifacts,
evaluator truth, Topaz state, submissions, local environments and raw discovery
scratch notes. The scratch notes referenced temporary probes and a companion file
that were not retained, so publishing them would create broken evidence links; the
maintained documentation and executable stages contain the conclusions used by
the experiment.

This removes the ambiguous placeholder-clone claim and makes the local baseline
repeatable. It does **not** establish independent reproducibility: the repository
does not yet have a published remote and no second environment or operator has
reproduced it. Until then, the accurate claim is "clean-clone verified locally."

### 3.13 The discovery phase was repository-independent, not documentation-only

The stated ground rule was "released wheel and its public documentation only". The
first half held; the second did not, and §1 is the reason. With no published
vocabulary for the magic string literals (§1.3), no published logical-key index
(§1.4), no documentation of the cross-tenant prohibition (§1.5) or the input
constraints (§1.6), the released documentation was not sufficient to build against.

Discovery therefore read what the wheel itself ships: module source under
`site-packages/synthworld/`, pydantic model definitions and field types, function
signatures, `__all__` export lists, and the packaged reference bundles under
`synthworld/benchmarks/`. No source checkout, editable install, or unpublished
network API was used, and nothing outside the installed distribution was consulted.

That is a legitimate position for an outside consumer — all of it arrives with
`pip install` and is available to anyone — but it is a weaker claim than
"documentation only", and the distinction matters for anyone judging how much of
this could have been built from the published surface alone. The answer is: not
this much.
