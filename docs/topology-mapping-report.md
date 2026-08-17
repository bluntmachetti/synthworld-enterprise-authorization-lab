# Topology → SynthWorld mapping report

Field-by-field audit of the transformation from `britannia_global_bank_topology.yaml` into the
SynthWorld `EnterpriseIdentityAccessImportV1` document and, from there, into the compiled public
universe. This document is written to be read side-by-side with the source: every count in it was
recomputed from the artefacts named below, not copied from a prior summary.

## 1. Provenance

| | |
|---|---|
| Source topology | `/home/kademolu/Projects/agent-auth-2/01-source/topology/britannia_global_bank_topology.yaml` |
| Topology SHA-256 | `29ea8dd155ceed277eedf3f7261f0ba6844ff5a3e6c5a9c70164ae78b80871d1` |
| Mapping constants | `/home/kademolu/Projects/agent-auth-2/01-source/config/experiment.yaml` (SHA-256 `4f4d3fccea6515325f161471c843c1089f77b1fc922caf4c845108bb6d572f0b`) |
| Adapter | `/home/kademolu/Projects/agent-auth-2/bin/10_map_topology.py` |
| Adapter ledger | `/home/kademolu/Projects/agent-auth-2/01-source/generated/mapping-ledger.json` (98 rows) |
| Blocked pairs | `/home/kademolu/Projects/agent-auth-2/01-source/generated/cross-boundary-pairs.json` (135 ownership + 49 dependency) |
| Emitted import document | `/home/kademolu/Projects/agent-auth-2/01-source/generated/britannia-identity-access-import.yaml` (SHA-256 `6f893fce79bb68c55b9157acafc398f5b5abf37c615050470b06e5ee3ba21e13`) |
| Compiled universe | `/home/kademolu/Projects/agent-auth-2/02-synthworld-public/identity-access/identity-access-universe.json` (digest `a4c7bcfb…66a7c6`, seed `20260816`) |
| SynthWorld | `idcognito-synthworld==0.16.0` |

The adapter's output is a pure function of (topology bytes, `experiment.yaml` bytes). The
compilation seed affects selector resolution only.

## 2. Classification vocabulary

The adapter emits exactly four classifications. They are not severity grades; they answer different
questions.

| Classification | Meaning | Recoverable from the compiled world? |
|---|---|---|
| `represented_directly` | The field's value or the edge it defines survives into the SynthWorld document with no semantic reinterpretation. | Yes. |
| `documented_transformation` | The field is consumed, but through a rule that changes or loses information. Every such rule is named in §6 with its exact factor. | Only via this report plus `experiment.yaml`. |
| `experiment_metadata` | The field is read by nothing in the compiled world. It is retained as provenance because it describes the source estate, not because SynthWorld could hold it. | No — it never entered. |
| `not_representable` | There is no SynthWorld construct capable of holding the fact, at any fidelity. | No. |

The distinction between the last two is deliberate but imperfect: `experiment_metadata` is used both
for "SynthWorld has no construct" and for "a construct exists but using it would assert a fact the
topology does not state". Where the second reading applies, the ledger note says so
(`team_locations[].office_type` is the clearest example).

## 3. Coverage audit — what the ledger does and does not name

A programmatic recursive walk of the parsed topology yields **150 distinct field paths**
(123 leaves, 19 list containers, 8 nested-object containers; the 12 collection roots and the
`organisation` root are excluded as they are collections, not fields). This matches the independent
count in `docs/discovery-notes/topology-inventory.md`.

The ledger has **98 rows**. One of them, `services[].service_type=external`, is not a field path at
all — it is a synthetic key the adapter uses to record a value-conditioned rule. So **97 ledger rows
name a real topology path**.

**150 − 97 = 53 topology paths do not appear verbatim in the ledger.** That is the gap, and it is
reported in full below rather than smoothed over.

### 3.1 The gap, characterised

| | Count |
|---:|---|
| Topology field paths | 150 |
| Named verbatim by a ledger row | 97 |
| **Not named by any ledger row** | **53** |
| — of those, leaf (scalar) paths | 40 |
| — of those, list containers | 11 |
| — of those, nested-object containers | 2 |
| Paths with no ledger row *and* no ancestor ledger row | 1 (`organisation.metadata`, a pure container whose every descendant is covered) |

No leaf field in the topology is entirely unaccounted for. But 40 leaves are accounted for only
*collectively*, by a coarser ancestor row — most often `services[].metadata`,
`vendors[].metadata`, `organisation.metadata.regulatory_structure` or `vendors[].ownership_structure`.
A blanket row classifying a whole metadata object as `experiment_metadata` asserts that none of its
9 sub-keys is used. That assertion happens to be true here (verified in §3.3), but the ledger does
not prove it — an auditor has to take it on trust, and a future edit that starts consuming
`services[].metadata.network_zone` would not change a single ledger row.

**Recommended remediation:** the adapter's `Ledger.note()` should be called per leaf, not per
container, at least for the six nested-object rows that stand in for 32 of these 40 leaves
(`services[].metadata` alone covers 12).

### 3.2 Full table of topology paths absent from the ledger

All 53. "Nearest ledger row that covers it" is the closest ancestor path that *does* have a ledger
row; the field itself has none.

| # | Topology path | Node type | Nearest ledger row that covers it | Its classification |
|---:|---|---|---|---|
| 1 | `organisation.regions[]` | leaf | `organisation.regions` | transformed |
| 2 | `organisation.metadata` | object | **none** | — |
| 3 | `organisation.metadata.legal_entity_footprint.uk` | leaf | `organisation.metadata.legal_entity_footprint` | transformed |
| 4 | `organisation.metadata.legal_entity_footprint.europe` | leaf | `organisation.metadata.legal_entity_footprint` | transformed |
| 5 | `organisation.metadata.legal_entity_footprint.americas` | leaf | `organisation.metadata.legal_entity_footprint` | transformed |
| 6 | `organisation.metadata.legal_entity_footprint.apac_mea` | leaf | `organisation.metadata.legal_entity_footprint` | transformed |
| 7 | `organisation.metadata.major_offices[]` | leaf | `organisation.metadata.major_offices` | not representable |
| 8 | `organisation.metadata.lines_of_defence.first_line` | list | `organisation.metadata.lines_of_defence` | transformed |
| 9 | `organisation.metadata.lines_of_defence.first_line[]` | leaf | `organisation.metadata.lines_of_defence` | transformed |
| 10 | `organisation.metadata.lines_of_defence.second_line` | list | `organisation.metadata.lines_of_defence` | transformed |
| 11 | `organisation.metadata.lines_of_defence.second_line[]` | leaf | `organisation.metadata.lines_of_defence` | transformed |
| 12 | `organisation.metadata.lines_of_defence.third_line` | list | `organisation.metadata.lines_of_defence` | transformed |
| 13 | `organisation.metadata.lines_of_defence.third_line[]` | leaf | `organisation.metadata.lines_of_defence` | transformed |
| 14 | `organisation.metadata.important_business_services[]` | leaf | `organisation.metadata.important_business_services` | metadata |
| 15 | `organisation.metadata.regulatory_structure.eu_eea` | list | `organisation.metadata.regulatory_structure` | metadata |
| 16 | `organisation.metadata.regulatory_structure.eu_eea[]` | leaf | `organisation.metadata.regulatory_structure` | metadata |
| 17 | `organisation.metadata.regulatory_structure.uk` | list | `organisation.metadata.regulatory_structure` | metadata |
| 18 | `organisation.metadata.regulatory_structure.uk[]` | leaf | `organisation.metadata.regulatory_structure` | metadata |
| 19 | `organisation.metadata.regulatory_structure.us` | list | `organisation.metadata.regulatory_structure` | metadata |
| 20 | `organisation.metadata.regulatory_structure.us[]` | leaf | `organisation.metadata.regulatory_structure` | metadata |
| 21 | `organisation.metadata.regulatory_structure.singapore` | list | `organisation.metadata.regulatory_structure` | metadata |
| 22 | `organisation.metadata.regulatory_structure.singapore[]` | leaf | `organisation.metadata.regulatory_structure` | metadata |
| 23 | `organisation.metadata.regulatory_structure.hong_kong` | list | `organisation.metadata.regulatory_structure` | metadata |
| 24 | `organisation.metadata.regulatory_structure.hong_kong[]` | leaf | `organisation.metadata.regulatory_structure` | metadata |
| 25 | `organisation.metadata.regulatory_structure.australia` | list | `organisation.metadata.regulatory_structure` | metadata |
| 26 | `organisation.metadata.regulatory_structure.australia[]` | leaf | `organisation.metadata.regulatory_structure` | metadata |
| 27 | `organisation.metadata.regulatory_structure.canada` | list | `organisation.metadata.regulatory_structure` | metadata |
| 28 | `organisation.metadata.regulatory_structure.canada[]` | leaf | `organisation.metadata.regulatory_structure` | metadata |
| 29 | `vendors[].ownership_structure.parent_company` | leaf | `vendors[].ownership_structure` | metadata |
| 30 | `vendors[].ownership_structure.country` | leaf | `vendors[].ownership_structure` | metadata |
| 31 | `vendors[].ownership_structure.publicly_traded` | leaf | `vendors[].ownership_structure` | metadata |
| 32 | `vendors[].alternative_vendors[]` | leaf | `vendors[].alternative_vendors` | metadata |
| 33 | `vendors[].metadata.exit_plan` | leaf | `vendors[].metadata` | metadata |
| 34 | `vendors[].metadata.contractual_terms` | leaf | `vendors[].metadata` | metadata |
| 35 | `vendors[].metadata.certifications` | list | `vendors[].metadata` | metadata |
| 36 | `vendors[].metadata.certifications[]` | leaf | `vendors[].metadata` | metadata |
| 37 | `services[].metadata.expected_mttr_minutes` | leaf | `services[].metadata` | metadata |
| 38 | `services[].metadata.network_zone` | leaf | `services[].metadata` | metadata |
| 39 | `services[].metadata.last_resilience_test_days` | leaf | `services[].metadata` | metadata |
| 40 | `services[].metadata.important_business_service` | leaf | `services[].metadata` | metadata |
| 41 | `services[].metadata.customer_segment` | leaf | `services[].metadata` | metadata |
| 42 | `services[].regulatory_scope[]` | leaf | `services[].regulatory_scope` | metadata |
| 43 | `services[].metadata.business_capability` | leaf | `services[].metadata` | metadata |
| 44 | `services[].metadata.backup_policy` | object | `services[].metadata` | metadata |
| 45 | `services[].metadata.backup_policy.frequency` | leaf | `services[].metadata` | metadata |
| 46 | `services[].metadata.backup_policy.retention_days` | leaf | `services[].metadata` | metadata |
| 47 | `services[].metadata.backup_policy.tested_within_days` | leaf | `services[].metadata` | metadata |
| 48 | `services[].metadata.backup_policy.encryption_at_rest` | leaf | `services[].metadata` | metadata |
| 49 | `services[].metadata.rpo_minutes` | leaf | `services[].metadata` | metadata |
| 50 | `services[].metadata.external_party_type` | leaf | `services[].metadata` | metadata |
| 51 | `teams[].key_capabilities[]` | leaf | `teams[].key_capabilities` | metadata |
| 52 | `data_flows[].regulatory_constraints[]` | leaf | `data_flows[].regulatory_constraints` | metadata |
| 53 | `team_locations[].skills_in_region[]` | leaf | `team_locations[].skills_in_region` | metadata |

### 3.3 Two ledger rows that overstate what was built

> **ADDENDUM — both findings were acted on.** This audit was run against ledger revision
> "98 rows". Both discrepancies below were real, and the adapter was corrected rather than
> the report softened. In the current ledger (**100 rows**):
> `services[].data_classification` is now classified **`not_representable`** with the reason
> stated in (a); the dead `_index_team_clearance()` computation was removed from
> `bin/10_map_topology.py`; the `clearance:` block of `experiment.yaml` is now explicitly
> marked *designed but not realised*; and `services[].metadata` gained a tightened note plus
> two new dedicated rows, `services[].metadata.network_zone` and
> `services[].metadata.expected_mttr_minutes`, both `not_representable`. The corrected
> classification totals are 11 direct / 16 transformed / 43 metadata / 30 not representable.
> The analysis below is retained verbatim as the audit trail. The compiled world did not
> change: the generated import document is byte-identical before and after, so every digest
> and every score in `docs/results.md` is unaffected.


The coverage audit turned up two rows whose stated SynthWorld target is not present in the compiled
artefacts. Both are recorded here rather than silently corrected.

**(a) `services[].data_classification` is classified `represented_directly` but is not realised.**

The ledger row reads:

> `services[].data_classification` → *ABAC ResourceClassificationFact + subject clearance derivation* —
> "Maps 1:1 onto SynthWorld InformationClassification; also drives each team's derived clearance
> level (max over primary-owned services)."

What is actually true:

* `ResourceSetTemplateV1` (wheel `synthworld/enterprise/models.py:210`) has fields
  `key, tenant_key, organisation_key, target_kind, owner_unit_key, instance_count, actions`. There is
  **no classification field**, so the value cannot ride into the universe on the resource set.
* The construct the ledger names does exist elsewhere: `ResourceClassificationFactV1` and the
  `classification_within_clearance` predicate are in `synthworld/enterprise/abac/models.py`, and
  `InformationClassification` is a real 4-value enum. So the mapping was *possible*.
* But `02-synthworld-public/authorization/abac-state.json` contains exactly six fact kinds —
  `subject_tenant_id`, `resource_tenant_id`, `action_id`, `action_class`, `resource_target_kind`,
  `environment_network_zone` — 3 209 of each. **No `resource_classification` fact was emitted, and no
  clearance fact was emitted.**
* Inside the adapter, `_index_team_clearance()` computes `self.team_max_classification`; grep confirms
  that attribute is assigned at `10_map_topology.py:111` and **never read again**.

Correct classification for this field as the pipeline currently stands: `experiment_metadata`
(computed, then dropped). The `clearance:` block of `experiment.yaml` is likewise dead configuration
today. This is the single largest discrepancy between the ledger and the built world.

**(b) `services[].metadata` (blanket `experiment_metadata`) — the note is right, the wording invites
a wrong inference.**

The note says the block holds "MTTR, network zone hints, etc." An `environment_network_zone` ABAC
fact *is* emitted, so a reader may reasonably assume `services[].metadata.network_zone` feeds it. It
does not. `20_build_world.py:744` derives the zone purely from subject kind — `partner` for accounts,
`internal` for principals. The topology's own `network_zone` vocabulary
(`dmz`, `data`, `external`, `management`, `application`, 5 values on all 35 services) is unused, and
could not map anyway: SynthWorld's `NetworkZone` enum is `internal | partner | public` only, with no
defensible correspondence to the five topology values.

## 4. Mapping by collection

Rows are exactly the adapter's own ledger rows, unmodified. Classification abbreviations follow §2.
Where §3.3 contradicts a row, the contradiction stands — the row is reproduced as-issued.

### 4.1 `organisation` — 1 record(s), 17 ledger rows

direct 0 · transformed 3 · metadata 11 · not representable 3

| Field | Classification | SynthWorld target | Notes |
|---|---|---|---|
| `organisation.industry_preset` | metadata | - | As above. |
| `organisation.metadata.annual_revenue_usd` | not representable | - | Financial figure; no authorization construct. |
| `organisation.metadata.benchmark_reference` | metadata | - | Provenance prose. |
| `organisation.metadata.employee_count_total` | metadata | - | Whole-bank headcount; the compiled world sizes populations from team_locations instead. |
| `organisation.metadata.headquarters` | metadata | - | No SynthWorld geographic construct. |
| `organisation.metadata.important_business_services` | metadata | - | Regulatory concept (UK operational resilience); no SynthWorld construct. |
| `organisation.metadata.it_budget_usd` | not representable | - | As above. |
| `organisation.metadata.legal_entity_footprint` | transformed | blueprint.tenants[] | The four legal entities become the four bank authorization tenants. The prose description of each entity is not representable and is kept as experiment metadata. |
| `organisation.metadata.lines_of_defence` | transformed | role(risk-oversight) | Second and third line of defence become a read-only oversight role. The specific named functions are experiment metadata. |
| `organisation.metadata.major_offices` | not representable | - | No SynthWorld location construct. |
| `organisation.metadata.regulatory_structure` | metadata | - | Jurisdiction -> regime map; no SynthWorld construct. |
| `organisation.metadata.target_operating_model` | metadata | - | Prose. |
| `organisation.metadata.team_model` | metadata | - | Prose. |
| `organisation.metadata.technology_and_operations_fte` | metadata | - | As above. |
| `organisation.name` | metadata | - | SynthWorld organisations are keyed logically; the display name is recorded in the mapping report and HTML view. |
| `organisation.regions` | transformed | tenant assignment key | Each region is assigned to a legal-entity tenant by experiment.yaml tenancy.region_to_tenant. SynthWorld has no geographic construct, so region itself is not representable. |
| `organisation.scale_preset` | metadata | - | Generator hint for the tool that produced the topology; no SynthWorld construct. |

### 4.2 `vendors` — 19 record(s), 12 ledger rows

direct 0 · transformed 3 · metadata 7 · not representable 2

| Field | Classification | SynthWorld target | Notes |
|---|---|---|---|
| `vendors[].alternative_vendors` | metadata | - | Resilience substitutability; no authorization construct. |
| `vendors[].catalogue_slug` | metadata | - | Vendor catalogue identifier. |
| `vendors[].criticality_to_org` | metadata | - | No authorization construct. |
| `vendors[].data_processor` | transformed | vendor unit inclusion predicate | Only data-processor vendors get a unit and supplier population, because only they plausibly hold principals touching bank data. |
| `vendors[].headquarters_country` | metadata | - | No SynthWorld geographic construct. |
| `vendors[].jurisdiction` | metadata | - | Legal jurisdiction; distinct from the tenant axis, which is derived from the bank's own legal entities. |
| `vendors[].metadata` | metadata | - | Per-vendor free-form metadata. |
| `vendors[].monthly_cost_usd` | not representable | - | Financial figure. |
| `vendors[].name` | transformed | blueprint.tenants[vendor-external] + units + supplier populations | Third parties are modelled as one external tenant containing a department unit per data-processor vendor. |
| `vendors[].ownership_structure` | metadata | - | Corporate ownership; no SynthWorld construct. |
| `vendors[].security_assessment_date` | not representable | - | A real calendar date. SynthWorld ticks are dimensionless logical integers with no calendar, so this cannot be mapped without inventing a clock. See the limitations report. |
| `vendors[].vendor_type` | transformed | agent account allocation predicate | vendor_type=ai_ml selects which services get an agent-kind account, supplying the agent-binding negative case. |

### 4.3 `services` — 35 record(s), 15 ledger rows

direct 2 · transformed 2 · metadata 3 · not representable 8

| Field | Classification | SynthWorld target | Notes |
|---|---|---|---|
| `services[].baseline_error_rate` | not representable | - | SynthWorld models identity and access only; error rate is a resilience/finance property with no authorization construct. |
| `services[].baseline_latency_ms` | not representable | - | SynthWorld models identity and access only; latency is a resilience/finance property with no authorization construct. |
| `services[].baseline_throughput_rps` | not representable | - | SynthWorld models identity and access only; throughput is a resilience/finance property with no authorization construct. |
| `services[].bcm_plan` | not representable | - | SynthWorld models identity and access only; business continuity plan is a resilience/finance property with no authorization construct. |
| `services[].criticality` | metadata | - | critical/high/medium has no SynthWorld construct. It is NOT mapped onto InformationClassification, which would conflate availability criticality with confidentiality. |
| `services[].data_classification` | direct | ABAC ResourceClassificationFact + subject clearance derivation | Maps 1:1 onto SynthWorld InformationClassification; also drives each team's derived clearance level (max over primary-owned services). |
| `services[].disaster_recovery_plan` | not representable | - | SynthWorld models identity and access only; disaster recovery plan is a resilience/finance property with no authorization construct. |
| `services[].incident_reporting_contact` | not representable | - | SynthWorld models identity and access only; incident contact is a resilience/finance property with no authorization construct. |
| `services[].metadata` | metadata | - | Per-service operational metadata (MTTR, network zone hints, etc.) is retained as experiment metadata; see the mapping report for the full per-key breakdown. |
| `services[].monthly_cost_usd` | not representable | - | SynthWorld models identity and access only; cost is a resilience/finance property with no authorization construct. |
| `services[].name` | direct | resource_set + workload population | Each service becomes one resource set and one workload population. |
| `services[].regulatory_scope` | metadata | - | Regulatory regime list has no SynthWorld construct. Retained as experiment metadata and shown in the HTML view. |
| `services[].service_type` | transformed | resource_set.target_kind | api->api and database->data_store are exact. cache->data_store, queue->api, worker->application and external->application are approximations: SynthWorld TargetKind has no cache, messaging or external-system construct. The original service_type is preserved in the mapping report. |
| `services[].service_type=external` | transformed | home tenant fallback | The three external network services (card-scheme-network, swift-network, uk-sepa-clearing-network) have no service_deployments row. They inherit the tenant where their primary owning team has the largest regional headcount, and their resource_set instance_count is forced to 1. |
| `services[].sla_availability_target` | not representable | - | SynthWorld models identity and access only; availability target is a resilience/finance property with no authorization construct. |

### 4.4 `teams` — 15 record(s), 4 ledger rows

direct 1 · transformed 0 · metadata 3 · not representable 0

| Field | Classification | SynthWorld target | Notes |
|---|---|---|---|
| `teams[].headcount` | metadata | - | Whole-team headcount. Populations are sized from the per-region team_locations rows instead, which sum to a different total; both figures appear in the mapping report. |
| `teams[].key_capabilities` | metadata | - | Free-text capability list; no SynthWorld construct. |
| `teams[].name` | direct | unit(kind=team) | Each team becomes a team unit in every tenant it has a location in. |
| `teams[].team_type` | metadata | - | product/platform/sre/security/shared_services has no SynthWorld unit-kind analogue (UnitKind is division\|department\|team only). |

### 4.5 `domains` — 7 record(s), 3 ledger rows

direct 1 · transformed 0 · metadata 1 · not representable 1

| Field | Classification | SynthWorld target | Notes |
|---|---|---|---|
| `domains[].description` | metadata | - | Free text; no SynthWorld construct. Surfaced in the HTML view. |
| `domains[].name` | direct | unit(kind=division) | Each business domain becomes a division unit, replicated per tenant. |
| `domains[].parent_domain` | not representable | - | The field exists but is null for all 7 domains, so no domain hierarchy can be derived. The unit tree is consequently two levels (division -> team), not three. Nothing is discarded because nothing is present. |

### 4.6 `service_dependencies` — 104 record(s), 5 ledger rows

direct 0 · transformed 2 · metadata 2 · not representable 1

| Field | Classification | SynthWorld target | Notes |
|---|---|---|---|
| `service_dependencies[].criticality` | metadata | - | Dependency criticality has no authorization construct. |
| `service_dependencies[].dependency_type` | metadata | - | sync_http/async_event/data_read/... has no SynthWorld construct; every edge is flattened to a single 'invoke' action. |
| `service_dependencies[].source` | transformed | account_allocations[] (workload) + account_access_atom_rules[] | A service->service edge becomes the caller's workload account holding invoke on the callee's resource set. This is what makes the wrong-runtime-binding negative case testable: a workload account invoking a service it has no dependency edge to. |
| `service_dependencies[].target` | transformed | account_access_atom_rules[] target | Callee service resource set. |
| `service_dependencies[].timeout_ms` | not representable | - | Optional field (present on 65 of 104 edges). A call timeout has no SynthWorld construct. |

### 4.7 `service_deployments` — 98 record(s), 4 ledger rows

direct 1 · transformed 2 · metadata 1 · not representable 0

| Field | Classification | SynthWorld target | Notes |
|---|---|---|---|
| `service_deployments[].deployment_type` | transformed | service home tenant selection + resource_set.instance_count | deployment_type=primary picks the service's home legal entity; the row count becomes instance_count. The four deployment types (primary/failover/read_replica/edge_cache) have no SynthWorld construct and are otherwise experiment metadata. |
| `service_deployments[].infrastructure_provider` | metadata | - | Hosting provider has no SynthWorld construct; retained in the mapping report and the HTML view only. |
| `service_deployments[].region` | transformed | tenant assignment | Region -> legal entity via experiment.yaml tenancy.region_to_tenant. |
| `service_deployments[].service` | direct | resource_set reference | Foreign key into services[].name. |

### 4.8 `vendor_dependencies` — 36 record(s), 5 ledger rows

direct 1 · transformed 1 · metadata 3 · not representable 0

| Field | Classification | SynthWorld target | Notes |
|---|---|---|---|
| `vendor_dependencies[].criticality` | metadata | - | No authorization construct. |
| `vendor_dependencies[].dependency_type` | metadata | - | 21 distinct free-form values; no SynthWorld construct. |
| `vendor_dependencies[].fallback_vendor` | metadata | - | Optional (15 of 36 rows). Resilience concept, not access. |
| `vendor_dependencies[].service` | direct | agent/supplier account target | Foreign key into services[].name. |
| `vendor_dependencies[].vendor` | transformed | supplier population.count | The number of services a vendor supports becomes the size of its supplier population. This count is derived, not stated in the source. |

### 4.9 `service_ownerships` — 72 record(s), 3 ledger rows

direct 2 · transformed 1 · metadata 0 · not representable 0

| Field | Classification | SynthWorld target | Notes |
|---|---|---|---|
| `service_ownerships[].ownership_type` | transformed | roles[] + role_hierarchy + role_grants | primary/on_call/supporting become the seniority ladder service-owner > service-operator > service-contributor, each with a different action grant. This ladder is what the scope-exceeded denial case exercises. |
| `service_ownerships[].service` | direct | principal_access_atom_rules[].resource_set_key | Foreign key into services[].name. |
| `service_ownerships[].team` | direct | principal_access_atom_rules[].population_key | Foreign key into teams[].name; selects which populations get atoms. |

### 4.10 `service_domains` — 47 record(s), 3 ledger rows

direct 3 · transformed 0 · metadata 0 · not representable 0

| Field | Classification | SynthWorld target | Notes |
|---|---|---|---|
| `service_domains[].domain` | direct | unit(division) reference | Foreign key into domains[].name. |
| `service_domains[].is_primary` | direct | resource_set owner division selection | Selects which domain division owns the service's resource set. |
| `service_domains[].service` | direct | resource_set -> unit edge | Foreign key into services[].name. |

### 4.11 `data_flows` — 6 record(s), 20 ledger rows

direct 0 · transformed 0 · metadata 9 · not representable 11

| Field | Classification | SynthWorld target | Notes |
|---|---|---|---|
| `data_flows[].adequacy_decision` | not representable | - | GDPR transfer concept; no SynthWorld construct. |
| `data_flows[].confidentiality` | metadata | - | Duplicate of data_classification on all 6 rows. |
| `data_flows[].data_category` | metadata | - | personal/etc; no SynthWorld construct. |
| `data_flows[].data_classification` | metadata | - | Per-flow classification; the resource-set classification is taken from services[].data_classification instead. |
| `data_flows[].encryption` | not representable | - | Cryptographic control, not an access relation. |
| `data_flows[].encryption_at_rest` | not representable | - | As above. |
| `data_flows[].encryption_in_transit` | not representable | - | As above. |
| `data_flows[].erasure_days` | not representable | - | Retention period; no SynthWorld construct. |
| `data_flows[].erasure_mechanism` | not representable | - | As above. |
| `data_flows[].has_bcr` | not representable | - | As above. |
| `data_flows[].has_dpa` | not representable | - | Contractual flag; no SynthWorld construct. |
| `data_flows[].has_sccs` | not representable | - | As above. |
| `data_flows[].is_cross_border` | metadata | - | Transfer property, not an access decision. |
| `data_flows[].regulatory_constraints` | metadata | - | Regime list; no SynthWorld construct. |
| `data_flows[].source_region` | metadata | - | As above. |
| `data_flows[].source_service` | metadata | - | Data-flow edges describe payload movement, not principal access. Modelling them as access atoms would assert authorization facts the topology does not state. |
| `data_flows[].target_region` | metadata | - | As above. |
| `data_flows[].target_service` | metadata | - | As above. |
| `data_flows[].transfer_mechanism` | not representable | - | As above. |
| `data_flows[].volume_gb_per_day` | not representable | - | Throughput figure. |

### 4.12 `team_locations` — 36 record(s), 7 ledger rows

direct 1 · transformed 2 · metadata 3 · not representable 1

| Field | Classification | SynthWorld target | Notes |
|---|---|---|---|
| `team_locations[].can_operate_remotely` | metadata | - | Same reasoning as office_type. |
| `team_locations[].headcount_in_region` | transformed | population.count | Divided by experiment.yaml scaling.population_divisor (50), ceiling, minimum 1. Lossy by construction: the original headcount is preserved verbatim in the mapping report. Setting the divisor to 1 reproduces the full-scale world. |
| `team_locations[].office_type` | metadata | - | office/remote has no SynthWorld construct. Note: NetworkZone (internal\|partner\|public) exists but mapping remote->public would assert a network fact the topology does not state. |
| `team_locations[].region` | transformed | population tenant assignment | Region -> legal-entity tenant. |
| `team_locations[].skills_in_region` | metadata | - | Free-text skills; no SynthWorld construct. |
| `team_locations[].team` | direct | population -> unit edge | Foreign key into teams[].name. |
| `team_locations[].time_zone` | not representable | - | SynthWorld ticks are dimensionless logical integers with no wall clock or zone, so a time zone cannot be represented honestly. |

## 5. Summary of classifications

### 5.1 By collection

| Collection | direct | transformed | metadata | not representable | ledger rows |
|---|---:|---:|---:|---:|---:|
| `organisation` | 0 | 3 | 11 | 3 | 17 |
| `vendors` | 0 | 3 | 7 | 2 | 12 |
| `services` | 2 | 2 | 3 | 8 | 15 |
| `teams` | 1 | 0 | 3 | 0 | 4 |
| `domains` | 1 | 0 | 1 | 1 | 3 |
| `service_dependencies` | 0 | 2 | 2 | 1 | 5 |
| `service_deployments` | 1 | 2 | 1 | 0 | 4 |
| `vendor_dependencies` | 1 | 1 | 3 | 0 | 5 |
| `service_ownerships` | 2 | 1 | 0 | 0 | 3 |
| `service_domains` | 3 | 0 | 0 | 0 | 3 |
| `data_flows` | 0 | 0 | 9 | 11 | 20 |
| `team_locations` | 1 | 2 | 3 | 1 | 7 |
| **Total** | **12** | **16** | **43** | **27** | **98** |

### 5.2 Headline ratio

Of 98 ledger rows, **28 (28.6%) are consumed** by the compiled world (12 direct + 16 transformed) and
**70 (71.4%) are not** (43 metadata + 27 not representable). Adjusting for §3.3(a) —
`services[].data_classification` is claimed direct but is not realised — the consumed figure is
**27 rows (27.6%)**.

Read against the raw estate rather than the ledger, the ratio is starker: two collections
(`data_flows`, 6 records / 20 fields, and the entire `organisation.metadata` block, 40 of the 45
organisation-level paths) contribute **nothing** to the compiled universe.

## 6. Lossy transformations

Every rule below changes or discards information. Each entry states what was lost, why, the exact
factor, and the recovery route.

### L1 — Population headcount divisor (7 150 → 159)

| | |
|---|---|
| **Source** | `team_locations[].headcount_in_region`, 36 rows, range 70…520, Σ = **7 150** |
| **Rule** | `count = max(min_population_count, ceil(headcount_in_region / population_divisor))` with `population_divisor: 50`, `min_population_count: 1` (`experiment.yaml` §scaling) |
| **Result** | 36 employee populations, Σ `count` = **159** declared principals |
| **What is lost** | Individual headcount magnitude, and the ratio between teams. `7150 / 50 = 143` exactly; the emitted total is 159 because the ceiling is applied **per row**, adding 16 phantom heads. A team of 70 and a team of 100 both become 2. |
| **Why** | One SynthWorld principal per head yields ≈7 150 principals and a proportional atom explosion, which cannot be loaded into Topaz and scored inside one reproducible run. |
| **Recovery** | Set `scaling.population_divisor: 1` and re-run stage 10; the population keys (`pop-wf-<team>-<region>`) are unchanged, so the scaled and full-scale worlds are row-aligned. The raw values remain in the topology. |

Two further headcount totals exist in the source and neither is used: `Σ teams[].headcount` = **15 850**
and `organisation.metadata.technology_and_operations_fte` = **14 950**. Three totals, three different
numbers; the adapter picks `team_locations` because it is the only one with a regional breakdown, and
records the choice in the `teams[].headcount` ledger row. Any consumer treating the compiled
principal count as a scaled version of "the bank's headcount" is using the wrong denominator.

### L2 — `services[].service_type` → `TargetKind` (6 values → 3)

`TargetKind` is a closed enum: `application | api | tool | data_store | environment`
(`synthworld/enterprise/models.py:108`). The topology's `service_type` has six values.

| `service_type` | services | → `TargetKind` | Exact? | Loss |
|---|---:|---|---|---|
| `api` | 22 | `api` | exact | none |
| `database` | 4 | `data_store` | exact | none |
| `cache` | 1 | `data_store` | **approximation** | a cache has no durability contract; `data_store` implies one |
| `queue` | 1 | `api` | **approximation** | `TargetKind` has no messaging construct; async delivery semantics vanish |
| `worker` | 4 | `application` | **approximation** | a background worker has no request surface; `application` implies one |
| `external` | 3 | `application` | **approximation** | third-party ownership vanishes entirely — see L5 |

Resulting resource sets: `api` 23, `data_store` 5, `application` 7 (35 total). After instance
expansion: `api` 72, `data_store` 16, `application` 13 authorization targets (101 total).

* **What is lost:** the 6-way distinction becomes 3-way. 9 of 35 services (25.7%) carry an
  approximated kind. `tool` and `environment` are never used.
* **Why:** no closer member of the enum exists.
* **Recovery:** the resource-set key is `rs-<slug(services[].name)>`, a 1:1 injection from the
  service name, so the original `service_type` is recoverable by joining any resource set or
  authorization target back to the topology on that key.
* **Judgement call:** `queue → api` was chosen over `queue → tool`. An event bus is consumed over a
  request interface far more than it resembles a tool, but `tool` was a defensible alternative and
  was rejected on that reading alone. `worker → application` was chosen over `worker → tool` on the
  same reasoning. Both are admitted approximations, not derivations.

### L3 — `domains[].parent_domain` is null on all 7 rows; the unit tree is 2 levels, not 3

* **Source:** `domains[].parent_domain` — declared as a self-referencing FK, value `null` in 7 of 7
  records. Distinct cardinality 1.
* **What is lost:** *nothing from the source* — there is no hierarchy in the instance data to lose.
  What is lost is the **capability**: `experiment.yaml` §units names `domain_unit_kind: division` and
  `team_unit_kind: team`, and SynthWorld's `UnitKind` offers `division | department | team`, so a
  three-level tree was expressible. The source cannot fill it.
* **Resulting tree:**

```
tenant (uk | europe | americas | apac-mea)
└── division   ×7   (every domain, replicated in every bank tenant → 28 units)
    └── team   ×n   (only where the team has a team_locations row → 35 units)

tenant vendor-external
└── department ×17  (one per data-processor vendor; parent_unit_key = null → a root)
```

  80 units total, matching the compiled universe exactly. Depth is 2 in the bank tenants and 1 in
  `vendor-external`.
* **Rule:** a team's parent division is the domain that is primary for the plurality of services the
  team owns with `ownership_type = primary`; ties broken by domain name ascending
  (`experiment.yaml units.team_parent_rule: plurality_primary_service_domain`).
* **The inverse loss:** the mapping is lossy in the *other* direction too. 7 domains become **28**
  division units, because each domain is replicated per bank tenant. A domain is no longer a single
  node — "Payments & Treasury" exists four times with four distinct unit ids and no edge between
  them. Any query for "the Payments & Treasury division" must union four units.
* **Recovery:** unit keys are `unit-<tenant>-div-<slug(domain)>`; strip the tenant prefix to recover
  the 7 source domains.

### L4 — 6 `dependency_type` values collapse to a single `invoke` action

| | |
|---|---|
| **Source** | `service_dependencies` — 104 rows; `dependency_type` ∈ {`async_event` 35, `sync_http` 30, `data_read` 18, `sync_grpc` 9, `data_write` 8, `async_queue` 4} |
| **Rule** | every surviving edge becomes one workload-account allocation plus one account access-atom rule with `action: "invoke"`. The action ladder is fixed at `[read, write, invoke, deploy]` (`experiment.yaml resources.actions`). |
| **Result** | 49 edges dropped as cross-tenant (§8); **55 declared** → 55 `alloc-dep-*` allocations and 55 `aar-dep-*-invoke` atom rules |
| **What is lost** | (i) transport semantics — sync vs async is gone; (ii) **direction of data** — `data_read` and `data_write` both become `invoke`, so a read-only dependency is indistinguishable from a write dependency even though `read` and `write` actions exist in the ladder; (iii) `criticality` (`critical` 39 / `optional` 42 / `degraded_operation` 23); (iv) `timeout_ms` (present on 65 of 104). |
| **Why** | SynthWorld has no transport, no messaging and no criticality construct. `invoke` is the only action in the ladder that means "one service calls another" regardless of payload direction. |
| **Recovery** | The allocation key is `alloc-dep-<slug(source)>-<slug(target)>` — a 1:1 injection from the source edge — so all four dropped attributes are recoverable by joining back to `service_dependencies` on `(source, target)`, which the inventory confirms is unique at 104/104. For the 49 dropped edges, `cross-boundary-pairs.json` preserves `dependency_type` verbatim. |
| **Judgement call** | Mapping `data_read → read` and `data_write → write` was available and was **not** taken. The rejected reading: those actions in this world denote a principal reading a resource set, not a service reading another service's data, and reusing them would have made workload atoms indistinguishable from workforce atoms at scoring time. That is defensible but it is a choice, and it costs the read/write distinction on 26 of 104 edges. |

### L5 — The 3 `external` services have no deployments, so their tenant is invented

| | |
|---|---|
| **Affected** | `card-scheme-network`, `swift-network`, `uk-sepa-clearing-network` — all `service_type: external` |
| **Source state** | 0 `service_deployments` rows, 0 `vendor_dependencies` rows, no `incident_reporting_contact`, `monthly_cost_usd == 0.0`, no `on_call` ownership row. They appear only as dependency targets, one `primary` ownership row each, and `service_domains` rows. |
| **Rule** | home tenant = the tenant of the region in which the service's `primary` owning team has the **largest** `headcount_in_region`; ties broken by region name ascending. `instance_count = max(1, deployment_count) = 1`. |
| **Outcome** | All three are primary-owned by `Payments Engineering`, whose locations are UK South (London) **360**, EU Central (Frankfurt) **280**, Asia Pacific (Singapore) **160**. All three therefore land in tenant **`uk`**. |
| **What is lost** | The most important fact about these services — that the bank does not operate them — has no representation. In the compiled universe they are ordinary `application` targets, homed in `uk`, owned by the Payments Engineering team unit, indistinguishable from an internally-built application. `metadata.external_party_type` (`card_scheme`, `market_infrastructure`, `financial_messaging_network`) is not carried. |
| **Why** | Every `ResourceSetTemplateV1` requires a `tenant_key` and an `instance_count > 0`. There is no "unowned" or "third-party" tenant concept for a *service*; `vendor-external` holds vendor principals, not resources. |
| **Recovery** | `services[].service_type == "external"` and `services[].metadata.external_party_type` in the source. Also detectable structurally: these are the only services with zero `service_deployments` rows. |
| **Judgement call** | Two alternatives were rejected. (a) *Drop them* — rejected because they are the target of real `service_dependencies` edges and 3 `service_ownerships` rows, and dropping them would break referential integrity for those rows. (b) *Home them in `vendor-external`* — rejected because every bank call to SWIFT would then be a cross-tenant denial, which would both distort the case mix toward case C and misstate the topology, which says the payments team owns these integrations. The chosen rule is a heuristic with no basis in the source data; the assignment "SWIFT is a UK resource" is manufactured. |

### L6 — `service_deployments` (98 rows, 4 types) collapses to one integer per service

`deployment_type` has four values — `primary` 32, `failover` 32, `read_replica` 19, `edge_cache` 15 —
and is used twice: `primary` selects the home tenant, and the **row count per service** becomes
`resource_set.instance_count`. Σ = 98 + 3 forced = **101**.

Lost: which region each replica sits in, and what kind of replica it is. A service with one primary
and three edge caches is indistinguishable from one with four primaries. `infrastructure_provider`
(Azure 43 / GCP 38 / AWS 17) is dropped entirely. Recovery: join `rs-<service>` back to
`service_deployments`, whose `(service, region)` key is unique at 98/98.

### L7 — 5 regions collapse to 4 bank tenants

`tenancy.region_to_tenant` maps `EU West (Ireland)` and `EU Central (Frankfurt)` to the same tenant
`europe`. All 36 `team_locations` rows and all 98 `service_deployments` rows therefore lose the
Ireland/Frankfurt distinction; a Dublin team and a Frankfurt team are in the same authorization
boundary. Recovery: population keys retain the region — `pop-wf-<team>-<region>` — so the region is
fully recoverable from the key even though it is not a modelled attribute.

### L8 — `service_ownerships` 72 rows → 70 pairs (2 rows silently dropped)

`(service, team)` is **not** unique in the source: `SRE & Observability` holds both `primary` and
`on_call` on `observability-platform` and on `resilience-testing-orchestrator`. The adapter keeps the
most senior `ownership_type` per pair (`primary < on_call < supporting`) because two roles granting
the same action would emit a duplicate atom and be rejected with `duplicate_access_atom_declaration`.

This is **lossless in effect but not by construction**: `service-owner` and `service-operator` are
both configured as `[read, write, invoke, deploy]`, so the junior grant is a subset of the senior.
Change `roles.grants` so that operator holds an action owner does not, and these two rows start
losing real access silently. Recovery: `service_ownerships` in the source; the true key is
`(service, team, ownership_type)`, unique at 72/72.

### L9 — `vendor_dependencies` 36 edges become 17 population sizes

Only the **count** of `vendor_dependencies` rows per vendor survives, as the supplier population's
`count` (`max(1, rows)`); Σ = **38** across 17 populations. The edge itself — which service a vendor
supplies — is not declared. Lost with it: the 21-value `dependency_type` vocabulary, `criticality`
(critical 15 / high 15 / medium 6) and `fallback_vendor` (15 of 36 rows). The one exception is
`vendor_type: ai_ml`, which selects services for an `agent`-kind account: exactly one such allocation
exists (`alloc-agent-*`), expanding to 3 agent accounts.

### L10 — 19 vendors become 17 units

`vendors[].data_processor` is the inclusion predicate. It is present on 17 of 19 vendors (always
`true` where present). **`Bloomberg` and `LSEG Workspace` are excluded** — they are the same two
vendors missing `security_assessment_date`. They contribute no unit, no group, no role and no
principals. Recovery: the source `vendors` list.

### L11 — `lines_of_defence` → oversight role: 2 of 4 names silently resolve to nothing

`organisation.metadata.lines_of_defence.second_line` + `third_line` contain four strings. The adapter
grants the `risk-oversight` role to any of them that matches a `teams[].name`:

| String | Resolves to a team? | Effect |
|---|:--:|---|
| `Cyber Security Engineering` | yes | oversight role assigned across all 7 divisions in each of its tenants |
| `Vendor & Resilience Office` | yes | as above |
| `Financial Crime and Compliance` | **no** | **no assignment produced** |
| `Internal Audit and model validation` | **no** | **no assignment produced** |

Half the declared second/third line of defence therefore has no representation. The adapter does not
warn; the `if team not in self.teams: continue` is silent. The topology inventory flags these as soft
references (prose, not team identifiers), so the failure is in the source, but the pipeline should
surface it rather than skip it.

### L12 — Cross-boundary drops

The largest single loss in the pipeline. 135 of 189 ownership combinations and 49 of 104 dependency
edges cannot be declared at all. Treated in full in §8.

## 7. What cannot be represented at all

27 fields are classified `not_representable`. They fall into five groups by reason. A further 43
fields are classified `experiment_metadata`; where the reason is the same absence of a construct,
they are listed alongside, because the distinction between the two labels is a judgement call and an
auditor should see the whole set.

### 7.1 No construct for resilience, SLA or cost figures — 12 fields

SynthWorld's enterprise model contains identity, access and authorization only. There is no
availability, latency, throughput, error-rate, continuity, recovery or money construct anywhere in
the released schema.

| Field | Value range in source |
|---|---|
| `services[].sla_availability_target` | 0.999 … 0.99999, 9 distinct |
| `services[].baseline_latency_ms` | 3.0 … 2400.0, 26 distinct |
| `services[].baseline_throughput_rps` | 40.0 … 42000.0, 30 distinct |
| `services[].baseline_error_rate` | 0.0002 … 0.02, 16 distinct |
| `services[].monthly_cost_usd` | 0.0 … 980000.0 |
| `services[].bcm_plan` | constant `true` (35/35) |
| `services[].disaster_recovery_plan` | constant `true` (35/35) |
| `services[].incident_reporting_contact` | constant, 32/35 |
| `service_dependencies[].timeout_ms` | 200 … 2500, 65 of 104 rows |
| `vendors[].monthly_cost_usd` | 240 000 … 2 400 000 |
| `organisation.metadata.annual_revenue_usd` | 36 200 000 000 |
| `organisation.metadata.it_budget_usd` | 3 100 000 000 |

Related fields classified `experiment_metadata` for the same underlying reason: `services[].criticality`,
`service_dependencies[].criticality`, `vendor_dependencies[].criticality`,
`vendors[].criticality_to_org`, `vendor_dependencies[].fallback_vendor`,
`vendors[].alternative_vendors`, `services[].metadata.*` (MTTR, RPO, backup policy, resilience-test
recency), `services[].regulatory_scope`, `organisation.metadata.regulatory_structure`,
`organisation.metadata.important_business_services`. That is a further ~20 leaf fields describing
operational resilience and regulatory scope, none of which reaches the compiled world.

**Note the asymmetry in labelling.** `services[].bcm_plan` is `not_representable` while
`services[].criticality` is `experiment_metadata`, yet neither has any SynthWorld construct. The
ledger's own rationale for `criticality` gives the real distinction: a *plausible but wrong* mapping
existed (onto `InformationClassification`) and was rejected, whereas for `bcm_plan` no candidate
existed at all. That distinction is not stated in the classification vocabulary and has to be read
out of the notes.

### 7.2 No geographic construct — 1 field `not_representable`, 4 more downgraded

SynthWorld has no location, country, city or region entity. Tenancy is the only spatial-looking axis
and it is a *legal* axis, not a geographic one.

| Field | Classification | Note |
|---|---|---|
| `organisation.metadata.major_offices` (13 cities) | not representable | no location construct |
| `organisation.metadata.headquarters` (`London, UK`) | metadata | identical reason, different label |
| `vendors[].headquarters_country` (5 ISO codes) | metadata | identical reason |
| `vendors[].ownership_structure.country` | metadata (via container row) | identical reason |
| `vendors[].jurisdiction` (5 ISO codes) | metadata | ledger distinguishes it from the tenant axis |
| `organisation.regions` (5 strings) | **transformed** | the *region* is not representable; only its mapping to a tenant survives |

**This is an inconsistency in the ledger, not in the world.** Five fields blocked by the same missing
construct carry three different labels. The substantive fact is uniform: no geography enters the
compiled universe. Region survives only as an opaque substring inside population keys
(`pop-wf-<team>-<region>`), which is a key-naming convention, not a modelled attribute.

`vendors[].jurisdiction`, `vendors[].headquarters_country` and `vendors[].ownership_structure.country`
are, per the inventory, identical row-for-row on all 19 vendors — a redundant triplet. Three fields
carrying one fact, none of which is representable.

### 7.3 No calendar — ticks are dimensionless logical integers — 2 fields

The single hardest constraint. A SynthWorld `tick` is an integer with no unit, no epoch and no zone.
`experiment.yaml` §temporal sets `base_tick: 100`, `expired_tick: 200`, `session_validity_ticks: 50`;
none of those numbers denotes a duration.

| Field | Value | Why unmappable |
|---|---|---|
| `vendors[].security_assessment_date` | constant `2026-02-15T00:00:00Z`, 17 of 19 vendors | A wall-clock instant. Converting it to a tick requires inventing an epoch and a tick length, neither of which the model defines. Any chosen mapping would be an assertion about the world that the source does not make, and would be silently wrong the moment a second date with a different offset appeared. |
| `team_locations[].time_zone` | `Europe/London`, `Europe/Dublin`, `Europe/Berlin`, `Asia/Singapore`, `America/New_York` — 36 of 36 rows | A time zone is an offset function against a wall clock. With no wall clock there is nothing for it to offset. It cannot be approximated; there is no "less precise time zone". |

Consequence for the benchmark: the follow-the-sun operating model stated in
`organisation.metadata.target_operating_model` cannot be exercised at all. Temporal cases in the
corpus (`expired_tick: 200`, 35 expiry cells) test *ordinal* expiry — tick 200 is after tick 100 —
which is a real and scoreable property, but it carries no relationship to the calendar dates or zones
in the source.

### 7.4 No data-transfer or GDPR construct — the whole `data_flows` collection

`data_flows` is 6 records and **21 field paths, of which 20 have ledger rows and 0 reach the compiled
world**: 11 `not_representable`, 9 `experiment_metadata`.

| Concept | Fields | Why nothing holds it |
|---|---|---|
| Transfer legality | `adequacy_decision`, `transfer_mechanism` (`SCC`/`ADEQUACY`), `has_dpa`, `has_sccs`, `has_bcr` | SynthWorld models whether a subject may act on a target. It has no concept of a *transfer* — a movement of data between two resources — and therefore no place to attach a lawful-basis attribute. |
| Cryptographic control | `encryption` (`in_transit`), `encryption_in_transit`, `encryption_at_rest` | Encryption is a protective control over data at rest or in flight, not an access relation. No ABAC fact kind expresses it. |
| Retention / erasure | `erasure_days` (30/45), `erasure_mechanism` (`crypto_erase`/`anonymization`/`physical_delete`) | No lifecycle-of-data construct. Account lifecycle exists; data lifecycle does not. |
| Volume | `volume_gb_per_day` (14…95) | A throughput figure — see §7.1. |
| The edge itself | `source_service`, `target_service`, `source_region`, `target_region` | Classified `experiment_metadata` with an explicit rationale: a data flow is *payload movement*, not *principal access*. Declaring these as access atoms would assert authorization facts the topology does not state. **This is the correct call and it is worth stating plainly: the adapter chose to represent nothing rather than to represent something false.** |
| Classification | `data_classification`, `confidentiality`, `data_category`, `is_cross_border`, `regulatory_constraints` | Per-flow, and the flow does not exist. |

The cost is real: cross-border personal-data movement is the topology's most regulator-relevant
feature, and the compiled benchmark contains no trace of it. The cross-tenant denial cases in §8 are
about *legal-entity boundaries*, not about GDPR transfers, and should not be reported as such.

### 7.5 Declared but empty — 1 field

`domains[].parent_domain` — `null` in 7 of 7 records. Nothing is discarded because nothing is
present; the loss is of a capability, not of data. See L3.

## 8. The cross-tenant declaration constraint

This is the constraint that shaped the world more than any other.

### 8.1 What the importer enforces

The released validator (`synthworld/enterprise/validation.py`) refuses **every** relation type that
crosses a tenant or organisation boundary. These were confirmed against the installed wheel, not
inferred:

| Diagnostic | Line | Message | Guards |
|---|---:|---|---|
| `cross_tenant_access_declaration` | 505 | "access declarations must remain in one tenant and organisation" | population ↔ resource set — i.e. `principal_access_atom_rules[]` and `account_allocations[]` |
| `cross_tenant_membership` | 528 | "membership cannot cross tenant or organisation scope" | population ↔ group |
| `cross_tenant_role_assignment` | 551 | "role assignment cannot cross tenant or organisation scope" | population ↔ role |
| `cross_tenant_group_role_assignment` | 574 | "group-role assignment cannot cross tenant or organisation scope" | group ↔ role |
| `cross_tenant_group_nesting` | 309 | "nested groups must share tenant and organisation scope" | child group ↔ parent group |
| `cross_tenant_role_hierarchy` | 355 | "role hierarchy edges must share tenant and organisation scope" | senior role ↔ junior role |
| `cross_tenant_role_grant` | 382 | "role grants cannot cross tenant boundaries" | role ↔ resource set |

**The closure matters more than any single diagnostic.** A directory has exactly seven ways to route
a subject to a resource — direct atom, account allocation, group membership, group nesting, role
assignment, group-role assignment, role grant — and each of the seven is independently guarded.
There is no indirection that gets a population in tenant *X* to a resource set in tenant *Y*. Tenants
are hard partitions of the declared world, not scopes with an escape hatch.

### 8.2 What that forced

**Ownership.** After deduplicating `service_ownerships` to 70 `(service, team)` pairs (L8), each pair
is expanded over every region in which the team has staff, giving **189** (pair, region) combinations.
The service's home tenant is fixed by its primary deployment region. Where the two differ, the pair
cannot be declared:

| | Count | Share |
|---|---:|---:|
| (pair, region) combinations | 189 | 100% |
| Same tenant → declared | 54 | 28.6% |
| **Cross-tenant → blocked** | **135** | **71.4%** |

Blocked pairs by ownership type: `on_call` 77, `primary` **52**, `supporting` 6. Fifty-two of the
blocked pairs are *primary ownership* — the topology's strongest ownership statement.

Blocked pairs by tenant direction:

| subject tenant → resource tenant | pairs |
|---|---:|
| `uk` → `europe` | 39 |
| `apac-mea` → `europe` | 25 |
| `apac-mea` → `uk` | 23 |
| `americas` → `uk` | 21 |
| `americas` → `europe` | 18 |
| `europe` → `uk` | 9 |

The 54 surviving combinations expand to **201** `principal_access_atom_rules` (49 combinations at
owner/operator grants × 4 actions, plus 5 supporting combinations × 1 action = 196 + 5 = 201).

**Dependencies.** Of 104 `service_dependencies` edges, **49 (47.1%)** connect services homed in
different tenants and are blocked; 55 survive. Blocked by type: `async_event` 21, `sync_http` 14,
`sync_grpc` 5, `data_read` 5, `data_write` 3, `async_queue` 1. Direction: `uk → europe` 26,
`europe → uk` 23.

**The net effect.** The compiled world is a strictly intra-entity projection of a bank that in reality
operates across entities. `SRE & Observability` is on-call for 32 of 35 services in the topology; in
the compiled world its populations can only reach the services homed in the same tenant as the
region they sit in. Any consumer reading the universe as "who can access what at Britannia" is
reading a 28.6% sample of the ownership graph.

### 8.3 How the blocked pairs are still exercised

Two distinct mechanisms, and they are not the same thing.

**(a) Inside SynthWorld — synthesised boundary cells, case class `C`.**
Because a cross-tenant relation cannot be declared, the boundary is expressed at *evaluation* time
instead of *declaration* time. `bin/20_build_world.py` selects principal subjects deterministically
(`_pick(subject_id + ":ct", 12) == 0`), and for their cells asserts a `resource_tenant_id` ABAC fact
naming a real but **different** tenant. An ABAC deny rule then fires. From
`02-synthworld-public/authorization/abac-state.json`:

| Rule | Effect | Cells |
|---|---|---:|
| `abac-allow-same-tenant` | allow | 2 982 |
| `abac-deny-cross-tenant` | deny | **63** |
| `abac-deny-scope-exceeded` | deny | 164 |

All 3 209 cells run under the `rbac_with_abac_guard` profile, so ABAC can only deny, never widen —
the RBAC derivation sets the base outcome and the guard subtracts.

**Be precise about what this is:** those 63 cells are *manufactured* boundary violations over
subjects chosen by a hash, not replays of the 135 + 49 real pairs. The real pairs are not what
SynthWorld scores. The mechanism is honest — an ABAC fact is the only construct the released contract
offers for asserting a boundary the universe forbids declaring — but it does not preserve the
identity of the blocked relations.

**(b) Outside SynthWorld — the pairs file, carried for Topaz replay.**
All 184 blocked relations are written verbatim to
`01-source/generated/cross-boundary-pairs.json`, each carrying enough to reconstruct the request:

```json
{"team": "Financial Crime Technology", "region": "UK South (London)",
 "subject_tenant": "uk", "service": "aml-sanctions-engine", "resource_tenant": "europe",
 "ownership_type": "primary", "population_key": "pop-wf-financial-crime-technology-uk-south-london",
 "resource_set_key": "rs-aml-sanctions-engine"}
```

```json
{"source": "api-gateway", "source_tenant": "uk", "target": "core-banking-ledger",
 "target_tenant": "europe", "dependency_type": "sync_http",
 "population_key": "pop-wl-api-gateway", "resource_set_key": "rs-core-banking-ledger"}
```

`bin/80_validate.py:88` reads the file and asserts the 135 / 49 counts.

**Honest status:** the adapter's comment names "stage 40" as the consumer that replays these against
Topaz. At the time of writing `bin/` contains `10_map_topology.py`, `20_build_world.py`,
`50_build_submission.py`, `60_score.py`, `80_validate.py` and the two Topaz shell scripts. **There is
no stage-40 script.** The data is preserved and count-checked; the Topaz replay is designed and
intended but is not demonstrably executed by anything currently in the repository. This report does
not claim it has run.

## 9. End-to-end count chain

Three stages: the **topology** (source records), the **blueprint** (the emitted
`EnterpriseIdentityAccessImportV1` document — declarative templates and rules), and the **compiled
universe** (concrete entities after SynthWorld expands populations, instances and selectors). Every
figure below was recounted from the artefacts; none is quoted.

### 9.1 Entities

| Topology | → | Blueprint (import doc) | → | Compiled universe |
|---|---|---|---|---|
| `organisation` 1; `legal_entity_footprint` 4 entities; vendors ⇒ 1 external tenant | | `tenants` **5**, `organisations` **5** | | `tenants` **5**, `organisations` **5** |
| `domains` 7 × 4 bank tenants | | division units 28 | | |
| `teams` 15, materialised per tenant where a `team_locations` row exists | | team units 35 | | |
| `vendors` 19, filtered to `data_processor` | | department units 17 | | |
| | | **`units` 80** | | **`units` 80** |
| domains + teams + data-processor vendors | | `groups` **80** (28 division + 35 team + 17 vendor) | | `groups` **80** |
| 3 ownership roles + 1 oversight role, × 7 domains × 4 tenants; + 1 supplier role per vendor | | `roles` **129** (112 + 17) | | `roles` **129** |
| `services` 35 | | `resource_sets` **35**, Σ `instance_count` **101** | | `authorization_targets` **101** |
| 4 actions per target | | `resources.actions` = 4 | | `permissions` **404** (101 × 4) |

### 9.2 Populations and principals

| Kind | Blueprint populations | Sizing rule | Σ count | Compiled principals |
|---|---:|---|---:|---:|
| `employee` | 36 | `ceil(headcount_in_region / 50)`, min 1 — from 7 150 real staff | 159 | 159 |
| `workload` | 35 | `service_deployments` row count per service, min 1 | 101 | 101 |
| `supplier` | 17 | `vendor_dependencies` row count per data-processor vendor, min 1 | 38 | 38 |
| **Total** | **88** | | **298** | **`principals` 298** |

### 9.3 Accounts, subjects and atoms

| Blueprint | Rule | Compiled |
|---|---|---|
| `account_allocations` **127** (90 workload, 36 workforce, 1 agent) | accounts = selected subjects × `accounts_per_selected_subject` × resource-set `instance_count` | `accounts` **597** (490 workload, 104 workforce, 3 agent) |
| — | principals ∪ accounts | `access_subjects` **895** (298 + 597) |
| `principal_access_atom_rules` **201** | expanded over population count × target instances | 2 898 principal atoms |
| `account_access_atom_rules` **92** (55 dependency-`invoke`, 36 workforce-`read`, 1 agent-`invoke`) | expanded over accounts | 276 account atoms |
| | | **`access_atoms` 3 174** |
| — | principals + accounts + groups + targets + units | `relationship_anchors` **1 156** (298 + 597 + 80 + 101 + 80) |

The atom arithmetic reconciles exactly: 2 898 + 276 = 3 174, and the universe's own subject-kind
split of `access_atoms` is `principal` 2 898 / `account` 276.

### 9.4 Directory-RBAC state

Declared rules expand into concrete kernel rows.

| Blueprint `directory_rbac_state` | Rows declared | → | `directory-rbac-kernel.json` |
|---|---:|---|---:|
| `memberships` | 53 | | 197 |
| `group_nesting` | 35 | | 35 |
| `group_role_assignments` | 17 | | 17 |
| `population_role_assignments` | 101 | | `subject_role_assignments` 345 |
| `role_hierarchy` | 56 (4 tenants × 7 domains × 2 pairs) | | 56 |
| `role_grants` | 350 (35 services × 10 grants) | | 1 010 |
| `account_observations` | 0 (added by stage 20) | | 597 |
| `direct_entitlements` | 0 | | 0 |

### 9.5 Evaluation corpus

| | Count |
|---|---:|
| `access_atoms` in the universe | 3 174 |
| Cells at `base_tick` 100 | 3 174 |
| Cells at `expired_tick` 200 (revocation cases) | 35 |
| **`evaluation_cells`** | **3 209** |
| `access_requests` (1:1 with cells, enforced) | 3 209 |
| `contexts` | 2 (`ctx-internal` 2 898 cells, `ctx-partner` 311) |
| Authorization-kernel cell profiles | 3 209, all `rbac_with_abac_guard` |
| ABAC attribute facts | 6 kinds × 3 209 = 19 254 |
| ReBAC relation tuples | 3 209 |

### 9.6 Relations that never became counts

| Topology collection | Records | Reached the universe? |
|---|---:|---|
| `service_ownerships` | 72 | 54 of 189 (pair, region) expansions → 201 atom rules; 135 blocked |
| `service_dependencies` | 104 | 55 → 55 allocations + 55 atom rules; 49 blocked |
| `service_deployments` | 98 | only as `instance_count` (101) and tenant selection |
| `vendor_dependencies` | 36 | only as 17 population sizes (Σ 38) + 1 agent allocation |
| `service_domains` | 47 | as division ownership of resource sets and role scoping |
| `team_locations` | 36 | 36 employee populations |
| `data_flows` | **6** | **none** |

## 10. Judgement calls, with the alternatives that were rejected

Every item here is a decision the source data does not determine. They are separated from the lossy
transformations in §6 because a lossy rule discards a known fact, whereas a judgement call *invents*
one.

| # | Decision | Alternative rejected, and why |
|---:|---|---|
| J1 | **Tenant = legal entity** (`uk`, `europe`, `americas`, `apac-mea`) from `legal_entity_footprint`, plus `vendor-external`. | *Tenant per region* (5) — would make Dublin and Frankfurt separate ring-fences, which the footprint prose does not assert. *Single tenant* — would erase the boundary axis entirely and make case C untestable. The chosen axis is defensible (UK ring-fencing is a real regulatory separation) but the topology never uses the word "tenant". |
| J2 | **`population_divisor: 50`.** | *Divisor 1* — 7 150 employee principals and a proportional atom count, not loadable into Topaz and scoreable in one reproducible run. The divisor is an engineering constraint, not a modelling claim. |
| J3 | **`queue → api`, `worker → application`, `cache → data_store`, `external → application`.** | `tool` for `queue` and `worker` — rejected as a worse fit, but it was a live option and `tool`/`environment` remain unused in the whole world. 9 of 35 services carry an approximated kind. |
| J4 | **`criticality` is NOT mapped to `InformationClassification`.** | Mapping `critical/high/medium` onto `restricted/confidential/internal` — rejected because it conflates availability criticality with data confidentiality. Correct call; the cost is that criticality is absent from 35 services, 104 dependencies, 36 vendor dependencies and 19 vendors. |
| J5 | **`service-operator` (on-call) is granted `deploy`.** | Granting on-call `[read, write, invoke]` only. **The topology says nothing about deploy rights.** `ownership_type: on_call` is a rota fact, not an entitlement fact. The grant is injected specifically to manufacture the scope-exceeded case (`experiment.yaml` says so explicitly). It is a legitimate operational pattern, but it is an assumption added by the experiment, not a fact read from the source. 164 cells depend on it. |
| J6 | **Team's parent division = plurality of primary-owned service domains**, ties broken by domain name ascending. | *No parent* (flat team units) or *one team unit per service domain*. The plurality rule is deterministic but arbitrary: a team that primary-owns 2 services in domain A and 2 in domain B is placed by alphabetical order of domain name. |
| J7 | **External services homed by their owning team's largest-headcount region** → all 3 in `uk`. | *Drop them* (breaks FK integrity for 3 ownership rows and several dependency edges); *home them in `vendor-external`* (every SWIFT call becomes a cross-tenant denial, distorting the case mix). The chosen rule has no basis in the source; "SWIFT is a UK resource" is manufactured. See L5. |
| J8 | **`data_flows` contributes nothing.** | Modelling flow edges as access atoms. Rejected because a data flow is payload movement, not principal access, and declaring it would assert authorization facts the topology does not state. Correct, and the cost — the entire GDPR/transfer dimension — is stated in §7.4. |
| J9 | **`office_type` / `can_operate_remotely` are not mapped to `NetworkZone`.** | `remote → public`. Rejected because it would assert a network fact the source does not state. Correct. `environment_network_zone` is instead derived from subject kind (account → `partner`, principal → `internal`), which is also an injected assumption, though a milder one. |
| J10 | **Divisions and roles are replicated into all 4 bank tenants regardless of whether anything is there.** | Materialising a division only where a service or team exists. Consequence of the choice: **no service is homed in `americas` or `apac-mea`** (18 in `uk`, 17 in `europe`), so those two tenants have 28 roles each, 33 population-role assignments, **zero role grants, zero resource sets and zero access atoms**. 32 of 298 principals (10.7%) hold roles that grant nothing anywhere. A symmetric world was preferred over a dense one; the price is a tenth of the population being inert. |
| J11 | **Most-senior-wins deduplication of `service_ownerships`.** | Keying atoms on `(service, team, ownership_type)`. Lossless only because owner and operator grants happen to be identical (L8). |
| J12 | **`vendors[].data_processor` as the vendor inclusion predicate.** | Including all 19 vendors. Excludes `Bloomberg` and `LSEG Workspace` entirely on the strength of an *optional* boolean that is absent — not `false` — on those two rows. Absence is being read as denial. |

## 11. Reproduction

```bash
.venv/bin/python \
  /home/kademolu/Projects/agent-auth-2/bin/10_map_topology.py
```

Rewrites `01-source/generated/britannia-identity-access-import.yaml`,
`mapping-ledger.json` and `cross-boundary-pairs.json`. Output is byte-stable given the same topology
and `experiment.yaml`: every collection is emitted in sorted key order, with no dict-iteration
dependence, no randomness and no clock.
