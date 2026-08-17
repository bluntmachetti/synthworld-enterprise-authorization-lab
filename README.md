# SynthWorld frozen enterprise authorization reference experiment

This frozen reference experiment demonstrates how an external consumer used the released
`idcognito-synthworld==0.16.0` package to generate enterprise identity and
authorization benchmarks, project only public artifacts into Aserto Topaz, and
score the resulting decisions against separately mounted evaluator truth.

It is intentionally outside the SynthWorld core repository. Topaz, Rego, Docker,
and the Britannia topology are experiment concerns; SynthWorld remains a
protocol-neutral deterministic benchmark package.

Publication status: **frozen and unsupported**. The workflow was CI-verified and
reproduced byte-for-byte against the exact versions below before publication. It
is retained as evidence of one experiment, not as a maintained Topaz integration,
adapter SDK, compatibility promise, or invitation to add other authorization
systems here.

Community experiments remain owned by their authors. They may be indexed as
self-reported results in the SynthWorld
[Experiment results](https://github.com/bluntmachetti/synthworld/discussions/categories/experiment-results)
Discussion category; inclusion does not mean that SynthWorld maintainers have
reviewed, reproduced, endorsed, or agreed to support them.

## What the lab tests

The lab has two complementary lanes:

| lane | purpose | size |
|---|---|---:|
| Britannia topology | topology-to-identity transformation, directory loading, RBAC and ABAC composition, lifecycle gates, and scale | 3,209 cells |
| SynthWorld adversarial reference pack | single-factor tenant, scope, binding, time, clearance, and RBAC/ReBAC composition failures | 14 attempts |

Both lanes execute against the same Topaz instance. The machine report keeps
transport/load verification, mechanism metrics, composed metrics, lifecycle
metrics, and robustness metrics separate. It deliberately computes no aggregate
score.

The adapter boundary is file based: public SynthWorld artifacts enter the
projector; raw product requests/responses leave the runner; typed SynthWorld
predictions enter the scorer. That boundary shows how an independently maintained
AuthZEN, OPA, OpenFGA, or other adapter could replace the projector/runner pair;
this publication does not undertake to build or maintain those adapters.

## Reproduce it

Prerequisites: Docker with Compose v2. No local Python environment, SynthWorld
checkout, or Topaz installation is needed.

Download and verify the reproduction kit attached to the immutable SynthWorld
release
[`enterprise-authorization-topaz-0.16.0-1`](https://github.com/bluntmachetti/synthworld/releases/tag/enterprise-authorization-topaz-0.16.0-1),
then run:

```bash
sha256sum -c SHA256SUMS
unzip enterprise-authorization-topaz-reproduction-kit-0.16.0-1.zip
cd enterprise-authorization-topaz-reproduction-kit-0.16.0-1
bin/run_lab.sh
```

To supply another topology that follows the documented Britannia topology
shape, update the explicit mapping configuration and topology SHA-256 in
`01-source/config/experiment.yaml`, then run:

```bash
bin/run_lab.sh --topology /path/to/organization-topology.yaml
```

The owner stage refuses a topology/config digest mismatch or an implicit seed.
This adapter is topology-shape-specific by design; a different source schema
requires a separate mapping adapter, not silent field guessing.

The command builds a digest-locked Python image, generates the world, starts a
digest-pinned Topaz instance on an internal-only network, runs both benchmark
lanes, seals the submission, scores it, runs negative controls, validates every
zone, and tears down Topaz and its database.

Primary outputs:

| artifact | path |
|---|---|
| machine validation report | `07-reports/validation-report.json` |
| metric report | `07-reports/scoring/scoring-report.json` |
| faulty-system controls | `07-reports/negative-controls.json` |
| seal refusal controls | `07-reports/seal-negative-controls.json` |
| sealed submission | `05-submission/SUBMISSION-SEAL.json` |
| public-only reference view | `viz/britannia-world.html` |

All generated experiment zones are ignored by Git. A clean run reconstructs
them from the committed topology, configuration, adapters, and hash-locked
dependencies.

## Enforced public/evaluator boundary

The Compose services have distinct filesystem capabilities:

```text
owner      topology/config -> public artifacts + evaluator truth
projector  public artifacts -> Topaz model, policy, and requests
runner     public artifacts + Topaz -> raw results + sealed submission
scorer     sealed submission + evaluator truth -> metric reports
```

The projector and runner do not mount `06-evaluator`; the scorer mounts it
read-only and has no network. The runner starts with an isolation probe that
checks the evaluator path, environment, mount table, and read-only public mount.
A regression service deliberately mounts `/evaluator` and the workflow succeeds
only when that service is rejected.

The submission seal binds:

- every prediction file;
- the complete public artifact inventory;
- raw and normalized Topaz responses;
- both Rego policies and the bundle manifest;
- adapter source files;
- the SynthWorld distribution version and published wheel/sdist digests;
- the immutable Topaz image, reported version, and commit; and
- the passed isolation report.

The scorer verifies all of that before loading evaluator truth. Four negative
controls prove that an absent seal, changed prediction, mismatched public
inventory, or package-version mismatch is refused.

This boundary protects against accidental evaluator leakage by the SUT. It is
not a claim against a hostile Docker daemon or host administrator. See
[`docs/isolation-design.md`](docs/isolation-design.md).

## Provenance

| dependency | immutable reference |
|---|---|
| SynthWorld | `idcognito-synthworld==0.16.0` |
| SynthWorld wheel SHA-256 | `dfe584e52185fe1e2b0da238589492ac5995b21a33e7ce1cb7dac0c3330dc480` |
| SynthWorld sdist SHA-256 | `8841225c263d13761466d7a9beb5f2378c2c2ae69c9471a6d37ad815a49deb57` |
| Topaz | `ghcr.io/aserto-dev/topaz:0.33.16@sha256:835868c04bdd7129127ea43642ffff7363d0bd26d5e1a37631fa881431054360` |
| Topaz runtime | `0.33.16`, commit `81b8405` |
| Python base | `python:3.12-slim@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65` |
| topology SHA-256 | `29ea8dd155ceed277eedf3f7261f0ba6844ff5a3e6c5a9c70164ae78b80871d1` |
| seed | `20260816` |

Python transitive dependencies are pinned with hashes in `requirements.lock`.
Container images are pinned by immutable digest. No `latest` tag or host port is
used.

## Results and correct interpretation

The verified reference run produces:

- exact object and relation read-back from Topaz: 1,699 objects and 5,879
  relations;
- 3,209/3,209 Britannia decisions and 14/14 adversarial decisions;
- 1.0 accuracy on the exercised composed effective/final, RBAC, ABAC, conflict,
  lifecycle, runtime-gate, and adversarial dimensions;
- all seven released faulty adversarial baselines rejected by their dedicated
  metric; and
- independent negative controls showing a mechanism error and a composed-decision
  error affect different metrics.

Those are results for this fixed world, policy, adapter, and Topaz version. They
do not establish general Topaz correctness, production security, or benchmark
coverage beyond the stated denominators. Empty and unexercised dimensions remain
explicit rather than being hidden in an overall score. See
[`docs/results.md`](docs/results.md).

## Public projection, not a SynthWorld renderer

`bin/70_visualize.py` produces a self-contained HTML view from public artifacts.
It is experiment-owned visualization and is labeled accordingly. SynthWorld
0.16.0 exposes public projection schemas and canonical serialization; it does
not ship this HTML UI or an `explorer` CLI subcommand.

## Repository map

| path | responsibility |
|---|---|
| `01-source/` | topology, deterministic mapping configuration, generated import |
| `02-synthworld-public/` | digest-indexed public benchmark artifacts |
| `03-topaz-input/` | public-only Topaz model, policies, directory rows, requests |
| `04-topaz-results/` | raw and normalized product responses plus isolation proof |
| `05-submission/` | typed predictions and pre-scoring seal |
| `06-evaluator/` | evaluator artifacts, visible only to owner and scorer |
| `07-reports/` | scoring, negative controls, and machine validation |
| `bin/` | role-specific deterministic workflow stages |

The topology mapping, including every source field that could not be represented
through the released API, is documented in
[`docs/topology-mapping-report.md`](docs/topology-mapping-report.md). Current
limitations are collected in [`docs/limitations.md`](docs/limitations.md).
