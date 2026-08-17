#!/usr/bin/env python3
"""Project the public 0.16 adversarial authorization pack into Topaz requests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from synthworld.enterprise.authorization.adversarial import (
    EnterpriseAdversarialAuthorizationPublicV1,
    resolve_adversarial_credential,
)
from synthworld.enterprise.consumer import canonical_enterprise_model_bytes

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_PATH = ROOT / "02-synthworld-public/adversarial/enterprise-adversarial-authorization.json"
OUT = ROOT / "03-topaz-input/adversarial"
POLICY_PATH = ROOT / "03-topaz-input/policy/adversarial/authz.rego"

POLICY = r"""# Public-fact-only policy for the SynthWorld adversarial authorization pack.
package adversarial.authz

import rego.v1

default allow := false

allow if {
    principal := principal_by_id(input.resource.resolved_principal_id)
    resource := resource_by_id(input.resource.attempt.resource_id)
    grant_allows(principal, resource)
    tenant_allowed(principal, resource)
    clearance_rank(principal.clearance) >= clearance_rank(resource.classification)
}

principal_by_id(principal_id) := principal if {
    some principal in input.resource.public.principals
    principal.principal_id == principal_id
}

resource_by_id(resource_id) := resource if {
    some resource in input.resource.public.resources
    resource.resource_id == resource_id
}

grant_allows(principal, resource) if {
    attempt := input.resource.attempt
    some grant in input.resource.public.grants
    grant.principal_id == principal.principal_id
    grant.resource_kind == resource.resource_kind
    grant.action == attempt.action
    source_allowed(grant.source)
    some scope in grant.allowed_scopes
    scope == attempt.requested_scope
    grant.valid_from_tick <= attempt.tick
    attempt.tick < grant.valid_until_tick
}

source_allowed("rbac") if {
    input.resource.public.policy.authority_combination == "rbac_or_rebac"
}

source_allowed("rebac") if {
    input.resource.public.policy.authority_combination == "rbac_or_rebac"
}

tenant_allowed(principal, resource) if {
    not tenant_deny_match(principal, resource)
    tenant_allow_match(principal, resource)
}

tenant_allowed(principal, resource) if {
    not tenant_deny_match(principal, resource)
    not tenant_rule_match(principal, resource)
    input.resource.public.policy.default_tenant_decision == "allow"
}

tenant_deny_match(principal, resource) if {
    some rule in input.resource.public.policy.tenant_rules
    rule.effect == "deny"
    tenant_comparison_matches(rule.operator, principal.tenant_id, resource.tenant_id)
}

tenant_allow_match(principal, resource) if {
    some rule in input.resource.public.policy.tenant_rules
    rule.effect == "allow"
    tenant_comparison_matches(rule.operator, principal.tenant_id, resource.tenant_id)
}

tenant_rule_match(principal, resource) if {
    some rule in input.resource.public.policy.tenant_rules
    tenant_comparison_matches(rule.operator, principal.tenant_id, resource.tenant_id)
}

tenant_comparison_matches("equals", left, right) if left == right
tenant_comparison_matches("not_equals", left, right) if left != right

clearance_rank("public") := 0
clearance_rank("internal") := 1
clearance_rank("confidential") := 2
clearance_rank("restricted") := 3
"""


def canonical_json(document: object) -> bytes:
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def main() -> int:
    public = EnterpriseAdversarialAuthorizationPublicV1.model_validate_json(
        PUBLIC_PATH.read_bytes()
    )
    public_document = public.model_dump(mode="json")
    OUT.mkdir(parents=True, exist_ok=True)
    POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
    POLICY_PATH.write_text(POLICY, "utf-8")

    requests = []
    for attempt in public.attempts:
        resolved = resolve_adversarial_credential(public, attempt.credential_id)
        requests.append(
            {
                "attempt_id": attempt.attempt_id,
                "resolved_principal_id": resolved,
                "body": {
                    "identity_context": {
                        "identity": resolved or attempt.presented_principal_id,
                        "type": "IDENTITY_TYPE_MANUAL",
                    },
                    "policy_context": {
                        "path": "adversarial.authz",
                        "decisions": ["allow"],
                    },
                    "resource_context": {
                        "attempt": attempt.model_dump(mode="json"),
                        "resolved_principal_id": resolved,
                        "public": public_document,
                    },
                },
            }
        )
    with (OUT / "authz-requests.jsonl").open("wb") as output:
        for row in sorted(requests, key=lambda item: item["attempt_id"]):
            output.write(canonical_json(row))

    public_bytes = canonical_enterprise_model_bytes(public)
    summary = {
        "schema_version": "synthworld-enterprise-authorization-topaz-projection/1",
        "attempts": len(requests),
        "public_sha256": hashlib.sha256(public_bytes).hexdigest(),
        "policy_sha256": hashlib.sha256(POLICY.encode("utf-8")).hexdigest(),
        "policy_path": "adversarial.authz",
        "decisions": ["allow"],
    }
    (OUT / "projection-summary.json").write_bytes(canonical_json(summary))
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
