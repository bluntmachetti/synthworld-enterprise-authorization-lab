# Public/evaluator isolation design

The authorization system must produce its submission without access to benchmark
answers. The reference lab enforces that boundary through Compose filesystem and
network capabilities, then records enough evidence for the scorer to verify the
run before opening evaluator truth.

## Roles and capabilities

| role | network | readable inputs | writable outputs | evaluator access |
|---|---|---|---|---|
| owner | none | topology, config | generated import, public artifacts, evaluator artifacts | read/write: creates truth |
| projector | none | generated import, public artifacts | Topaz model, policies, requests | none |
| Topaz | internal SUT network | config, projected policy bundle | private database volume | none |
| runner/SUT | internal SUT network | generated mapping, public artifacts, projected inputs | raw results, predictions, seal, public view | none |
| scorer | none | public inputs, results, submission, evaluator truth | reports | read-only |

Every Python role uses a read-only root filesystem, drops Linux capabilities,
enables `no-new-privileges`, and receives only its explicit bind mounts. Topaz has
no published host ports and is reachable only on the internal Compose network.

## Artifact zones

| zone | contents |
|---|---|
| `01-source/` | supplied topology, experiment configuration, deterministic mapping output |
| `02-synthworld-public/` | only files exported as public, plus a SHA-256 index |
| `03-topaz-input/` | projected model, Rego bundle, directory records, request corpora |
| `04-topaz-results/` | raw and normalized responses and the SUT isolation report |
| `05-submission/` | typed predictions and `SUBMISSION-SEAL.json` |
| `06-evaluator/` | intact public/evaluator benchmark trees and owner receipt |
| `07-reports/` | scorer, negative-control, and validation reports |

The regular SynthWorld evaluator loaders validate evaluator artifacts against
their sibling public artifacts, so zone 6 keeps intact exported trees. Zone 2 is
a byte-identical copy of only the public half. Stage 80 verifies every indexed
file in both locations and rejects stray public-zone files.

## Runner isolation proof

Before any Topaz request, `bin/05_check_isolation.py` checks:

- `/evaluator` and `/app/06-evaluator` do not exist;
- no evaluator-named environment capability is present;
- `/proc/self/mountinfo` exposes no evaluator mount;
- the public artifact index exists; and
- the public artifact bind mount is read-only.

It writes `04-topaz-results/isolation-report.json`. Stage 50 refuses to seal
unless that report passed. The report itself is bound into the seal.

The `isolation-regression` Compose profile deliberately supplies `/evaluator`.
`bin/run_lab.sh` treats rejection as success and acceptance as a fatal failure.
This catches accidental future capability broadening in the runner service.

## Pre-scoring seal

Stage 50 runs inside the evaluator-free runner and writes
`05-submission/SUBMISSION-SEAL.json`. The seal contains exact SHA-256 values for:

- all five prediction artifacts;
- `PUBLIC-INDEX.json` and every public artifact digest it records;
- raw and normalized outputs from both Topaz lanes;
- run reports, policy bundle manifest, and both Rego policies;
- the isolation probe and the public-only adapter/runner source files; and
- package, schema, adapter, Topaz image, runtime version, and commit provenance.

The seal carries its own digest. Stage 60 verifies the seal document, submission
bytes, all bound evidence, the public inventory, and version compatibility before
calling an evaluator loader.

`bin/55_seal_regression.py` proves four refusal paths:

1. the seal is absent;
2. a prediction changed after sealing;
3. the sealed public inventory belongs to a different artifact set; and
4. the SynthWorld package version differs from the sealed provenance.

## What the boundary claims

The SUT containers cannot access evaluator paths through the capabilities in
`compose.yaml`. This is stronger than a source-code convention or a post-hoc
claim that no read occurred. The owner necessarily creates truth, and the scorer
necessarily reads it; neither role participates in producing the sealed product
decision.

The threat model is accidental leakage and experiment-architecture mistakes. A
host administrator or process controlling the Docker daemon can inspect or
change containers, images, mounts, networks, and volumes. This lab does not claim
protection from that administrator. For a hostile-host threat model, the owner,
SUT, and scorer would require separate trust domains and remotely attested
execution.

## Public policy is not evaluator leakage

A policy decision point must receive public identity observations, policy facts,
and rules. Public ABAC facts and rule scope are therefore legitimate SUT inputs.
Canonical bindings, expected decisions, evaluator case labels, and derivation
truth remain evaluator-only.

The adversarial lane resolves public credential evidence before the Topaz call.
That resolution result is product input derived through the released public
helper; the evaluator retains the canonical binding and expected outcome used to
score it.

## Audit commands

```bash
# Render the resolved Compose model and inspect role mounts/networks.
docker compose config

# Run the complete boundary and its expected-failure regression.
bin/run_lab.sh

# Inspect the exact pre-scoring evidence.
python -m json.tool 05-submission/SUBMISSION-SEAL.json

# Inspect the final machine checks.
python -m json.tool 07-reports/validation-report.json
```
