# Public / evaluator isolation design

The point of this experiment is that Topaz's authorization decisions are produced
without ever seeing the answers. That claim is only worth something if you can check
it afterwards. This document says exactly where the line falls, who is allowed to
cross it, how you can verify nobody did — and, in the last two sections, exactly how
strong that verification is. Short version: it is **audited discipline, not an
enforced boundary**. The evaluator tree is on the same filesystem the whole time.

## The six zones

| Zone | Directory | Holds | May read | May be read by |
|---|---|---|---|---|
| 1 | `01-source/` | supplied topology, experiment config, adapter output | — | 2, 3, 7 |
| 2 | `02-synthworld-public/` | SynthWorld **public** artifacts only (13 files) | 1 | 3, 4, 5, 7 |
| 3 | `03-topaz-input/` | Topaz model, Rego policy, directory records, request corpus | 1, 2 | 4 |
| 4 | `04-topaz-results/` | raw + normalized Topaz decisions | 3 | 5 |
| 5 | `05-submission/` | blinded submission + its pre-scoring digest | 2, 4 | 6 |
| 6 | `06-evaluator/` | intact SynthWorld trees (public **and** evaluator), scoring output | everything | nobody |

Zone 7 (`viz/`) is the HTML view; it reads zones 1 and 2 only.

## Why zone 6 holds the intact trees

The released loaders (`load_evaluator_enterprise_directory_rbac_truth`,
`load_evaluator_enterprise_case_inventory`,
`load_evaluator_enterprise_authorization`) do not read an evaluator directory in
isolation. Each one re-loads the sibling **public** tree from the same root and
cross-checks digests, byte-for-byte canonical JSON, and the full file inventory —
`load_evaluator_enterprise_case_inventory` even re-validates every `target_id`
against the public corpus. Splitting `public/` away from `evaluator/` therefore
breaks scoring outright.

So the intact SynthWorld trees live in zone 6, and zone 2 holds a **verified
byte-identical copy of only the public half**. Stage 80 checks that copy against
zone 6 file by file and also asserts that zone 2 contains nothing else. The
isolation guarantee is thus:

> Everything in zone 2 is provably a subset of what SynthWorld itself marks
> `"visibility": "public"`, and stages 30–50 read nothing but zone 2.

## Who is allowed to touch evaluator material

**The generator may. The system under test may not.** These are different roles
and conflating them is the usual way this kind of experiment goes wrong.

- **Stage 20 (`20_build_world.py`) is the world generator.** It necessarily handles
  both halves — it *creates* the answer key. It receives
  `evaluator_canonical_binding_truth` in memory from
  `compile_enterprise_identity_access_universe` and uses it to author the
  deliberately-wrong account bindings that make `binding_status` a real question.
  That is authoring, not cheating.
- **Stages 30, 40 and 50 are the system under test.** They build the Topaz model,
  the Rego policy, the directory records, the request corpus, and the submission.
  They read zone 2 and nothing else.
- **Stage 60 is the evaluator.** It is the only stage that opens zone 6, and it
  refuses to start until it has re-verified the sealed submission digest.

## What is actually enforced, and what is only disciplined

Three independent mechanisms. State them with their limits, because the difference
between "auditable" and "impossible" is the whole value of this section:

1. **Path guard.** `50_build_submission.py` resolves every path it opens and
   raises `ISOLATION VIOLATION` if it resolves inside `06-evaluator/`. Stages 30
   and 40 were built under an explicit instruction never to read zone 6.
   *Limit:* this is a convention inside the same process, with the same filesystem
   privileges. It checks the paths that stage 50 chooses to route through it. It
   constrains stages 30 and 40 not at all.
2. **Digest seal.** Stage 50 writes `05-submission/SUBMISSION-DIGEST.json`
   containing a SHA-256 per submission file plus a combined digest, and records
   `"evaluator_artifacts_read": false`. Stage 60 recomputes all of them and
   **aborts** on any drift. A submission edited after seeing the truth cannot be
   scored without the digest changing.
   *Limit:* the seal is a statement about **time of modification**, not about
   reads. It proves the submission was final before truth was opened by stage 60.
   It cannot prove that nothing in zone 6 was read while the submission was being
   produced. And `"evaluator_artifacts_read": false` is an assertion written by the
   stage itself — not a measurement, and not falsifiable by anything in this design.
3. **Post-hoc leak scan.** Stage 80 greps the HTML view for evaluator vocabulary
   (`birthright_decision`, `intended_decision`, `effective_decision`,
   `final_decision`, `reconciliation`, `binding_status`, `lifecycle_status`,
   `canonical-binding`, the four truth filenames) and fails if any appears.
   *Limit:* it scans the rendered view for leaked *vocabulary*. A decision
   influenced by a truth value would leave no trace in it.

### The structural gap

Stage 20 writes zone 6 **before Topaz ever starts**. The answer key is therefore
present on the same filesystem, readable by the same user, for the entire run of
the system under test. Nothing above changes that; the mechanisms make a read
*auditable*, not *impossible*.

The honest formulation is:

> Zone 6 was not read by stages 30–50 — verifiable by reading four short scripts
> and by `grep -rn "06-evaluator" bin/30_project_topaz.py bin/40_run_topaz.py`,
> which returns nothing. The submission was sealed before zone 6 was opened by the
> evaluator — proved cryptographically. **Neither of those is a guarantee that
> reading zone 6 was impossible, because it was not.**

The fix is structural, not procedural: run stages 30–50 in a container or process
whose filesystem view does not include `06-evaluator/`, so the boundary is enforced
by the kernel instead of by the author. Everything else in this design already
survives that change unaltered — zone 2 is a self-contained public copy and is the
only input those stages take. Doing it is a Phase 3 change and is not claimed here.

## What is deliberately public — and why that is not a leak

Two things look like answers but are not:

- **`abac-state.json` / `abac-intent.json` are public**, and the ABAC deny rules
  are scoped to explicit `cell_ids`. So the ABAC guard verdict *is* publicly
  derivable. That is correct: policy is public, truth is not. A PDP is always
  told the policy. What remains genuinely hidden is the RBAC derivation over the
  directory graph, the account-binding gate, and the whole B/I/E/F truth.
- **`directory-rbac-kernel.json` is public and contains
  `account_observations[].observed_principal_id`** — the *observed*, possibly
  wrong binding. The *canonical* binding lives only in
  `evaluator/canonical-binding-truth.json`. That pair is precisely the
  `binding_status ∈ {matches_canonical, mismatch, missing}` question, and the
  public side is the input a real system would have.

## What the public side genuinely cannot know

Stated up front so the scores are read correctly, not excused afterwards:

- **`intended_decision`.** The RBAC intent overlay is an experiment-owned input to
  `compile_enterprise_directory_rbac_truth` and is exported to *neither* tree. No
  public artifact contains it. The submission predicts `intended == effective`;
  the resulting metric measures declared-vs-intended drift in the world, not
  policy accuracy.
- **`effective_path_ids`.** These are internal SynthWorld derivation-path
  identifiers that appear in no public artifact. Submitted empty.
- **The account binding gate.** A consumer can see the *observed* binding but has
  nothing to compare it against, so it cannot detect a mismatch. The policy does
  not guess; it accepts the loss on that cohort — `binding_gate_pass := true` for
  every subject. In this world the loss turned out to be zero, because all 15
  mismatch cells had already lost their RBAC derivation, so the gate never fires
  and nothing here tests it. See `docs/results.md` §7.2.

These three are reported in a separate `not_publicly_winnable` block in the
scoring report rather than mixed into the headline numbers.

## Verifying the claim yourself

```bash
# zone 2 is exactly the public half of zone 6, and nothing more
python3 bin/80_validate.py

# the submission was sealed before scoring ran
cat 05-submission/SUBMISSION-DIGEST.json
python3 - <<'EOF'
import hashlib, json, pathlib
m = json.loads(pathlib.Path("05-submission/SUBMISSION-DIGEST.json").read_text())
for name, want in m["sha256"].items():
    got = hashlib.sha256(pathlib.Path("05-submission", name).read_bytes().rstrip(b"\n")).hexdigest()
    print(("OK  " if got == want else "DRIFT"), name, got)
EOF

# no stage that feeds Topaz mentions the evaluator zone
grep -rn "06-evaluator" bin/30_project_topaz.py bin/40_run_topaz.py bin/70_visualize.py || echo "clean"
```
