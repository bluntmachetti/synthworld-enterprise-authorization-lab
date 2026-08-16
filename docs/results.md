# Results

Reported in the six parts requested, plus what is and is not supported by them.

Provenance: `idcognito-synthworld==0.15.0` (wheel sha256 `f1b17f82…57ee60`);
Topaz `0.33.16@sha256:835868c0…54360`, which reports `version 0.33.16, commit
81b8405` at runtime; source topology sha256 `29ea8dd1…0871d1`; seed `20260816`.
Validation: **32/32 checks pass** (`reports/validation-report.json`).

---

## 1. What SynthWorld generated

From the adapter's import document, `compile-enterprise-access` and the enterprise
Python API produced:

| Compiled universe | count |
|---|---:|
| tenants | 5 |
| organisations | 5 |
| units (division + team + vendor department) | 80 |
| principals (employee 159, workload 101, supplier 38) | 298 |
| accounts (workload 490, workforce 104, agent 3) | 597 |
| access subjects (principals ∪ accounts) | 895 |
| groups | 80 |
| roles | 129 |
| authorization targets | 101 |
| permissions | 404 |
| access atoms | 3 174 |
| relationship anchors | 1 156 |

| Evaluation corpus | count |
|---|---:|
| contexts | 2 |
| **evaluation cells (the unit of scoring)** | **3 209** |
| access requests (1:1 with cells) | 3 209 |
| session slots / role activation requests | 0 / 0 |

| Observed directory (public RBAC kernel) | count |
|---|---:|
| memberships | 197 |
| group nesting edges | 35 |
| group role assignments | 17 |
| subject role assignments | 345 |
| role hierarchy edges | 56 |
| role grants | 1 010 |
| account observations | 597 |
| direct entitlements | 0 |

**Determinism**: three independent builds produced 23 byte-identical artifacts.
Universe digest `a4c7bcfb74956b88a55dade06fff0869bd30583826732315aadcdf16a066a7c6`;
corpus digest `7c582bc94d117350c539d86b9a013b46d7628f1bf091a921a52457d79c483816`.
Stage 80 asserts both, so accidental non-determinism fails the run.

Split: **13 public files** (zone 2, digest-indexed) and 10 evaluator-only files
(zone 6).

---

## 2. What the experiment adapter transformed

`bin/10_map_topology.py` turns a service/vendor topology into an identity/access
blueprint. It classifies **100 topology field paths**:

| classification | fields |
|---|---:|
| represented directly | 11 |
| represented through a documented transformation | 16 |
| preserved as experiment-owned metadata | 43 |
| not representable | 30 |

Blueprint emitted: 5 tenants, 5 organisations, 80 units, 88 populations
(298 declared principals), 80 groups, 129 roles, 35 resource sets,
201 principal access-atom rules, 127 account allocations, 92 account access-atom
rules, and a directory state of 53 membership rules, 35 nesting edges, 17 group
role assignments, 101 population role assignments, 56 hierarchy edges and 350 role
grants.

The load-bearing transformations, each documented with its rule in
`01-source/config/experiment.yaml` and its rationale in
`docs/topology-mapping-report.md`:

- **Tenancy from legal entities.** `organisation.metadata.legal_entity_footprint`
  (uk, europe, americas, apac_mea) plus one external vendor tenant. Regions map to
  entities. Cross-tenant denial therefore models ring-fence enforcement.
- **Population scaling.** `team_locations[].headcount_in_region` sums to 7 150 real
  staff, divided by 50 (ceiling, min 1) → 298 principals. Lossy; the divisor is a
  config knob and 1 reproduces full scale.
- **Role ladder from ownership.** `ownership_type` primary/on_call/supporting →
  service-owner > service-operator > service-contributor, with different action
  grants. This ladder is what the scope-exceeded case exercises.
- **Machine-to-machine access from dependencies.** 104 `service_dependencies` edges
  become workload-account access atoms.
- **Two-level unit tree, not three.** `domains[].parent_domain` exists but is null
  on all 7 rows, so no domain hierarchy can be derived.
- **Data classification could not cross the boundary.** The values map 1:1 onto
  SynthWorld's `InformationClassification`, but `ResourceSetTemplateV1` has no
  classification field, so a clearance model was designed and then could not be
  built. Recorded as not representable rather than claimed as mapped — this was
  caught by the mapping report's own coverage audit and the ledger was corrected.

**What could not be declared at all**: the released importer forbids cross-tenant
declarations of every kind. The topology contains **135 team-owns-service pairs and
49 service-to-service calls that genuinely straddle two legal entities**. They are
preserved in `01-source/generated/cross-boundary-pairs.json` and motivate the
cross-boundary case class, which is expressed through the ABAC layer instead.

---

## 3. What Topaz stored

Projected from the 13 public artifacts only (`bin/30_project_topaz.py` re-hashes
them against `PUBLIC-INDEX.json` and aborts on mismatch):

| | count |
|---|---:|
| directory objects (8 types) | **1 699** |
| directory relations (25 tuple shapes) | **5 879** |
| authorization requests | 3 209 |
| role-holder graph queries | 129 |

**Load verification, before any decision was made**: every object and relation was
read back and compared per type and per tuple shape — 1 699/1 699 objects across
all 8 types, 5 879/5 879 relations across all 25 shapes. Seven structural
`/api/v3/directory/check` smoke cases passed, covering subject role assignment,
group role assignment via membership, group-nesting closure, role-hierarchy
closure, role grant → exercisable, the account-holds-no-role negative, and target
ownership. 0 HTTP errors across 1 699 + 5 879 + 3 209 + 129 calls.

The two transitive closures live in the Topaz **manifest**, so Topaz computes them,
not the projector:

```
group.member           : subject | group#member          <- group-nesting closure
role.holder            : assignee | senior_role->holder  <- role-hierarchy closure
permission.exercisable : direct_holder | granting_role->holder
```

---

## 4. What Topaz decided

3 209 `POST /api/v2/authz/is` calls, seven decisions each, ~0.6 s total.

| decision | true | false |
|---|---:|---:|
| `birthright` | 0 | 3 209 |
| `intended` | 3 007 | 202 |
| `effective` | 3 007 | 202 |
| `rbac_final` (directory-RBAC family: + binding + lifecycle) | 2 989 | 220 |
| `final` (composed: + ABAC guard) | 2 762 | 447 |
| `abac_deny` | 227 | 2 982 |
| `cross_tenant` (derived independently in Rego) | 63 | 3 146 |

18 cells are effective-allow but `rbac_final`-deny — the account lifecycle gate
firing, since the binding gate is conceded and never fires. A further 227 are
downgraded by the ABAC guard.

**`final` in that table is never scored.** It is the composed decision, and the
released package ships no scorer for it (`docs/limitations.md` §1.1). Everything in
§5 measures `effective` and `rbac_final`. The 227 ABAC downgrades — the whole
scope-exceeded and cross-tenant-boundary population — appear in this section and
nowhere else.

**Two independent cross-checks, both clean:**

- The projector evaluated the same published ABAC rules in Python, kept its verdict
  outside the request body, and stage 40 compared: **0 disagreements** across 3 209
  cells.
- Rego derived `cross_tenant` from the published tenant facts, independently of the
  rule scope. It matches the published cross-tenant rule's scope exactly: 63 = 63,
  0 in scope with matching tenants, 0 with differing tenants out of scope.
  This is a **cross-check, not a control path**: `cross_tenant` is emitted as its
  own decision and is not an input to `abac_deny` or `final`. The published rule
  still decides by enumerated cell id, because the ABAC vocabulary offers no
  negation to decide by (§7.11).

What Topaz derived vs what it was told: the request body carries only `cell_id`,
`subject_id`, `subject_kind`, `target_id`, `action`, `permission_id`, `tick`, the
published ABAC facts, and the published in-scope rules. **No role, group, nesting,
hierarchy, grant, entitlement or binding fact reaches the request.** Those come
from the directory.

---

## 5. What SynthWorld evaluated

Submission sealed at
`89099e3b55226cd6bd378f6dc7a2153aed3ee8d0e6e7fe3f9781d5be25a69f05` before any
evaluator artifact was opened; stage 60 re-verified it and would have aborted on
drift. 3 209/3 209 cells answered by Topaz, 0 defaulted.

### Scored — genuine measurements

| scorer | metric | value | n |
|---|---|---:|---:|
| directory-RBAC | `rbac.effective_decision_accuracy` | **1.0000** | 3 209 |
| directory-RBAC | `rbac.rbac_decision_accuracy` (final) | **1.0000** | 3 209 |
| directory-RBAC | `rbac.authorized_role_exact_match_rate` | **1.0000** | 895 |
| directory-RBAC | `birthright.birthright_decision_accuracy` | **1.0000** | 3 209 |
| ABAC | `abac.abac_decision_accuracy` | **1.0000** | 3 209 |

### Per case class — every class perfect, on the directory-RBAC family only

Both columns are directory-RBAC-family decisions. `rbac_final` is `effective` gated
by account binding and lifecycle **only** — the ABAC guard is not in it, because
`evaluate_enterprise_directory_rbac` does not score it. The third column is the
count of cells in the class whose *RBAC-family truth* is `deny`, and it is the
column to read before reading a class name:

| class | cells | effective | rbac_final | of which RBAC truth = deny |
|---|---:|---:|---:|---:|
| same-tenant allow | 2 754 | 1.0000 | 1.0000 | 0 |
| deny: missing role or relation | 143 | 1.0000 | 1.0000 | 143 |
| deny: scope exceeded | 164 | 1.0000 | 1.0000 | **0** |
| deny: cross-tenant boundary | 63 | 1.0000 | 1.0000 | **0** |
| deny: wrong principal binding | 15 | 1.0000 | 1.0000 | 15 |
| temporal, pre-expiry | 35 | 1.0000 | 1.0000 | 27 |
| temporal, post-expiry | 35 | 1.0000 | 1.0000 | 35 |

The two bolded zeroes are the important entries. For all 227 cells in those two
classes the RBAC truth is `allow`, the submission predicted `allow`, and the
1.0000 is a correct prediction of an **allow**. Their deny exists only in the
composed decision (`final` in §4: 447 denies vs `rbac_final`'s 220), and
**SynthWorld ships no scorer for the composed decision** — see
`docs/limitations.md` §1.1. So the composed result of the ABAC guard is reported
descriptively in §4 and is nowhere scored, here or in the released package. The
scoring report carries `composed_decision_scored: false` on every class, plus the
per-class `rbac_truth_final_deny` count above.

Two further readings that the 1.0000 does not by itself support:

- **`deny: wrong principal binding` was not decided by the binding gate.** The
  policy sets `binding_gate_pass := true` unconditionally. All 15 cells carry zero
  `effective_path_ids` in truth, so `effective` was already deny and the gate had
  nothing left to do. Correct answer, wrong mechanism — expanded in §7.2.
- **`deny: cross-tenant boundary` is partly tautological.** The published deny rule
  enumerates exactly those 63 cell ids under an `action_class_is` predicate listing
  all four action classes, which is true for every cell in its scope; the rule
  therefore denies the cells it was told to deny. See §7.11.

### Not publicly winnable — reported separately, not folded into the above

| metric | value | why |
|---|---:|---|
| `intent.intended_decision_accuracy` | 0.9913 | The RBAC intent overlay is exported to neither tree. Predicting `intended == effective` means this measures **declared-vs-intended drift (0.87 %)**, not policy accuracy. |
| `rbac.rbac_derivation_path_exact_match_rate` | 0.0629 | `effective_path_ids` are internal SynthWorld identifiers absent from every public artifact. Submitted empty. |
| `abac.predicate_outcome_accuracy` | 0.0000 | Keyed by `truth_id`, minted inside the evaluator-only ABAC truth. The outcomes are derivable; the identifiers are not. |
| `ssd.ssd_violation_detection_rate` | 0.0000 | SoD constraints live in the unpublished intent overlay. |
| `ssd.ssd_violation_false_positive_rate` | 0.0000 | The 0.0 means no false alarms were raised — a trivial consequence of submitting nothing. |

### Mechanisms not exercised

`rebac.rebac_decision_accuracy` 0.0969 and
`rebac.relationship_path_exact_match_rate` 0.0000. The profile is
`rbac_with_abac_guard` for all 3 209 cells, so the relationship mechanism is not on
the decision path and was not projected. Every cell was submitted
`not_applicable`; guessing would be fabrication.

### World properties, not scores

`sprawl.effective_outside_intent_rate` 0.0067, `sprawl.missing_intended_access_rate`
0.0027, `birthright_breadth.effective_outside_birthright_rate` 1.0,
`redundancy.redundant_derivation_cell_rate` 0.8563,
`accumulation.privilege_accumulation_subject_rate` 0.0. The released scorer computes
these from truth alone and ignores the submission — verified by degrading a
prediction and observing they do not move.

### Six metrics have a zero denominator

`activation.*` (2), `activation_safety.*` (2), `dsd.*` (1) and
`birthright.birthright_assignment_exact_match_rate`. The corpus declares no session
slots, activation requests or birthright rules, so these report `null`.

**There is no aggregate.** The released scorers deliberately emit none, and the
package ships no scorer for the composed access state at all. None was invented.

---

## 6. Which conclusions are supported

1. **A real Rego policy, given only the public half of the world, reproduced
   SynthWorld's `effective` and directory-RBAC `final` decisions exactly** —
   3 209/3 209 on both, with the submission sealed before truth was opened. The
   composed decision is not part of this claim: nothing scores it (§5).
2. **The multi-hop derivation works.** Transitive group nesting, transitive role
   hierarchy, role grants and account→principal authority inheritance are all
   resolved inside Topaz from directory relations. The seven structural smoke
   checks isolate each hop independently.
3. **All six required case classes are present and decided correctly** — RBAC
   derivation (143), ABAC scope guard (164), ABAC boundary guard (63), the binding
   cohort (15), lifecycle at two ticks (70), and the allow baseline (2 754). Three
   qualifications, none of which this run can discharge:
   - The 164 + 63 ABAC classes are denied in the composed decision only, and the
     composed decision is **unscored** — what scored 1.0000 for them is an allow.
   - The 15 binding cells were denied by the missing RBAC derivation, **not** by
     the binding gate, which is conceded and never fires.
   - So the mechanism-by-mechanism claim holds for RBAC derivation and lifecycle,
     holds for the ABAC guard only in the descriptive `final` column of §4, and
     does not hold at all for account binding.
4. **The temporal case is a genuine transition, not an assertion.** The same access
   atom is evaluated at tick 100 and tick 200; the expiring cohort flips and the
   suspended cohort denies at both.
5. **The ABAC guard is evaluated, not echoed — but what it evaluates is thin.**
   Rego does evaluate the published predicates and combine them under each rule's
   own operator, and an independent Python evaluation agrees on all 3 209 cells.
   The limit is the rules themselves: the cross-tenant deny rule enumerates its 63
   cell ids under a predicate that is true for every action class, so evaluating it
   cannot produce any answer other than its own scope. Rego's independently-derived
   `cross_tenant` decision **is** a real evaluation of the boundary condition and it
   agrees on all 63 — but it is a cross-check emitted alongside the answer, not an
   input to `abac_deny`, and therefore not what drives `final`. The agreement is
   evidence supplied by this experiment, not by the contract.
6. **Account authority inheritance was modelled correctly.** Applying the same rule
   the policy uses for permissions to the reported role sets moved
   `authorized_role_exact_match_rate` from 0.88 to 1.00, confirming the semantics
   match SynthWorld's without having been fitted to truth.
7. **The pipeline is reproducible end to end on this machine, including Topaz.** A
   full clean run from a deleted virtualenv and a destroyed Topaz volume reproduced
   the submission digest `89099e3b5522…5a69f05` **byte for byte**. That covers the
   whole chain — topology → blueprint → compiled world → directory load → 3 209
   authorization decisions → submission — not just the generation half. The image
   is pinned by index digest, the dependencies by hash, and 32/32 validation checks
   pass. It is **not yet independently reproducible as published**: this directory
   is not a Git repository and has never been published, so a third party has
   nothing to fetch. See §7.13.
8. **The topology mapping is complete and auditable.** All 100 field paths
   classified, every lossy transformation named with its factor, every
   non-representable field given a reason.

## 7. Which conclusions are NOT supported

1. **This says nothing about Topaz's general correctness.** It shows that this
   policy, over this directory, reproduces this world's decisions.
2. **The binding gate was never tested, and the case class named for it does not
   test it.** The policy concedes the gate outright — `binding_gate_pass := true`,
   unconditionally, for every subject — because the canonical binding is
   evaluator-only. The 15 binding-mismatch cells scored 1.0000, but the gate is not
   what decided them: all 15 carry **zero `effective_path_ids`** in truth, so the
   RBAC derivation already found no path and `effective` was already deny. Topaz
   returned `effective=false` and `rbac_final=false` on every one of them, and would
   have returned the same with the gate deleted from the policy. So the class is a
   duplicate of "missing role or relation" as far as any mechanism is concerned.
   **The concession was free in this world. It would not be in a world where the
   mis-bound principal held authority the real owner lacked, and this experiment
   provides no evidence either way. Testing it needs a case where the two differ.**
3. **`intended_decision` was not tested.** It was predicted equal to `effective` by
   construction. 0.9913 is a property of the world's 0.87 % drift.
4. **Derivation paths were not tested.** Submitted empty; 0.0629 is the empty-path
   rate.
5. **Separation of duties was not tested.** Constraints are not public; nothing was
   submitted. The 0.0 false-positive rate is not evidence of precision.
6. **The relationship (ReBAC) mechanism was not tested at all.**
7. **Just-in-time activation, dynamic SoD and birthright assignment were not
   tested** — zero denominators, because the source topology describes no
   activation model and inventing one would not be grounded in the supplied data.
8. **Cross-tenant access was never a directory edge.** The importer forbids
   declaring one. The boundary case is an ABAC assertion that the resource's
   authoritative tenant differs — a faithful model of a request served outside the
   subject's legal entity, but not the same thing as a cross-tenant relation
   existing in the directory.
9. **The 1.0000 scores are not evidence that the world is hard.** They are evidence
   that the policy is correct on it. The world was generated by the same author as
   the policy, in separate stages with a sealed submission — but a genuinely
   adversarial world was not attempted.
10. **The composed decision was not scored — by anything.** `per_case_class` reports
    `effective` and `rbac_final`, both from the directory-RBAC family. The composed
    `final`, which is the only decision the ABAC guard participates in, has no
    prediction model and no `evaluate_*` function anywhere in the released package
    (`docs/limitations.md` §1.1), so it is reported descriptively in §4 and scored
    nowhere. Concretely: the ABAC guard downgrades 227 cells that the RBAC family
    calls `allow`, and **not one of those 227 downgrades is measured against
    truth**. The per-cell ABAC scorer measures the guard's own per-cell verdict, not
    its effect on the decision.
11. **The cross-tenant boundary rule is partly tautological.** `SameTenantV1` is
    positive-only and the vocabulary has no negation, so a cross-tenant deny can be
    expressed only by enumerating cell ids. The published rule enumerates all 63,
    under an `action_class_is` predicate listing every action class — a predicate
    that is true for every cell in its own scope. Evaluating that rule therefore
    cannot yield anything but its scope. Rego's independent `cross_tenant`
    derivation is a genuine evaluation and agrees on all 63, but it is a
    cross-check: it feeds no other decision. **The boundary condition was verified
    by the experiment, not enforced by the policy under test.**
12. **The isolation is disciplined, not enforced.** Stage 20 writes the evaluator
    tree before Topaz starts, so the answer key exists on the same filesystem,
    readable by the same user, throughout the run. The digest seal proves the
    submission was not modified after finalization; it does **not** prove no
    evaluator file was read before that. The `ISOLATION VIOLATION` guard is a
    same-process path check, not a sandbox. What is established is auditability;
    what would establish the stronger claim is running stages 30–50 in a container
    or process that cannot mount `06-evaluator/` at all.
13. **It is locally reproducible, not yet independently published.** The source-only
    baseline is under Git and has been verified from a clean local clone. Generated
    artifacts, evaluator truth and raw discovery scratch notes are deliberately not
    committed. There is not yet a published remote or an independent reproduction,
    so this remains local evidence rather than a generally available experiment.
14. **The discovery phase was repository-independent, not documentation-only.** The
    released documentation was insufficient to build against, so discovery read the
    installed wheel's module source, pydantic schemas, function signatures,
    `__all__` exports and packaged reference bundles. No source checkout or
    editable install was used and no unpublished API was called, but "public
    documentation only" would overstate it.
15. **The Britannia topology is fictional** and is not claimed to be representative
    of any real bank.
