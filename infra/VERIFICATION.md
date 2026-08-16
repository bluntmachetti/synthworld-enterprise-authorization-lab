# Britannia Phase 2 — Topaz Infrastructure Verification

**Date:** 2026-08-16 · **Host:** Linux amd64, Docker 29.5.2, Compose v5.1.4
**Image:** `ghcr.io/aserto-dev/topaz:0.33.16@sha256:835868c04bdd7129127ea43642ffff7363d0bd26d5e1a37631fa881431054360`
**Compose project:** `britannia-phase2`

All output below is pasted verbatim from the actual run. Nothing is paraphrased.

---

## 1. Host port mapping

**No remapping was required — every Topaz default port was free.**

| Host (127.0.0.1) | Container | Service |
|---|---|---|
| `8282` | `8282` | authorizer gRPC |
| `8383` | `8383` | authorizer REST gateway (`/api/v2/...`) |
| `9292` | `9292` | directory gRPC |
| `9393` | `9393` | directory REST gateway (`/api/v3/...`) |
| `9494` | `9494` | health (gRPC health protocol — not HTTP) |
| `9696` | `9696` | Prometheus metrics |

### Evidence the ports were free before starting

Container-level (`docker ps --format '{{.Names}}\t{{.Ports}}'`):

```
arena-app	0.0.0.0:8765->8000/tcp, [::]:8765->8000/tcp
arena-redis	127.0.0.1:6380->6379/tcp
arena-postgres	127.0.0.1:5433->5432/tcp
aftershock-deploy-aftershock-1	0.0.0.0:8788->8788/tcp
aftershock-deploy-autoheal-1	
k12-staging-ollama-1	192.168.4.153:11434->11434/tcp
aftershock-deploy-caddy-1	0.0.0.0:80->80/tcp, [::]:80->80/tcp, 0.0.0.0:443->443/tcp, [::]:443->443/tcp, 443/udp, 2019/tcp
```

Host-level (`ss -tlnp | grep -E ':(8282|8383|9292|9393|9494|9696)\b'`):

```
NONE OF 8282/8383/9292/9393/9494/9696 ARE LISTENING
```

Full host listener set before start (`ss -tln`), for the record:

```
0.0.0.0:22        0.0.0.0:27500     0.0.0.0:443       0.0.0.0:80
0.0.0.0:8765      0.0.0.0:8788      127.0.0.1:18001   127.0.0.1:18434
127.0.0.1:5433    127.0.0.1:6380    127.0.0.53%lo:53  127.0.0.54:53
172.30.2.1:18001  172.30.2.1:18434  192.168.4.153:11434
[::]:22           [::]:443          [::]:80           [::]:8765
```

Live published ports once running:

```
$ docker ps --filter "name=britannia-phase2-topaz" --format '{{.Names}} {{.Status}} {{.Ports}}'
britannia-phase2-topaz Up 39 seconds 127.0.0.1:8282->8282/tcp, 127.0.0.1:8383->8383/tcp, 127.0.0.1:9292->9292/tcp, 127.0.0.1:9393->9393/tcp, 127.0.0.1:9494->9494/tcp, 127.0.0.1:9696->9696/tcp
```

Every publish is bound to `127.0.0.1` only — the authorizer runs anonymous and is not reachable off-host.

---

## 2. Startup — `bin/topaz_up.sh`

```
$ bash /home/kademolu/Projects/agent-auth-2/bin/topaz_up.sh
==> compose project : britannia-phase2
==> infra dir       : /home/kademolu/Projects/agent-auth-2/infra
 Network britannia-phase2_default  Creating
 Network britannia-phase2_default  Created
 Volume britannia-phase2_topaz-db  Creating
 Volume britannia-phase2_topaz-db  Created
 Container britannia-phase2-topaz  Creating
 Container britannia-phase2-topaz  Created
 Container britannia-phase2-topaz  Starting
 Container britannia-phase2-topaz  Started
==> waiting for both gateways to return 200 ...
==> ready after 2 attempt(s)  (directory=200 authorizer=200)

Topaz is up.

  Authorizer REST gateway : http://127.0.0.1:8383      (/api/v2/authz/is, /api/v2/policies, /api/v2/info)
  Directory  REST gateway : http://127.0.0.1:9393      (/api/v3/directory/...)
  Authorizer gRPC         : 127.0.0.1:8282
  Directory  gRPC         : 127.0.0.1:9292
  Health (gRPC protocol)  : 127.0.0.1:9494
  Metrics                 : http://127.0.0.1:9696

  Policy path  : britannia.authz
  Decision     : allowed

  Tear down with: bin/topaz_down.sh   (destroys the britannia-phase2_topaz-db volume)
```

Ready after **2 attempts (~2 s)** from a cold, empty volume — matching the reference's measurement exactly.

### Idempotency

Second invocation against the already-running stack reconciled instead of recreating (note `Running`, not `Recreating`, and the preserved 39 s uptime above):

```
$ bash /home/kademolu/Projects/agent-auth-2/bin/topaz_up.sh
==> compose project : britannia-phase2
==> infra dir       : /home/kademolu/Projects/agent-auth-2/infra
 Container britannia-phase2-topaz  Running
==> waiting for both gateways to return 200 ...
==> ready after 1 attempt(s)  (directory=200 authorizer=200)
```

---

## 3. Policy bundle loaded and compiled — `GET /api/v2/policies`

```bash
curl -s -o policies.json -w '%{http_code}\n' http://127.0.0.1:8383/api/v2/policies
```

HTTP status:

```
200
```

Full response body:

```json
{
  "result": [
    {
      "id": "/bundle/bundle/britannia/authz.rego",
      "raw": "# PLACEHOLDER POLICY — Britannia Phase 2.\n#\n# Purpose at this stage: prove the local bundle mounts, loads, and COMPILES.\n# Compilation is confirmed by a non-empty `ast` field for this file in\n# `GET /api/v2/policies` (see topaz-reference.md §7.5).\n#\n# The real authorization logic is authored in a later stage; do not build on the\n# shape of this rule beyond the package path and decision name.\n#\n#   policy path (policy_context.path) : britannia.authz\n#   decision name (policy_context.decisions[]) : allowed\n#\n# Identity style: IDENTITY_TYPE_MANUAL. Per §9.1, `input.user` is `{}` for MANUAL\n# identities — no directory lookup happens — so the subject is taken entirely from\n# `resource_context`, which lands verbatim on `input.resource`.\n\npackage britannia.authz\n\nimport rego.v1\n\ndefault allowed := false\n\n# Fully explicit ReBAC check: every tuple field comes from resource_context.\nallowed if {\n\tds.check({\n\t\t\"object_type\": input.resource.object_type,\n\t\t\"object_id\": input.resource.object_id,\n\t\t\"relation\": input.resource.relation,\n\t\t\"subject_type\": input.resource.subject_type,\n\t\t\"subject_id\": input.resource.subject_id,\n\t})\n}\n",
      "package_path": "data.britannia.authz",
      "ast": "package britannia.authz\n\ndefault allowed := false\nallowed = true if { __local0__ = input.resource.object_id; __local1__ = input.resource.object_type; __local2__ = input.resource.relation; __local3__ = input.resource.subject_id; __local4__ = input.resource.subject_type; ds.check({\"object_id\": __local0__, \"object_type\": __local1__, \"relation\": __local2__, \"subject_id\": __local3__, \"subject_type\": __local4__}) }"
    }
  ]
}
```

Field extraction:

```
id           = /bundle/bundle/britannia/authz.rego
package_path = data.britannia.authz
ast present  = True | len = 412
```

**The `ast` field is present and non-empty (412 chars), and `ds.check` appears in it resolved as a
built-in with its arguments hoisted to `__local*__` temporaries.** Per reference §7.5 this proves the
bundle was found, parsed, and compiled — not merely mounted.

---

## 4. Version — `GET /api/v2/info`

```bash
curl -s http://127.0.0.1:8383/api/v2/info
```

```json
{
  "version": "0.33.16",
  "commit": "81b8405",
  "date": "2026-08-05T09:58:34Z",
  "os": "linux",
  "arch": "amd64"
}
```

Version is **0.33.16**, commit `81b8405` — byte-identical to the reference's recorded output, confirming
the pinned digest resolved to the intended build.

---

## 5. Throwaway manifest + directory round trip

Throwaway probe manifest (`probe-manifest.yaml`, written to scratch, **not** committed to the repo):

```yaml
# yaml-language-server: $schema=https://www.topaz.sh/schema/manifest.json
---
model:
  version: 3

types:
  user: {}

  ledger:
    relations:
      owner: user
    permissions:
      can_read: owner
```

### 5.1 Install the manifest

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST http://127.0.0.1:9393/api/v3/directory/manifest \
  -H 'Content-Type: application/yaml' \
  --data-binary @probe-manifest.yaml
```

```

HTTP 200
```

(Empty body, HTTP 200 — as documented in §5.2.)

### 5.2 Create objects

```bash
curl -s -X POST http://127.0.0.1:9393/api/v3/directory/object \
  -H 'Content-Type: application/json' \
  -d '{"object":{"type":"user","id":"probe.user@britannia.test","display_name":"Probe User"}}'
```

```json
{
  "result": {
    "type": "user",
    "id": "probe.user@britannia.test",
    "display_name": "Probe User",
    "properties": {},
    "created_at": "2026-08-15T23:42:00.607952830Z",
    "updated_at": "2026-08-15T23:42:00.607952830Z",
    "etag": "7697773948003554942"
  }
}
```

```bash
curl -s -X POST http://127.0.0.1:9393/api/v3/directory/object \
  -H 'Content-Type: application/json' \
  -d '{"object":{"type":"ledger","id":"ledger-001","display_name":"Probe Ledger"}}'
```

```json
{
  "result": {
    "type": "ledger",
    "id": "ledger-001",
    "display_name": "Probe Ledger",
    "properties": {},
    "created_at": "2026-08-15T23:42:00.621838023Z",
    "updated_at": "2026-08-15T23:42:00.621838023Z",
    "etag": "5264596908333891092"
  }
}
```

### 5.3 Create the relation

```bash
curl -s -X POST http://127.0.0.1:9393/api/v3/directory/relation \
  -H 'Content-Type: application/json' \
  -d '{"relation":{"object_type":"ledger","object_id":"ledger-001","relation":"owner","subject_type":"user","subject_id":"probe.user@britannia.test"}}'
```

```json
{
  "result": {
    "object_type": "ledger",
    "object_id": "ledger-001",
    "relation": "owner",
    "subject_type": "user",
    "subject_id": "probe.user@britannia.test",
    "subject_relation": "",
    "created_at": "2026-08-15T23:42:00.635278054Z",
    "updated_at": "2026-08-15T23:42:00.635278054Z",
    "etag": "3477447659130887772"
  }
}
```

Relations were written over REST per §6.2 — the `topaz directory import` CLI path (§12.4) was
deliberately not used.

---

## 6. Real authorization decisions — `POST /api/v2/authz/is`

Both calls use `IDENTITY_TYPE_MANUAL`, so `input.user` is `{}` and the subject comes entirely from
`resource_context` (§9.1) — exactly what the placeholder policy reads.

### 6.1 TRUE — the owner asks `can_read`

```bash
curl -s -X POST http://127.0.0.1:8383/api/v2/authz/is \
  -H 'Content-Type: application/json' \
  -d '{
    "identity_context": {"identity": "probe.user@britannia.test", "type": "IDENTITY_TYPE_MANUAL"},
    "policy_context": {"path": "britannia.authz", "decisions": ["allowed"]},
    "resource_context": {"object_type":"ledger","object_id":"ledger-001","relation":"can_read","subject_type":"user","subject_id":"probe.user@britannia.test"}
  }'
```

```json
{
  "decisions": [
    {
      "decision": "allowed",
      "is": true
    }
  ]
}
```

### 6.2 FALSE — an unrelated user asks `can_read` on the same ledger

```bash
curl -s -X POST http://127.0.0.1:8383/api/v2/authz/is \
  -H 'Content-Type: application/json' \
  -d '{
    "identity_context": {"identity": "intruder@britannia.test", "type": "IDENTITY_TYPE_MANUAL"},
    "policy_context": {"path": "britannia.authz", "decisions": ["allowed"]},
    "resource_context": {"object_type":"ledger","object_id":"ledger-001","relation":"can_read","subject_type":"user","subject_id":"intruder@britannia.test"}
  }'
```

```json
{
  "decisions": [
    {
      "decision": "allowed",
      "is": false
    }
  ]
}
```

The only difference between the two requests is the subject. The decision flips with the directory
data, which proves the whole chain is live: bundle → OPA compile → `ds.check` built-in → directory
reader → relation tuple.

---

## 7. Teardown — `bin/topaz_down.sh`

Volume before:

```
$ docker volume ls --filter 'name=britannia-phase2' --format '{{.Name}}'
britannia-phase2_topaz-db
```

```
$ bash /home/kademolu/Projects/agent-auth-2/bin/topaz_down.sh
==> tearing down compose project 'britannia-phase2' (with volumes)
 Container britannia-phase2-topaz  Stopping
 Container britannia-phase2-topaz  Stopped
 Container britannia-phase2-topaz  Removing
 Container britannia-phase2-topaz  Removed
 Network britannia-phase2_default  Removing
 Volume britannia-phase2_topaz-db  Removing
 Volume britannia-phase2_topaz-db  Removed
 Network britannia-phase2_default  Removed
==> down. volume britannia-phase2_topaz-db removed; next start is a clean slate.
```

Volume after — **empty output, the volume is gone**:

```
$ docker volume ls --filter 'name=britannia-phase2' --format '{{.Name}}'
[exit of ls above: 0]
```

Ports released:

```
$ ss -tln | grep -E ':(8282|8383|9292|9393|9494|9696)\b'
all six topaz ports released
```

---

## 8. Blast-radius check — nothing else was touched

Pre-existing containers after the full up/down cycle, uptimes intact:

```
$ docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
arena-app	Up 10 days (healthy)	0.0.0.0:8765->8000/tcp, [::]:8765->8000/tcp
arena-redis	Up 3 weeks (healthy)	127.0.0.1:6380->6379/tcp
arena-postgres	Up 3 weeks (healthy)	127.0.0.1:5433->5432/tcp
aftershock-deploy-aftershock-1	Up 7 weeks (healthy)	0.0.0.0:8788->8788/tcp
aftershock-deploy-autoheal-1	Up 7 weeks (healthy)	
k12-staging-ollama-1	Up 8 weeks	192.168.4.153:11434->11434/tcp
aftershock-deploy-caddy-1	Up 2 months	0.0.0.0:80->80/tcp, [::]:80->80/tcp, 0.0.0.0:443->443/tcp, [::]:443->443/tcp, 443/udp, 2019/tcp
```

Unrelated pre-existing volumes from an earlier, separate `britannia-topaz-authz` project also survived
(`down -v` was scoped to `-p britannia-phase2` only):

```
$ docker volume ls --filter 'name=britannia-topaz-authz' --format '{{.Name}}'
britannia-topaz-authz_topaz-certs
britannia-topaz-authz_topaz-db
britannia-topaz-authz_topaz-decisions
```

---

## 9. Results summary

| # | Check | Result |
|---|---|---|
| 1 | All six default ports free; no remap needed | PASS |
| 2 | `topaz_up.sh` starts stack, both gateways 200 in ~2 s | PASS |
| 3 | `topaz_up.sh` idempotent (reconciles, no recreate) | PASS |
| 4 | `topaz_up.sh` prints resolved base URLs | PASS |
| 5 | `GET /api/v2/policies` → 200 | PASS |
| 6 | Response contains `britannia.authz` with non-empty `ast` | PASS (412 chars) |
| 7 | `GET /api/v2/info` reports `0.33.16` | PASS |
| 8 | `POST /api/v3/directory/manifest` → 200 | PASS |
| 9 | Object + relation created over REST | PASS |
| 10 | `POST /api/v2/authz/is` returns `true` | PASS |
| 11 | `POST /api/v2/authz/is` returns `false` | PASS |
| 12 | `topaz_down.sh` removes the named volume | PASS |
| 13 | No pre-existing container or volume touched | PASS |

**Deviations from the reference: none of substance.** The only differences are the intended
project-specific renames — bundle root is `infra/policy/` rather than `bundle/` (still mounted at
`/bundle`), the OPA `roots` are `["britannia"]`, and the package is `britannia.authz` rather than
`agentauth.check`. Compose additionally carries `name:`, `container_name:` and `restart:` for project
isolation; none of these affect Topaz behaviour. The verified §4.3 config was copied verbatim in
structure, including the mandatory explicit `insecure: false` beside `no_tls: true` (§12.1).
