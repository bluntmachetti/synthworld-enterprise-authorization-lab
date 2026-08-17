# Reference results

These results describe one fixed, reproducible experiment: SynthWorld 0.16.0,
seed `20260816`, the committed Britannia topology and adapter, and Topaz 0.33.16
commit `81b8405`. They are not a general product certification.

## Generation and projection

| generated universe | count |
|---|---:|
| tenants / organisations / units | 5 / 5 / 80 |
| principals / accounts / access subjects | 298 / 597 / 895 |
| authorization targets / permissions / access atoms | 101 / 404 / 3,174 |
| evaluation cells | 3,209 |

The topology adapter classifies 100 source field paths. The detailed mapping and
all unrepresentable fields are in `docs/topology-mapping-report.md`.

| Topaz projection | expected | read back |
|---|---:|---:|
| objects | 1,699 | 1,699 |
| relations | 5,879 | 5,879 |
| Britannia authorization requests | 3,209 | 3,209 responses |
| adversarial requests | 14 | 14 responses |

The directory verification compares every object type and relation tuple shape,
not only totals. Seven structural directory checks cover direct role assignment,
group membership and nesting, role hierarchy, permission grants, an account
negative, and target ownership.

## Britannia decision distribution

| Topaz decision | allow/true | deny/false |
|---|---:|---:|
| birthright | 0 | 3,209 |
| intended | 3,007 | 202 |
| effective RBAC | 3,007 | 202 |
| RBAC final after lifecycle/binding gates | 2,989 | 220 |
| composed final after ABAC guard | 2,762 | 447 |
| ABAC deny | 227 | 2,982 |
| cross-tenant derivation | 63 | 3,146 |

The projector separately evaluates the published ABAC rules and compares its
result with Rego. The reference run has zero disagreements. Rego also derives
tenant inequality independently from public tenant facts; all 63 derived
cross-tenant cells match the published rule scope.

## Scored dimensions

The exercised reference dimensions score 1.0 at their explicit denominators:

| area | metrics exercised | denominator |
|---|---|---:|
| composed | effective and final decision accuracy | 3,209 each |
| mechanism inventory | exact mechanism outcomes and profile inventory | 3,209 each |
| RBAC | composed RBAC outcome, effective/final RBAC, authorized role sets | 3,209 / 895 |
| ABAC | composed and mechanism-specific outcome | 3,209 |
| conflict | detection and resolution | 3,209 / 429 |
| lifecycle | lifecycle status | 311 |
| runtime gate | gated final decision | 18 |
| adversarial final | final decision | 14 |
| adversarial binding | principal and binding status | 4 each |
| adversarial mechanisms | tenant, scope, binding, time, clearance, composition | 1–2 each |
| adversarial robustness | identifier-independent decisions | 7 |
| adversarial temporal | expected transition | 1 |

The full report retains numerator, denominator, support, denominator meaning, and
empty-set behaviour for every metric. Empty dimensions such as ReBAC in the
Britannia profile are not evidence of success. World-property metrics computed
from truth alone and dimensions a public consumer cannot submit are reported in
separate sections.

No aggregate is calculated because these metrics have different semantics and
denominators.

## Per-class Britannia composed result

| class | cells | composed final accuracy |
|---|---:|---:|
| same-tenant allow | 2,754 | 1.0 |
| missing role/relation | 143 | 1.0 |
| scope exceeded | 164 | 1.0 |
| cross-tenant boundary | 63 | 1.0 |
| wrong observed principal binding | 15 | 1.0 |
| temporal pre-expiry | 35 | 1.0 |
| temporal post-expiry | 35 | 1.0 |

RBAC-family final and composed final remain separate in the JSON report. In
particular, scope and cross-tenant denial are ABAC composition effects, not RBAC
denials.

## Adversarial controls

The released SynthWorld reference pack includes deliberately incomplete public
baselines. Each one is caught by its dedicated metric:

| faulty baseline | discriminating metric | reference value |
|---|---|---:|
| tenant blind | tenant decision accuracy | 0.0 |
| scope blind | scope decision accuracy | 0.0 |
| binding blind | binding decision accuracy | 0.0 |
| time blind | time decision accuracy | 0.0 |
| clearance blind | clearance decision accuracy | 0.0 |
| RBAC only | composition decision accuracy | 0.0 |
| identifier/order memorization | identifier-independent accuracy | 0.2857 |

Two additional mutations prove metric independence: changing only an RBAC
mechanism outcome lowers the mechanism exact-match rate while composed final
accuracy remains 1.0; changing only a composed final decision lowers composed
final accuracy while mechanism exact-match remains 1.0.

## Integrity and isolation controls

The clean run validates:

- exact topology and frozen core artifact digests;
- byte-identical public copies and no stray public files;
- referential integrity and one request per cell;
- complete raw and normalized result inventories;
- exact sealed prediction and evidence bytes;
- evaluator-free SUT mounts and a read-only public input;
- rejection of a deliberately evaluator-mounted runner;
- rejection of unsealed, mutated, cross-artifact, and version-mismatched
  submissions;
- absence of evaluator vocabulary from the public HTML view; and
- digest-pinned images, no `latest`, no host port publishing, and an internal SUT
  network.

The authoritative outputs are generated rather than committed:

- `07-reports/scoring/scoring-report.json`
- `07-reports/negative-controls.json`
- `07-reports/seal-negative-controls.json`
- `07-reports/validation-report.json`

## What these results do not prove

- They do not establish correctness for Topaz versions, policies, topologies, or
  adapters other than those sealed in this run.
- The Britannia binding-named class is not an isolated binding test; the 0.16
  adversarial reference lane supplies the dedicated binding cohort.
- The Britannia profile does not exercise ReBAC on its decision path; the
  adversarial composition case covers one RBAC/ReBAC combination failure but is
  not broad ReBAC coverage.
- The external HTML projection is not a SynthWorld renderer.
- Container isolation does not protect against a hostile Docker daemon or host
  administrator.
- A 1.0 result on a small cohort is only a statement about that cohort and its
  denominator.
