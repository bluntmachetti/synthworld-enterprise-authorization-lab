#!/usr/bin/env python3
"""Stage 10 - map britannia_global_bank_topology.yaml onto a SynthWorld
EnterpriseIdentityAccessImportV1 document.

ZONE: reads 01-source, writes 01-source/generated. Touches no SynthWorld
artifact and no evaluator artifact. The only SynthWorld dependency is the
released package's public import schema, which this stage does not import -
validation happens in stage 20 via the released CLI.

Determinism: output is a pure function of (topology bytes, experiment.yaml
bytes). Every collection is emitted in sorted key order; no dict iteration
order, no randomness, no clock.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# The mapping ledger. Every topology field path the adapter reads or knowingly
# declines to read is recorded here so the mapping report can be generated from
# the same source of truth the adapter actually uses.
# --------------------------------------------------------------------------
DIRECT = "represented_directly"
TRANSFORMED = "documented_transformation"
METADATA = "experiment_metadata"
NOT_REPRESENTABLE = "not_representable"


class Ledger:
    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []
        self._seen: set[str] = set()

    def note(self, path: str, classification: str, target: str, rationale: str) -> None:
        if path in self._seen:
            return
        self._seen.add(path)
        self.rows.append(
            {
                "topology_field": path,
                "classification": classification,
                "synthworld_target": target,
                "rationale": rationale,
            }
        )

    def dump(self) -> list[dict[str, str]]:
        return sorted(self.rows, key=lambda r: r["topology_field"])


def slug(value: str) -> str:
    """Deterministic, collision-resistant slug for logical keys."""
    s = value.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "x"


def load_yaml(path: Path) -> Any:
    with path.open("rb") as fh:
        return yaml.safe_load(fh)


# --------------------------------------------------------------------------


class Mapper:
    def __init__(self, topology: dict, config: dict, ledger: Ledger) -> None:
        self.t = topology
        self.c = config
        self.L = ledger
        # Real topology pairs that cannot be declared because they cross a legal
        # entity boundary. Populated during atom-rule and allocation building and
        # consumed by the cross-boundary denial request set.
        self.cross_tenant_ownership: list[dict] = []
        self.cross_tenant_dependency: list[dict] = []

        self.region_to_tenant: dict[str, str] = dict(
            config["tenancy"]["region_to_tenant"]
        )
        self.vendor_tenant: str = config["tenancy"]["vendor_tenant"]

        self.services = {s["name"]: s for s in topology["services"]}
        self.teams = {t["name"]: t for t in topology["teams"]}
        self.domains = {d["name"]: d for d in topology["domains"]}
        self.vendors = {v["name"]: v for v in topology["vendors"]}

        self._validate_regions()

        # derived indexes
        self.service_primary_domain = self._index_service_primary_domain()
        self.service_home_tenant = self._index_service_home_tenant()
        self.service_deploy_count = Counter(
            d["service"] for d in topology["service_deployments"]
        )
        self.team_tenants = self._index_team_tenants()
        self.team_parent_division = self._index_team_parent_division()

    # ---------------- validation ----------------

    def _validate_regions(self) -> None:
        declared = set(self.t["organisation"]["regions"])
        mapped = set(self.region_to_tenant)
        missing = declared - mapped
        if missing:
            raise SystemExit(
                f"experiment.yaml tenancy.region_to_tenant is missing regions: "
                f"{sorted(missing)}"
            )
        used = {r["region"] for r in self.t["team_locations"]} | {
            d["region"] for d in self.t["service_deployments"]
        }
        unknown = used - mapped
        if unknown:
            raise SystemExit(f"unmapped regions referenced by rows: {sorted(unknown)}")

    # ---------------- indexes ----------------

    def _index_service_primary_domain(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for row in sorted(
            self.t["service_domains"], key=lambda r: (r["service"], r["domain"])
        ):
            if row.get("is_primary") and row["service"] not in out:
                out[row["service"]] = row["domain"]
        # services with no primary domain fall back to first domain alphabetically
        for row in sorted(
            self.t["service_domains"], key=lambda r: (r["service"], r["domain"])
        ):
            out.setdefault(row["service"], row["domain"])
        self.L.note(
            "service_domains[].is_primary",
            DIRECT,
            "resource_set owner division selection",
            "Selects which domain division owns the service's resource set.",
        )
        self.L.note(
            "service_domains[].service",
            DIRECT,
            "resource_set -> unit edge",
            "Foreign key into services[].name.",
        )
        self.L.note(
            "service_domains[].domain",
            DIRECT,
            "unit(division) reference",
            "Foreign key into domains[].name.",
        )
        return out

    def _index_service_home_tenant(self) -> dict[str, str]:
        """A service's home tenant is the tenant of its primary deployment region."""
        primary: dict[str, str] = {}
        fallback: dict[str, str] = {}
        for row in sorted(
            self.t["service_deployments"],
            key=lambda r: (r["service"], r["deployment_type"], r["region"]),
        ):
            svc, region = row["service"], row["region"]
            tenant = self.region_to_tenant[region]
            if row["deployment_type"] == "primary":
                primary.setdefault(svc, tenant)
            fallback.setdefault(svc, tenant)
        self.L.note(
            "service_deployments[].deployment_type",
            TRANSFORMED,
            "service home tenant selection + resource_set.instance_count",
            "deployment_type=primary picks the service's home legal entity; the "
            "row count becomes instance_count. The four deployment types "
            "(primary/failover/read_replica/edge_cache) have no SynthWorld "
            "construct and are otherwise experiment metadata.",
        )
        self.L.note(
            "service_deployments[].region",
            TRANSFORMED,
            "tenant assignment",
            "Region -> legal entity via experiment.yaml tenancy.region_to_tenant.",
        )
        self.L.note(
            "service_deployments[].service",
            DIRECT,
            "resource_set reference",
            "Foreign key into services[].name.",
        )
        self.L.note(
            "service_deployments[].infrastructure_provider",
            METADATA,
            "-",
            "Hosting provider has no SynthWorld construct; retained in the "
            "mapping report and the HTML view only.",
        )
        out = dict(fallback)
        out.update(primary)
        # The three service_type=external rows (SWIFT, card scheme and SEPA
        # clearing networks) have no service_deployments row at all, which is
        # semantically correct: the bank does not deploy them. They still need a
        # home tenant, so they inherit the tenant in which their primary owning
        # team has the largest regional headcount. Deterministic, tie-broken by
        # region name ascending.
        missing = sorted(set(self.services) - set(out))
        if missing:
            head: dict[tuple[str, str], int] = {}
            for row in self.t["team_locations"]:
                head[(row["team"], row["region"])] = int(row["headcount_in_region"])
            for service in missing:
                team = self.primary_owner_team(service)
                regions = sorted(
                    (
                        (-head[(team, r["region"])], r["region"])
                        for r in self.t["team_locations"]
                        if r["team"] == team
                    )
                )
                if not regions:
                    raise SystemExit(
                        f"service {service!r} has no deployment and its primary "
                        f"owner {team!r} has no location; cannot assign a tenant"
                    )
                out[service] = self.region_to_tenant[regions[0][1]]
            self.L.note(
                "services[].service_type=external",
                TRANSFORMED,
                "home tenant fallback",
                "The three external network services (card-scheme-network, "
                "swift-network, uk-sepa-clearing-network) have no "
                "service_deployments row. They inherit the tenant where their "
                "primary owning team has the largest regional headcount, and "
                "their resource_set instance_count is forced to 1.",
            )
        return out

    def _index_team_tenants(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = defaultdict(set)
        for row in self.t["team_locations"]:
            out[row["team"]].add(self.region_to_tenant[row["region"]])
        return dict(out)

    def _index_team_parent_division(self) -> dict[str, str]:
        """Team's parent division = plurality primary-owned service domain."""
        counts: dict[str, Counter] = defaultdict(Counter)
        for row in sorted(
            self.t["service_ownerships"], key=lambda r: (r["team"], r["service"])
        ):
            if row["ownership_type"] != "primary":
                continue
            dom = self.service_primary_domain.get(row["service"])
            if dom:
                counts[row["team"]][dom] += 1
        out: dict[str, str] = {}
        for team in sorted(self.teams):
            c = counts.get(team)
            if c:
                # deterministic tie-break: highest count, then domain name ascending
                out[team] = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            else:
                # teams owning nothing primary: attach to the alphabetically first
                # domain of any service they touch, else first domain overall
                touched = sorted(
                    {
                        self.service_primary_domain.get(r["service"], "")
                        for r in self.t["service_ownerships"]
                        if r["team"] == team
                    }
                    - {""}
                )
                out[team] = touched[0] if touched else sorted(self.domains)[0]
        return out

    # ---------------- key helpers ----------------

    def org_key(self, tenant: str) -> str:
        return f"org-{tenant}"

    def division_key(self, tenant: str, domain: str) -> str:
        return f"unit-{tenant}-div-{slug(domain)}"

    def team_unit_key(self, tenant: str, team: str) -> str:
        return f"unit-{tenant}-team-{slug(team)}"

    def vendor_unit_key(self, vendor: str) -> str:
        return f"unit-{self.vendor_tenant}-vendor-{slug(vendor)}"

    def population_key(self, team: str, region: str) -> str:
        return f"pop-wf-{slug(team)}-{slug(region)}"

    def workload_population_key(self, service: str) -> str:
        return f"pop-wl-{slug(service)}"

    def supplier_population_key(self, vendor: str) -> str:
        return f"pop-sup-{slug(vendor)}"

    def resource_key(self, service: str) -> str:
        return f"rs-{slug(service)}"

    def role_key(self, tenant: str, role: str) -> str:
        return f"role-{tenant}-{slug(role)}"

    def group_key(self, tenant: str, name: str) -> str:
        return f"grp-{tenant}-{slug(name)}"

    # ---------------- builders ----------------

    def _salt(self) -> str:
        """Released importer requires 64 lowercase hex chars; derive it from the
        configured phrase so the constant is reproducible and auditable."""
        det = self.c["determinism"]
        derived = hashlib.sha256(
            det["id_namespace_salt_phrase"].encode("utf-8")
        ).hexdigest()
        declared = det.get("id_namespace_salt")
        if declared and declared != derived:
            raise SystemExit(
                "experiment.yaml determinism.id_namespace_salt does not match "
                f"sha256(phrase); expected {derived}"
            )
        return derived

    def build(self) -> dict:
        blueprint = {
            "schema_version": "1.0.0",
            "blueprint_key": self.c["determinism"]["blueprint_key"],
            "id_namespace_salt": self._salt(),
            "tenants": self.build_tenants(),
            "organisations": self.build_organisations(),
            "units": self.build_units(),
            "populations": self.build_populations(),
            "groups": self.build_groups(),
            "roles": self.build_roles(),
            "resource_sets": self.build_resource_sets(),
            "principal_access_atom_rules": self.build_atom_rules(),
        }
        ext = self.build_iam_extension()
        state = self.build_directory_state()
        return {
            "schema_version": "1.0.0",
            "blueprint": blueprint,
            "iam_universe_extension": ext,
            "directory_rbac_state": state,
        }

    def tenants(self) -> list[str]:
        return sorted(set(self.region_to_tenant.values())) + [self.vendor_tenant]

    def build_tenants(self) -> list[dict]:
        self.L.note(
            "organisation.metadata.legal_entity_footprint",
            TRANSFORMED,
            "blueprint.tenants[]",
            "The four legal entities become the four bank authorization tenants. "
            "The prose description of each entity is not representable and is "
            "kept as experiment metadata.",
        )
        self.L.note(
            "organisation.regions",
            TRANSFORMED,
            "tenant assignment key",
            "Each region is assigned to a legal-entity tenant by "
            "experiment.yaml tenancy.region_to_tenant. SynthWorld has no "
            "geographic construct, so region itself is not representable.",
        )
        self.L.note(
            "vendors[].name",
            TRANSFORMED,
            "blueprint.tenants[vendor-external] + units + supplier populations",
            "Third parties are modelled as one external tenant containing a "
            "department unit per data-processor vendor.",
        )
        return [{"key": t} for t in self.tenants()]

    def build_organisations(self) -> list[dict]:
        self.L.note(
            "organisation.name",
            METADATA,
            "-",
            "SynthWorld organisations are keyed logically; the display name is "
            "recorded in the mapping report and HTML view.",
        )
        return [{"key": self.org_key(t), "tenant_key": t} for t in self.tenants()]

    def build_units(self) -> list[dict]:
        units: list[dict] = []
        bank_tenants = sorted(set(self.region_to_tenant.values()))
        # divisions: every domain exists in every bank tenant
        for tenant in bank_tenants:
            for domain in sorted(self.domains):
                units.append(
                    {
                        "key": self.division_key(tenant, domain),
                        "tenant_key": tenant,
                        "organisation_key": self.org_key(tenant),
                        "unit_kind": self.c["units"]["domain_unit_kind"],
                        "parent_unit_key": None,
                    }
                )
        # teams: only in tenants where the team actually has a location
        for team in sorted(self.teams):
            for tenant in sorted(self.team_tenants.get(team, set())):
                units.append(
                    {
                        "key": self.team_unit_key(tenant, team),
                        "tenant_key": tenant,
                        "organisation_key": self.org_key(tenant),
                        "unit_kind": self.c["units"]["team_unit_kind"],
                        "parent_unit_key": self.division_key(
                            tenant, self.team_parent_division[team]
                        ),
                    }
                )
        # vendor departments
        for vendor in sorted(self.vendors):
            if not self.vendors[vendor].get("data_processor"):
                continue
            units.append(
                {
                    "key": self.vendor_unit_key(vendor),
                    "tenant_key": self.vendor_tenant,
                    "organisation_key": self.org_key(self.vendor_tenant),
                    "unit_kind": self.c["units"]["vendor_unit_kind"],
                    "parent_unit_key": None,
                }
            )
        self.L.note(
            "domains[].name",
            DIRECT,
            "unit(kind=division)",
            "Each business domain becomes a division unit, replicated per tenant.",
        )
        self.L.note(
            "domains[].parent_domain",
            NOT_REPRESENTABLE,
            "-",
            "The field exists but is null for all 7 domains, so no domain "
            "hierarchy can be derived. The unit tree is consequently two levels "
            "(division -> team), not three. Nothing is discarded because nothing "
            "is present.",
        )
        self.L.note(
            "domains[].description",
            METADATA,
            "-",
            "Free text; no SynthWorld construct. Surfaced in the HTML view.",
        )
        self.L.note(
            "teams[].name",
            DIRECT,
            "unit(kind=team)",
            "Each team becomes a team unit in every tenant it has a location in.",
        )
        self.L.note(
            "teams[].team_type",
            METADATA,
            "-",
            "product/platform/sre/security/shared_services has no SynthWorld "
            "unit-kind analogue (UnitKind is division|department|team only).",
        )
        self.L.note(
            "teams[].key_capabilities",
            METADATA,
            "-",
            "Free-text capability list; no SynthWorld construct.",
        )
        self.L.note(
            "vendors[].data_processor",
            TRANSFORMED,
            "vendor unit inclusion predicate",
            "Only data-processor vendors get a unit and supplier population, "
            "because only they plausibly hold principals touching bank data.",
        )
        return units

    def build_populations(self) -> list[dict]:
        pops: list[dict] = []
        div = int(self.c["scaling"]["population_divisor"])
        floor = int(self.c["scaling"]["min_population_count"])
        # workforce populations, one per team_locations row
        for row in sorted(
            self.t["team_locations"], key=lambda r: (r["team"], r["region"])
        ):
            tenant = self.region_to_tenant[row["region"]]
            count = max(floor, math.ceil(int(row["headcount_in_region"]) / div))
            pops.append(
                {
                    "key": self.population_key(row["team"], row["region"]),
                    "tenant_key": tenant,
                    "organisation_key": self.org_key(tenant),
                    "unit_key": self.team_unit_key(tenant, row["team"]),
                    "population_kind": "employee",
                    "count": count,
                }
            )
        # workload populations, one per service, count = deployment rows
        for service in sorted(self.services):
            tenant = self.service_home_tenant[service]
            team = self.primary_owner_team(service)
            unit = (
                self.team_unit_key(tenant, team)
                if team and tenant in self.team_tenants.get(team, set())
                else self.division_key(tenant, self.service_primary_domain[service])
            )
            pops.append(
                {
                    "key": self.workload_population_key(service),
                    "tenant_key": tenant,
                    "organisation_key": self.org_key(tenant),
                    "unit_key": unit,
                    "population_kind": "workload",
                    "count": max(floor, int(self.service_deploy_count[service])),
                }
            )
        # supplier populations, one per data-processor vendor
        vendor_dep_counts = Counter(r["vendor"] for r in self.t["vendor_dependencies"])
        for vendor in sorted(self.vendors):
            if not self.vendors[vendor].get("data_processor"):
                continue
            pops.append(
                {
                    "key": self.supplier_population_key(vendor),
                    "tenant_key": self.vendor_tenant,
                    "organisation_key": self.org_key(self.vendor_tenant),
                    "unit_key": self.vendor_unit_key(vendor),
                    "population_kind": "supplier",
                    "count": max(floor, int(vendor_dep_counts.get(vendor, 1))),
                }
            )
        self.L.note(
            "team_locations[].headcount_in_region",
            TRANSFORMED,
            "population.count",
            f"Divided by experiment.yaml scaling.population_divisor ({div}), "
            "ceiling, minimum 1. Lossy by construction: the original headcount is "
            "preserved verbatim in the mapping report. Setting the divisor to 1 "
            "reproduces the full-scale world.",
        )
        self.L.note(
            "team_locations[].team",
            DIRECT,
            "population -> unit edge",
            "Foreign key into teams[].name.",
        )
        self.L.note(
            "team_locations[].region",
            TRANSFORMED,
            "population tenant assignment",
            "Region -> legal-entity tenant.",
        )
        self.L.note(
            "team_locations[].time_zone",
            NOT_REPRESENTABLE,
            "-",
            "SynthWorld ticks are dimensionless logical integers with no wall "
            "clock or zone, so a time zone cannot be represented honestly.",
        )
        self.L.note(
            "team_locations[].office_type",
            METADATA,
            "-",
            "office/remote has no SynthWorld construct. Note: NetworkZone "
            "(internal|partner|public) exists but mapping remote->public would "
            "assert a network fact the topology does not state.",
        )
        self.L.note(
            "team_locations[].can_operate_remotely",
            METADATA,
            "-",
            "Same reasoning as office_type.",
        )
        self.L.note(
            "team_locations[].skills_in_region",
            METADATA,
            "-",
            "Free-text skills; no SynthWorld construct.",
        )
        self.L.note(
            "services[].name",
            DIRECT,
            "resource_set + workload population",
            "Each service becomes one resource set and one workload population.",
        )
        self.L.note(
            "vendor_dependencies[].vendor",
            TRANSFORMED,
            "supplier population.count",
            "The number of services a vendor supports becomes the size of its "
            "supplier population. This count is derived, not stated in the source.",
        )
        return pops

    def primary_owner_team(self, service: str) -> str | None:
        for row in sorted(
            self.t["service_ownerships"], key=lambda r: (r["service"], r["team"])
        ):
            if row["service"] == service and row["ownership_type"] == "primary":
                return row["team"]
        return None

    def build_groups(self) -> list[dict]:
        groups: list[dict] = []
        bank_tenants = sorted(set(self.region_to_tenant.values()))
        for tenant in bank_tenants:
            for domain in sorted(self.domains):
                groups.append(
                    {
                        "key": self.group_key(tenant, f"div-{domain}"),
                        "tenant_key": tenant,
                        "organisation_key": self.org_key(tenant),
                        "owner_unit_key": self.division_key(tenant, domain),
                    }
                )
            for team in sorted(self.teams):
                if tenant not in self.team_tenants.get(team, set()):
                    continue
                groups.append(
                    {
                        "key": self.group_key(tenant, f"team-{team}"),
                        "tenant_key": tenant,
                        "organisation_key": self.org_key(tenant),
                        "owner_unit_key": self.team_unit_key(tenant, team),
                    }
                )
        for vendor in sorted(self.vendors):
            if not self.vendors[vendor].get("data_processor"):
                continue
            groups.append(
                {
                    "key": self.group_key(self.vendor_tenant, f"vendor-{vendor}"),
                    "tenant_key": self.vendor_tenant,
                    "organisation_key": self.org_key(self.vendor_tenant),
                    "owner_unit_key": self.vendor_unit_key(vendor),
                }
            )
        return groups

    def build_roles(self) -> list[dict]:
        roles: list[dict] = []
        bank_tenants = sorted(set(self.region_to_tenant.values()))
        role_names = sorted(set(self.c["roles"]["ownership_type_to_role"].values())) + [
            self.c["roles"]["oversight_role"]
        ]
        for tenant in bank_tenants:
            for domain in sorted(self.domains):
                for rn in role_names:
                    roles.append(
                        {
                            "key": self.role_key(tenant, f"{domain}-{rn}"),
                            "tenant_key": tenant,
                            "organisation_key": self.org_key(tenant),
                            "owner_unit_key": self.division_key(tenant, domain),
                        }
                    )
        # supplier roles live in the vendor tenant, scoped to the vendor unit
        for vendor in sorted(self.vendors):
            if not self.vendors[vendor].get("data_processor"):
                continue
            roles.append(
                {
                    "key": self.role_key(self.vendor_tenant, f"{vendor}-supplier"),
                    "tenant_key": self.vendor_tenant,
                    "organisation_key": self.org_key(self.vendor_tenant),
                    "owner_unit_key": self.vendor_unit_key(vendor),
                }
            )
        self.L.note(
            "service_ownerships[].ownership_type",
            TRANSFORMED,
            "roles[] + role_hierarchy + role_grants",
            "primary/on_call/supporting become the seniority ladder "
            "service-owner > service-operator > service-contributor, each with a "
            "different action grant. This ladder is what the scope-exceeded "
            "denial case exercises.",
        )
        self.L.note(
            "organisation.metadata.lines_of_defence",
            TRANSFORMED,
            "role(risk-oversight)",
            "Second and third line of defence become a read-only oversight role. "
            "The specific named functions are experiment metadata.",
        )
        return roles

    def build_resource_sets(self) -> list[dict]:
        out: list[dict] = []
        tk_map = self.c["resources"]["service_type_to_target_kind"]
        actions = list(self.c["resources"]["actions"])
        for service in sorted(self.services):
            svc = self.services[service]
            stype = svc["service_type"]
            if stype not in tk_map:
                raise SystemExit(f"unmapped service_type: {stype}")
            tenant = self.service_home_tenant[service]
            domain = self.service_primary_domain[service]
            team = self.primary_owner_team(service)
            owner_unit = (
                self.team_unit_key(tenant, team)
                if team and tenant in self.team_tenants.get(team, set())
                else self.division_key(tenant, domain)
            )
            out.append(
                {
                    "key": self.resource_key(service),
                    "tenant_key": tenant,
                    "organisation_key": self.org_key(tenant),
                    "target_kind": tk_map[stype],
                    "owner_unit_key": owner_unit,
                    "instance_count": max(1, int(self.service_deploy_count[service])),
                    "actions": actions,
                }
            )
        self.L.note(
            "services[].service_type",
            TRANSFORMED,
            "resource_set.target_kind",
            "api->api and database->data_store are exact. cache->data_store, "
            "queue->api, worker->application and external->application are "
            "approximations: SynthWorld TargetKind has no cache, messaging or "
            "external-system construct. The original service_type is preserved "
            "in the mapping report.",
        )
        self.L.note(
            "services[].data_classification",
            NOT_REPRESENTABLE,
            "-",
            "The VALUES map 1:1 onto SynthWorld's InformationClassification enum "
            "(internal/confidential/restricted), but there is nowhere to put them: "
            "ResourceSetTemplateV1 has no classification field, so the value cannot "
            "cross the blueprint boundary into the compiled universe. Stage 20 "
            "builds the ABAC facts from the compiled universe alone and therefore "
            "cannot see it either. A clearance model was designed (see the "
            "`clearance:` block in experiment.yaml) but is NOT realised: no "
            "resource_classification fact and no subject_clearance fact is emitted.",
        )
        self.L.note(
            "services[].criticality",
            METADATA,
            "-",
            "critical/high/medium has no SynthWorld construct. It is NOT mapped "
            "onto InformationClassification, which would conflate availability "
            "criticality with confidentiality.",
        )
        for f, why in [
            ("sla_availability_target", "availability target"),
            ("baseline_latency_ms", "latency"),
            ("baseline_throughput_rps", "throughput"),
            ("baseline_error_rate", "error rate"),
            ("monthly_cost_usd", "cost"),
            ("bcm_plan", "business continuity plan"),
            ("disaster_recovery_plan", "disaster recovery plan"),
            ("incident_reporting_contact", "incident contact"),
        ]:
            self.L.note(
                f"services[].{f}",
                NOT_REPRESENTABLE,
                "-",
                f"SynthWorld models identity and access only; {why} is a "
                "resilience/finance property with no authorization construct.",
            )
        self.L.note(
            "services[].regulatory_scope",
            METADATA,
            "-",
            "Regulatory regime list has no SynthWorld construct. Retained as "
            "experiment metadata and shown in the HTML view.",
        )
        self.L.note(
            "services[].metadata",
            METADATA,
            "-",
            "Per-service operational metadata, retained as experiment metadata. "
            "NOTE none of its sub-keys feeds any SynthWorld construct. In "
            "particular services[].metadata.network_zone does NOT feed the ABAC "
            "environment_network_zone fact: that fact is derived from subject "
            "kind alone (partner for accounts, internal for principals). See the "
            "dedicated row for network_zone.",
        )
        self.L.note(
            "services[].metadata.network_zone",
            NOT_REPRESENTABLE,
            "-",
            "The topology uses five zone values (dmz, data, external, management, "
            "application); SynthWorld's NetworkZone enum has three "
            "(internal, partner, public) with no defensible correspondence. "
            "Mapping them would assert a network fact the topology does not state, "
            "so the field is unused.",
        )
        self.L.note(
            "services[].metadata.expected_mttr_minutes",
            NOT_REPRESENTABLE,
            "-",
            "Recovery-time objective; no authorization construct.",
        )
        return out

    def build_atom_rules(self) -> list[dict]:
        """Access atoms come from service_ownerships: a team's staff in a region
        get, on the services that team owns, the actions its ownership role grants."""
        rules: list[dict] = []
        o2r = self.c["roles"]["ownership_type_to_role"]
        grants = self.c["roles"]["grants"]
        seen: set[str] = set()
        # A team can hold more than one ownership_type on the same service (e.g.
        # SRE & Observability is both `primary` and `on_call` for
        # observability-platform). Two ownership roles that both grant an action
        # would emit the same (population, resource_set, action) atom twice, which
        # the compiler rejects with `duplicate_access_atom_declaration`. Keep the
        # most senior ownership_type per (team, service) and drop the rest; the
        # senior role's grant is a superset of the junior's by construction.
        seniority = {"primary": 0, "on_call": 1, "supporting": 2}
        best_ownership: dict[tuple[str, str], str] = {}
        for row in self.t["service_ownerships"]:
            k = (row["service"], row["team"])
            cur = best_ownership.get(k)
            if cur is None or seniority[row["ownership_type"]] < seniority[cur]:
                best_ownership[k] = row["ownership_type"]
        for row in sorted(
            self.t["service_ownerships"],
            key=lambda r: (r["service"], r["team"], r["ownership_type"]),
        ):
            svc, team, otype = row["service"], row["team"], row["ownership_type"]
            if svc not in self.services or team not in self.teams:
                continue
            if best_ownership.get((svc, team)) != otype:
                continue
            role = o2r.get(otype)
            if role is None:
                raise SystemExit(f"unmapped ownership_type: {otype}")
            svc_tenant = self.service_home_tenant[svc]
            for region in sorted(
                {
                    r["region"]
                    for r in self.t["team_locations"]
                    if r["team"] == team
                }
            ):
                pop_tenant = self.region_to_tenant[region]
                if pop_tenant != svc_tenant:
                    # The released importer rejects any access declaration whose
                    # population and resource set sit in different tenants
                    # (diagnostic `cross_tenant_access_declaration`). This pair is
                    # real - the topology says this team owns this service, and
                    # this team has staff in this region - but it straddles two
                    # legal entities, so it cannot be declared. Record it: these
                    # pairs become the cross-boundary denial request set.
                    self.cross_tenant_ownership.append(
                        {
                            "team": team,
                            "region": region,
                            "subject_tenant": pop_tenant,
                            "service": svc,
                            "resource_tenant": svc_tenant,
                            "ownership_type": otype,
                            "population_key": self.population_key(team, region),
                            "resource_set_key": self.resource_key(svc),
                        }
                    )
                    continue
                pop = self.population_key(team, region)
                for action in grants[role]:
                    key = f"atom-{slug(otype)}-{slug(team)}-{slug(region)}-{slug(svc)}-{action}"
                    if key in seen:
                        continue
                    seen.add(key)
                    rules.append(
                        {
                            "rule_key": key,
                            "population_key": pop,
                            "resource_set_key": self.resource_key(svc),
                            "action": action,
                            "selector": {"kind": "all"},
                        }
                    )
        self.L.note(
            "service_ownerships[].team",
            DIRECT,
            "principal_access_atom_rules[].population_key",
            "Foreign key into teams[].name; selects which populations get atoms.",
        )
        self.L.note(
            "service_ownerships[].service",
            DIRECT,
            "principal_access_atom_rules[].resource_set_key",
            "Foreign key into services[].name.",
        )
        return rules

    def build_iam_extension(self) -> dict:
        allocs: list[dict] = []
        atom_rules: list[dict] = []
        # workload accounts: one per service workload population, bound to the
        # service's own resource set
        for service in sorted(self.services):
            key = f"alloc-wl-{slug(service)}"
            allocs.append(
                {
                    "key": key,
                    "population_key": self.workload_population_key(service),
                    "resource_set_key": self.resource_key(service),
                    "account_kind": "workload",
                    "selector": {"kind": "all"},
                    "accounts_per_selected_subject": 1,
                }
            )
        # service_dependencies: caller's workload account gets invoke on callee
        seen: set[str] = set()
        for row in sorted(
            self.t["service_dependencies"], key=lambda r: (r["source"], r["target"])
        ):
            src, tgt = row["source"], row["target"]
            if src not in self.services or tgt not in self.services:
                continue
            if self.service_home_tenant[src] != self.service_home_tenant[tgt]:
                # A real service-to-service call that crosses legal entities.
                # Cannot be declared (cross_tenant_access_declaration); becomes a
                # cross-boundary workload denial request instead.
                self.cross_tenant_dependency.append(
                    {
                        "source": src,
                        "source_tenant": self.service_home_tenant[src],
                        "target": tgt,
                        "target_tenant": self.service_home_tenant[tgt],
                        "dependency_type": row.get("dependency_type"),
                        "population_key": self.workload_population_key(src),
                        "resource_set_key": self.resource_key(tgt),
                    }
                )
                continue
            key = f"alloc-dep-{slug(src)}-{slug(tgt)}"
            if key in seen:
                continue
            seen.add(key)
            allocs.append(
                {
                    "key": key,
                    "population_key": self.workload_population_key(src),
                    "resource_set_key": self.resource_key(tgt),
                    "account_kind": "workload",
                    "selector": {"kind": "count", "count": 1},
                    "accounts_per_selected_subject": 1,
                }
            )
            atom_rules.append(
                {"rule_key": f"aar-dep-{slug(src)}-{slug(tgt)}-invoke", "account_allocation_key": key, "action": "invoke"}
            )
        # workforce accounts for each workforce population on its team's
        # primary-owned services
        for row in sorted(
            self.t["service_ownerships"], key=lambda r: (r["service"], r["team"])
        ):
            if row["ownership_type"] != "primary":
                continue
            svc, team = row["service"], row["team"]
            if svc not in self.services or team not in self.teams:
                continue
            for region in sorted(
                {r["region"] for r in self.t["team_locations"] if r["team"] == team}
            ):
                if self.region_to_tenant[region] != self.service_home_tenant[svc]:
                    continue  # already recorded by build_atom_rules
                key = f"alloc-wf-{slug(team)}-{slug(region)}-{slug(svc)}"
                if key in seen:
                    continue
                seen.add(key)
                allocs.append(
                    {
                        "key": key,
                        "population_key": self.population_key(team, region),
                        "resource_set_key": self.resource_key(svc),
                        "account_kind": "workforce",
                        "selector": {"kind": "count", "count": 1},
                        "accounts_per_selected_subject": int(
                            self.c["accounts"]["workforce_accounts_per_subject"]
                        ),
                    }
                )
                atom_rules.append(
                    {
                        "rule_key": f"aar-wf-{slug(team)}-{slug(region)}-{slug(svc)}-read",
                        "account_allocation_key": key,
                        "action": "read",
                    }
                )
        # agent accounts against ai_ml-vendor-backed services
        ai_vendors = {
            v
            for v, rec in self.vendors.items()
            if rec.get("vendor_type") in set(self.c["accounts"]["agent_account_vendor_types"])
        }
        for row in sorted(
            self.t["vendor_dependencies"], key=lambda r: (r["service"], r["vendor"])
        ):
            if row["vendor"] not in ai_vendors:
                continue
            svc = row["service"]
            if svc not in self.services:
                continue
            key = f"alloc-agent-{slug(svc)}"
            if key in seen:
                continue
            seen.add(key)
            allocs.append(
                {
                    "key": key,
                    "population_key": self.workload_population_key(svc),
                    "resource_set_key": self.resource_key(svc),
                    "account_kind": "agent",
                    "selector": {"kind": "count", "count": 1},
                    "accounts_per_selected_subject": 1,
                }
            )
            atom_rules.append(
                {"rule_key": f"aar-agent-{slug(svc)}-invoke", "account_allocation_key": key, "action": "invoke"}
            )
        self.L.note(
            "service_dependencies[].source",
            TRANSFORMED,
            "account_allocations[] (workload) + account_access_atom_rules[]",
            "A service->service edge becomes the caller's workload account "
            "holding invoke on the callee's resource set. This is what makes the "
            "wrong-runtime-binding negative case testable: a workload account "
            "invoking a service it has no dependency edge to.",
        )
        self.L.note(
            "service_dependencies[].target",
            TRANSFORMED,
            "account_access_atom_rules[] target",
            "Callee service resource set.",
        )
        self.L.note(
            "service_dependencies[].dependency_type",
            METADATA,
            "-",
            "sync_http/async_event/data_read/... has no SynthWorld construct; "
            "every edge is flattened to a single 'invoke' action.",
        )
        self.L.note(
            "service_dependencies[].criticality",
            METADATA,
            "-",
            "Dependency criticality has no authorization construct.",
        )
        self.L.note(
            "service_dependencies[].timeout_ms",
            NOT_REPRESENTABLE,
            "-",
            "Optional field (present on 65 of 104 edges). A call timeout has no "
            "SynthWorld construct.",
        )
        self.L.note(
            "vendors[].vendor_type",
            TRANSFORMED,
            "agent account allocation predicate",
            "vendor_type=ai_ml selects which services get an agent-kind account, "
            "supplying the agent-binding negative case.",
        )
        self.L.note(
            "vendor_dependencies[].service",
            DIRECT,
            "agent/supplier account target",
            "Foreign key into services[].name.",
        )
        self.L.note(
            "vendor_dependencies[].dependency_type",
            METADATA,
            "-",
            "21 distinct free-form values; no SynthWorld construct.",
        )
        self.L.note(
            "vendor_dependencies[].criticality",
            METADATA,
            "-",
            "No authorization construct.",
        )
        self.L.note(
            "vendor_dependencies[].fallback_vendor",
            METADATA,
            "-",
            "Optional (15 of 36 rows). Resilience concept, not access.",
        )
        return {
            "schema_version": "1.0.0",
            "account_allocations": allocs,
            "account_access_atom_rules": atom_rules,
        }

    def build_directory_state(self) -> dict:
        memberships: list[dict] = []
        group_nesting: list[dict] = []
        group_role_assignments: list[dict] = []
        population_role_assignments: list[dict] = []
        role_hierarchy: list[dict] = []
        role_grants: list[dict] = []

        # every workforce population is a member of its team group
        for row in sorted(
            self.t["team_locations"], key=lambda r: (r["team"], r["region"])
        ):
            tenant = self.region_to_tenant[row["region"]]
            memberships.append(
                {
                    "rule_key": f"mem-{slug(row['team'])}-{slug(row['region'])}",
                    "population_key": self.population_key(row["team"], row["region"]),
                    "group_key": self.group_key(tenant, f"team-{row['team']}"),
                    "selector": {"kind": "all"},
                }
            )
        # supplier populations join their vendor group
        for vendor in sorted(self.vendors):
            if not self.vendors[vendor].get("data_processor"):
                continue
            memberships.append(
                {
                    "rule_key": f"mem-vendor-{slug(vendor)}",
                    "population_key": self.supplier_population_key(vendor),
                    "group_key": self.group_key(self.vendor_tenant, f"vendor-{vendor}"),
                    "selector": {"kind": "all"},
                }
            )
        # team groups nest under their division group (same tenant)
        for team in sorted(self.teams):
            domain = self.team_parent_division[team]
            for tenant in sorted(self.team_tenants.get(team, set())):
                group_nesting.append(
                    {
                        "child_group_key": self.group_key(tenant, f"team-{team}"),
                        "parent_group_key": self.group_key(tenant, f"div-{domain}"),
                    }
                )
        # role hierarchy, per tenant per division
        bank_tenants = sorted(set(self.region_to_tenant.values()))
        for tenant in bank_tenants:
            for domain in sorted(self.domains):
                for pair in self.c["roles"]["hierarchy"]:
                    role_hierarchy.append(
                        {
                            "senior_role_key": self.role_key(
                                tenant, f"{domain}-{pair['senior']}"
                            ),
                            "junior_role_key": self.role_key(
                                tenant, f"{domain}-{pair['junior']}"
                            ),
                        }
                    )
        # role grants: each division role grants its action ladder on every
        # resource set homed in that tenant whose primary domain is that division
        for tenant in bank_tenants:
            for service in sorted(self.services):
                if self.service_home_tenant[service] != tenant:
                    continue
                domain = self.service_primary_domain[service]
                for rn, actions in sorted(self.c["roles"]["grants"].items()):
                    for action in actions:
                        role_grants.append(
                            {
                                "role_key": self.role_key(tenant, f"{domain}-{rn}"),
                                "resource_set_key": self.resource_key(service),
                                "action": action,
                            }
                        )
                for action in self.c["roles"]["oversight_grants"]:
                    role_grants.append(
                        {
                            "role_key": self.role_key(
                                tenant, f"{domain}-{self.c['roles']['oversight_role']}"
                            ),
                            "resource_set_key": self.resource_key(service),
                            "action": action,
                        }
                    )
        # population role assignments follow ownership_type
        o2r = self.c["roles"]["ownership_type_to_role"]
        seen_assign: set[str] = set()
        for row in sorted(
            self.t["service_ownerships"],
            key=lambda r: (r["service"], r["team"], r["ownership_type"]),
        ):
            svc, team, otype = row["service"], row["team"], row["ownership_type"]
            if svc not in self.services or team not in self.teams:
                continue
            domain = self.service_primary_domain[svc]
            role = o2r[otype]
            for region in sorted(
                {r["region"] for r in self.t["team_locations"] if r["team"] == team}
            ):
                tenant = self.region_to_tenant[region]
                key = f"pra-{slug(team)}-{slug(region)}-{slug(domain)}-{slug(role)}"
                if key in seen_assign:
                    continue
                seen_assign.add(key)
                population_role_assignments.append(
                    {
                        "rule_key": key,
                        "population_key": self.population_key(team, region),
                        "role_key": self.role_key(tenant, f"{domain}-{role}"),
                        "selector": {"kind": "all"},
                    }
                )
        # oversight: the second/third-line teams named in lines_of_defence get the
        # oversight role across every division in their tenants
        lod = self.t["organisation"]["metadata"]["lines_of_defence"]
        oversight_teams = sorted(set(lod.get("second_line", []) + lod.get("third_line", [])))
        for team in oversight_teams:
            if team not in self.teams:
                continue
            for region in sorted(
                {r["region"] for r in self.t["team_locations"] if r["team"] == team}
            ):
                tenant = self.region_to_tenant[region]
                for domain in sorted(self.domains):
                    key = f"pra-oversight-{slug(team)}-{slug(region)}-{slug(domain)}"
                    if key in seen_assign:
                        continue
                    seen_assign.add(key)
                    population_role_assignments.append(
                        {
                            "rule_key": key,
                            "population_key": self.population_key(team, region),
                            "role_key": self.role_key(
                                tenant, f"{domain}-{self.c['roles']['oversight_role']}"
                            ),
                            "selector": {"kind": "all"},
                        }
                    )
        # supplier groups get their vendor role
        for vendor in sorted(self.vendors):
            if not self.vendors[vendor].get("data_processor"):
                continue
            group_role_assignments.append(
                {
                    "group_key": self.group_key(self.vendor_tenant, f"vendor-{vendor}"),
                    "role_key": self.role_key(self.vendor_tenant, f"{vendor}-supplier"),
                }
            )
        return {
            "schema_version": "1.0.0",
            "account_observations": [],
            "memberships": memberships,
            "group_nesting": group_nesting,
            "group_role_assignments": group_role_assignments,
            "population_role_assignments": population_role_assignments,
            "role_hierarchy": role_hierarchy,
            "role_grants": role_grants,
            "direct_entitlements": [],
        }

    def note_remaining_fields(self) -> None:
        """Fields the adapter deliberately does not consume, recorded explicitly
        so the mapping report can prove nothing was silently discarded."""
        for path, cls, why in [
            ("organisation.scale_preset", METADATA, "Generator hint for the tool that produced the topology; no SynthWorld construct."),
            ("organisation.industry_preset", METADATA, "As above."),
            ("organisation.metadata.headquarters", METADATA, "No SynthWorld geographic construct."),
            ("organisation.metadata.benchmark_reference", METADATA, "Provenance prose."),
            ("organisation.metadata.employee_count_total", METADATA, "Whole-bank headcount; the compiled world sizes populations from team_locations instead."),
            ("organisation.metadata.technology_and_operations_fte", METADATA, "As above."),
            ("organisation.metadata.major_offices", NOT_REPRESENTABLE, "No SynthWorld location construct."),
            ("organisation.metadata.important_business_services", METADATA, "Regulatory concept (UK operational resilience); no SynthWorld construct."),
            ("organisation.metadata.regulatory_structure", METADATA, "Jurisdiction -> regime map; no SynthWorld construct."),
            ("organisation.metadata.target_operating_model", METADATA, "Prose."),
            ("organisation.metadata.team_model", METADATA, "Prose."),
            ("organisation.metadata.annual_revenue_usd", NOT_REPRESENTABLE, "Financial figure; no authorization construct."),
            ("organisation.metadata.it_budget_usd", NOT_REPRESENTABLE, "As above."),
            ("teams[].headcount", METADATA, "Whole-team headcount. Populations are sized from the per-region team_locations rows instead, which sum to a different total; both figures appear in the mapping report."),
            ("vendors[].catalogue_slug", METADATA, "Vendor catalogue identifier."),
            ("vendors[].criticality_to_org", METADATA, "No authorization construct."),
            ("vendors[].monthly_cost_usd", NOT_REPRESENTABLE, "Financial figure."),
            ("vendors[].headquarters_country", METADATA, "No SynthWorld geographic construct."),
            ("vendors[].jurisdiction", METADATA, "Legal jurisdiction; distinct from the tenant axis, which is derived from the bank's own legal entities."),
            ("vendors[].ownership_structure", METADATA, "Corporate ownership; no SynthWorld construct."),
            ("vendors[].alternative_vendors", METADATA, "Resilience substitutability; no authorization construct."),
            ("vendors[].security_assessment_date", NOT_REPRESENTABLE, "A real calendar date. SynthWorld ticks are dimensionless logical integers with no calendar, so this cannot be mapped without inventing a clock. See the limitations report."),
            ("vendors[].metadata", METADATA, "Per-vendor free-form metadata."),
            ("service_ownerships[].ownership_type", TRANSFORMED, "Already recorded above."),
            ("data_flows[].source_service", METADATA, "Data-flow edges describe payload movement, not principal access. Modelling them as access atoms would assert authorization facts the topology does not state."),
            ("data_flows[].target_service", METADATA, "As above."),
            ("data_flows[].source_region", METADATA, "As above."),
            ("data_flows[].target_region", METADATA, "As above."),
            ("data_flows[].data_classification", METADATA, "Per-flow classification; the resource-set classification is taken from services[].data_classification instead."),
            ("data_flows[].confidentiality", METADATA, "Duplicate of data_classification on all 6 rows."),
            ("data_flows[].data_category", METADATA, "personal/etc; no SynthWorld construct."),
            ("data_flows[].is_cross_border", METADATA, "Transfer property, not an access decision."),
            ("data_flows[].adequacy_decision", NOT_REPRESENTABLE, "GDPR transfer concept; no SynthWorld construct."),
            ("data_flows[].transfer_mechanism", NOT_REPRESENTABLE, "As above."),
            ("data_flows[].has_dpa", NOT_REPRESENTABLE, "Contractual flag; no SynthWorld construct."),
            ("data_flows[].has_sccs", NOT_REPRESENTABLE, "As above."),
            ("data_flows[].has_bcr", NOT_REPRESENTABLE, "As above."),
            ("data_flows[].encryption", NOT_REPRESENTABLE, "Cryptographic control, not an access relation."),
            ("data_flows[].encryption_in_transit", NOT_REPRESENTABLE, "As above."),
            ("data_flows[].encryption_at_rest", NOT_REPRESENTABLE, "As above."),
            ("data_flows[].erasure_days", NOT_REPRESENTABLE, "Retention period; no SynthWorld construct."),
            ("data_flows[].erasure_mechanism", NOT_REPRESENTABLE, "As above."),
            ("data_flows[].regulatory_constraints", METADATA, "Regime list; no SynthWorld construct."),
            ("data_flows[].volume_gb_per_day", NOT_REPRESENTABLE, "Throughput figure."),
        ]:
            self.L.note(path, cls, "-" if cls != TRANSFORMED else "see above", why)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topology", default=str(REPO / "01-source/topology/britannia_global_bank_topology.yaml"))
    ap.add_argument("--config", default=str(REPO / "01-source/config/experiment.yaml"))
    ap.add_argument("--out", default=str(REPO / "01-source/generated/britannia-identity-access-import.yaml"))
    ap.add_argument("--ledger", default=str(REPO / "01-source/generated/mapping-ledger.json"))
    args = ap.parse_args()

    topology = load_yaml(Path(args.topology))
    config = load_yaml(Path(args.config))

    ledger = Ledger()
    m = Mapper(topology, config, ledger)
    doc = m.build()
    m.note_remaining_fields()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # The released importer rejects YAML anchors/aliases ("yaml_alias_forbidden",
    # remediation: "Use the restricted JSON-compatible YAML subset"). PyYAML emits
    # an alias whenever the same list/dict object is referenced twice - which
    # happens naturally here because every resource set shares one actions list.
    # Suppress aliasing so the emitted document stays in the accepted subset.
    class NoAliasDumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:  # noqa: D401
            return True

    text = yaml.dump(
        doc,
        Dumper=NoAliasDumper,
        sort_keys=False,
        default_flow_style=False,
        width=100,
    )
    out.write_text(text, encoding="utf-8")

    counts = {
        "tenants": len(doc["blueprint"]["tenants"]),
        "organisations": len(doc["blueprint"]["organisations"]),
        "units": len(doc["blueprint"]["units"]),
        "populations": len(doc["blueprint"]["populations"]),
        "declared_principals": sum(p["count"] for p in doc["blueprint"]["populations"]),
        "groups": len(doc["blueprint"]["groups"]),
        "roles": len(doc["blueprint"]["roles"]),
        "resource_sets": len(doc["blueprint"]["resource_sets"]),
        "principal_access_atom_rules": len(doc["blueprint"]["principal_access_atom_rules"]),
        "account_allocations": len(doc["iam_universe_extension"]["account_allocations"]),
        "account_access_atom_rules": len(doc["iam_universe_extension"]["account_access_atom_rules"]),
        "memberships": len(doc["directory_rbac_state"]["memberships"]),
        "group_nesting": len(doc["directory_rbac_state"]["group_nesting"]),
        "group_role_assignments": len(doc["directory_rbac_state"]["group_role_assignments"]),
        "population_role_assignments": len(doc["directory_rbac_state"]["population_role_assignments"]),
        "role_hierarchy": len(doc["directory_rbac_state"]["role_hierarchy"]),
        "role_grants": len(doc["directory_rbac_state"]["role_grants"]),
        "cross_tenant_ownership_pairs_dropped": len(m.cross_tenant_ownership),
        "cross_tenant_dependency_pairs_dropped": len(m.cross_tenant_dependency),
    }

    # Real topology relations that the released importer forbids declaring
    # because they straddle two legal entities. These are not discarded: they are
    # the source of the cross-boundary denial requests in stage 40.
    cb = Path(args.out).parent / "cross-boundary-pairs.json"
    cb.write_text(
        json.dumps(
            {
                "note": (
                    "Topology relations that cross a legal-entity (tenant) "
                    "boundary. The released SynthWorld importer rejects these "
                    "with diagnostic `cross_tenant_access_declaration`, so they "
                    "cannot appear in the declared world. They are carried here "
                    "and replayed against Topaz as cross-boundary denial "
                    "requests."
                ),
                "ownership_pairs": sorted(
                    m.cross_tenant_ownership,
                    key=lambda r: (r["service"], r["team"], r["region"]),
                ),
                "dependency_pairs": sorted(
                    m.cross_tenant_dependency, key=lambda r: (r["source"], r["target"])
                ),
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )

    lp = Path(args.ledger)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(
        json.dumps(
            {
                "topology_sha256": hashlib.sha256(
                    Path(args.topology).read_bytes()
                ).hexdigest(),
                "config_sha256": hashlib.sha256(
                    Path(args.config).read_bytes()
                ).hexdigest(),
                "import_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "counts": counts,
                "ledger": ledger.dump(),
            },
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(json.dumps(counts, indent=1))
    print(f"import  -> {out}")
    print(f"ledger  -> {lp}  ({len(ledger.dump())} field rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
