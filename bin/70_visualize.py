#!/usr/bin/env python3
"""
70_visualize.py - build a self-contained, public-only HTML reference view of the
compiled Britannia world.

ZONE: experiment-owned tooling.

Inputs (an explicit allowlist, enforced at read time by `load()`):

  02-synthworld-public/**                       the public SynthWorld artifacts
  01-source/config/experiment.yaml              experiment configuration
  01-source/generated/mapping-ledger.json       adapter mapping ledger

Nothing under 06-evaluator/ is opened, and the generated page is audited before
it is written: if any evaluator-side term shows up in the output the script
fails loudly instead of emitting the file.

Output:
  viz/britannia-world.html   single file, no external CSS/JS/fonts/images.

Charts are inline SVG computed here in Python. No chart library, no CDN.
"""

from __future__ import annotations

import html
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "02-synthworld-public"
SOURCE = ROOT / "01-source"
OUT = ROOT / "viz" / "britannia-world.html"

ALLOWED_PREFIXES = (
    PUBLIC.resolve(),
    (SOURCE / "config").resolve(),
    (SOURCE / "generated").resolve(),
)

# Terms that would indicate evaluator-side truth leaking into the page.
# They live here, in the generator, and must never reach the HTML.
AUDIT_TERMS = [
    "birthright",
    "intended_decision",
    "effective_decision",
    "final_decision",
    "reconciliation",
    "binding_status",
    "lifecycle_status",
    "canonical",
    "answer",
    "verdict",
    "same-tenant-allow",
    "deny-scope",
    "deny-cross",
]


def load(path: Path):
    """Read a JSON file, refusing anything outside the input allowlist."""
    rp = path.resolve()
    if not any(str(rp).startswith(str(p) + "/") or rp == p for p in ALLOWED_PREFIXES):
        raise SystemExit(f"refusing to read outside the input allowlist: {rp}")
    return json.loads(rp.read_text("utf-8"))


def read_text(path: Path) -> str:
    rp = path.resolve()
    if not any(str(rp).startswith(str(p) + "/") or rp == p for p in ALLOWED_PREFIXES):
        raise SystemExit(f"refusing to read outside the input allowlist: {rp}")
    return rp.read_text("utf-8")


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

E = html.escape


def num(v) -> str:
    return f"{v:,}"


def short(label: str) -> str:
    """'Example Authorization Target 000085' -> 'Target 000085'."""
    if not label:
        return "-"
    s = label
    for pre, post in (
        ("Example Authorization Target ", "Target "),
        ("Example Organisational Unit ", "Unit "),
        ("Example Access Group ", "Group "),
        ("Example Access Role ", "Role "),
        ("Example Organisation ", "Org "),
        ("Example Tenant ", "Tenant "),
        ("Example Account ", "Account "),
    ):
        if s.startswith(pre):
            return post + s[len(pre):]
    s = re.sub(r"^Example ", "", s)
    return s


def idfrag(uuid: str) -> str:
    return uuid.split("-")[0] if uuid else "-"


def pct(part: int, whole: int) -> str:
    return f"{(100.0 * part / whole):.1f}%" if whole else "-"


# --------------------------------------------------------------------------
# SVG chart primitives (palette comes from CSS custom properties, so the
# charts follow the page theme in both light and dark)
# --------------------------------------------------------------------------

S1 = "var(--series-1)"
S2 = "var(--series-2)"


def _bar_path(x: float, y: float, w: float, h: float, r: float = 4.0) -> str:
    """Horizontal bar anchored at the baseline, rounded only at the data end."""
    if w <= 0.6:
        w = 0.6
    r = min(r, w, h / 2.0)
    if r <= 0.5:
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}"/>'
    return (
        f'<path d="M{x:.1f},{y:.1f} H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} '
        f"V{y + h - r:.1f} Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} "
        f'H{x:.1f} Z"/>'
    )


def hbar(rows, width=620, label_w=186, val_w=62, row_h=25, bar_h=13, series=S1, note=None):
    """rows: (label, value) or (label, value, series_css) or (label, value, series_css, tip)."""
    n = len(rows)
    pad_t, pad_b = 8, 8
    height = pad_t + pad_b + n * row_h
    x0 = label_w
    plot_w = width - label_w - val_w
    mx = max([r[1] for r in rows] + [0]) or 1
    out = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="bar chart">'
    ]
    out.append(
        f'<line x1="{x0}" y1="{pad_t - 2}" x2="{x0}" y2="{height - pad_b + 2}" class="axis"/>'
    )
    for i, r in enumerate(rows):
        label, value = r[0], r[1]
        col = r[2] if len(r) > 2 and r[2] else series
        tip = r[3] if len(r) > 3 and r[3] else f"{label}: {num(value)}"
        y = pad_t + i * row_h
        by = y + (row_h - bar_h) / 2.0
        w = (plot_w - 4) * (value / mx)
        out.append(f'<g><title>{E(tip)}</title>')
        out.append(f'<text class="cat" x="{x0 - 9}" y="{y + row_h / 2 + 4:.1f}">{E(label)}</text>')
        out.append(f'<g fill="{col}">{_bar_path(x0 + 1, by, w, bar_h)}</g>')
        out.append(
            f'<text class="val" x="{x0 + 1 + max(w, 0.6) + 7:.1f}" '
            f'y="{y + row_h / 2 + 4:.1f}">{num(value)}</text>'
        )
        out.append("</g>")
    out.append("</svg>")
    svg = "".join(out)
    tail = f'<p class="chart-note">{E(note)}</p>' if note else ""
    return f'<div class="scroll chart-wrap">{svg}</div>{tail}'


def buckets(values, edges):
    """edges: ascending upper bounds; returns [(label, count), ...]."""
    labels, counts = [], []
    lo = 1
    for hi in edges:
        labels.append(f"{lo}–{hi}" if hi > lo else f"{lo}")
        counts.append(0)
        lo = hi + 1
    labels.append(f"{lo}+")
    counts.append(0)
    for v in values:
        placed = False
        lo = 1
        for i, hi in enumerate(edges):
            if lo <= v <= hi:
                counts[i] += 1
                placed = True
                break
            lo = hi + 1
        if not placed:
            counts[-1] += 1
    return [(l, c) for l, c in zip(labels, counts) if c or True]


# --------------------------------------------------------------------------
# generic tree layout -> SVG (used for the group nesting forest)
# --------------------------------------------------------------------------

def forest_svg(components, children_of, label_of, sub_of, box_w=122, box_h=28,
               hgap=12, vgap=30, max_width=940, comp_gap=26, fill=S1):
    """components: list of root node ids. children_of: id -> [ids]."""
    placed = []  # (x, y, id, depth)
    edges = []

    def measure(node):
        kids = children_of.get(node, [])
        if not kids:
            return box_w
        w = sum(measure(k) for k in kids) + hgap * (len(kids) - 1)
        return max(box_w, w)

    def place(node, x, y, width):
        cx = x + width / 2.0 - box_w / 2.0
        placed.append((cx, y, node))
        kids = children_of.get(node, [])
        if not kids:
            return
        widths = [measure(k) for k in kids]
        total = sum(widths) + hgap * (len(kids) - 1)
        cur = x + (width - total) / 2.0
        for k, w in zip(kids, widths):
            kx = cur + w / 2.0 - box_w / 2.0
            edges.append((cx + box_w / 2.0, y + box_h, kx + box_w / 2.0, y + box_h + vgap))
            place(k, cur, y + box_h + vgap, w)
            cur += w + hgap

    def depth(node):
        kids = children_of.get(node, [])
        return 1 + (max(depth(k) for k in kids) if kids else 0)

    cur_x, cur_y, row_h = 0.0, 0.0, 0.0
    total_w = 0.0
    for root in components:
        w = measure(root)
        h = depth(root) * box_h + (depth(root) - 1) * vgap
        if cur_x > 0 and cur_x + w > max_width:
            cur_y += row_h + comp_gap
            cur_x, row_h = 0.0, 0.0
        place(root, cur_x, cur_y, w)
        cur_x += w + comp_gap
        row_h = max(row_h, h)
        total_w = max(total_w, cur_x - comp_gap)
    total_h = cur_y + row_h

    out = [
        f'<svg class="chart" viewBox="-4 -4 {total_w + 8:.0f} {total_h + 8:.0f}" '
        f'width="{total_w + 8:.0f}" height="{total_h + 8:.0f}" role="img" aria-label="nesting graph">'
    ]
    for x1, y1, x2, y2 in edges:
        my = (y1 + y2) / 2.0
        out.append(
            f'<path class="edge" d="M{x1:.1f},{y1:.1f} V{my:.1f} H{x2:.1f} V{y2:.1f}"/>'
        )
    for x, y, node in placed:
        out.append(f'<g class="node"><title>{E(label_of(node))} — {E(sub_of(node))}</title>')
        out.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{box_w}" height="{box_h}" rx="5" '
            f'class="nodebox" style="stroke:{fill}"/>'
        )
        out.append(
            f'<text class="nodelab" x="{x + box_w / 2:.1f}" y="{y + 12:.1f}">{E(label_of(node))}</text>'
        )
        out.append(
            f'<text class="nodesub" x="{x + box_w / 2:.1f}" y="{y + 22:.1f}">{E(sub_of(node))}</text>'
        )
        out.append("</g>")
    out.append("</svg>")
    return f'<div class="scroll chart-wrap">{"".join(out)}</div>'


def ladders_svg(ladders, per_row=5, box_w=158, box_h=34, vgap=16, hgap=22, rowgap=26):
    """ladders: list of [(top_label, top_sub), (mid...), (bottom...)] chains."""
    depth = max(len(l) for l in ladders)
    cols = min(per_row, len(ladders))
    rows = (len(ladders) + per_row - 1) // per_row
    lad_h = depth * box_h + (depth - 1) * vgap
    total_w = cols * box_w + (cols - 1) * hgap
    total_h = rows * lad_h + (rows - 1) * rowgap
    out = [
        f'<svg class="chart" viewBox="-4 -6 {total_w + 8} {total_h + 12}" width="{total_w + 8}" '
        f'height="{total_h + 12}" role="img" aria-label="role hierarchy ladders">'
    ]
    for i, lad in enumerate(ladders):
        c, r = i % per_row, i // per_row
        x = c * (box_w + hgap)
        y0 = r * (lad_h + rowgap)
        for j, (lab, sub) in enumerate(lad):
            y = y0 + j * (box_h + vgap)
            if j:
                out.append(
                    f'<path class="edge arrow" d="M{x + box_w / 2},{y - vgap} V{y - 4}"/>'
                    f'<path class="arrowhead" d="M{x + box_w / 2 - 3.5},{y - 5} '
                    f"L{x + box_w / 2 + 3.5},{y - 5} L{x + box_w / 2},{y} Z\"/>"
                )
            tone = ("var(--rank-1)", "var(--rank-2)", "var(--rank-3)")[min(j, 2)]
            out.append(f'<g class="node"><title>{E(lab)} — {E(sub)}</title>')
            out.append(
                f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" rx="5" '
                f'class="nodebox" style="stroke:{tone}"/>'
            )
            out.append(f'<rect x="{x}" y="{y}" width="4" height="{box_h}" rx="2" fill="{tone}"/>')
            out.append(f'<text class="nodelab left" x="{x + 12}" y="{y + 14}">{E(lab)}</text>')
            out.append(f'<text class="nodesub left" x="{x + 12}" y="{y + 25}">{E(sub)}</text>')
            out.append("</g>")
    out.append("</svg>")
    return f'<div class="scroll chart-wrap">{"".join(out)}</div>'


# ==========================================================================
# LOAD
# ==========================================================================

uni = load(PUBLIC / "identity-access" / "identity-access-universe.json")
rbac = load(PUBLIC / "directory-rbac" / "directory-rbac-kernel.json")
corpus = load(PUBLIC / "evaluation-corpus" / "evaluation-corpus.json")
abac = load(PUBLIC / "authorization" / "abac-state.json")
rebac = load(PUBLIC / "authorization" / "rebac-state.json")
authk = load(PUBLIC / "authorization" / "authorization-kernel.json")
index = load(PUBLIC / "PUBLIC-INDEX.json")
manifests = {
    name: load(PUBLIC / name / "manifest.json")
    for name in ("identity-access", "directory-rbac", "evaluation-corpus", "authorization")
}
ledger = load(SOURCE / "generated" / "mapping-ledger.json")
exp_yaml = read_text(SOURCE / "config" / "experiment.yaml")

# ==========================================================================
# DERIVE
# ==========================================================================

tenants = uni["tenants"]
orgs = uni["organisations"]
units = uni["units"]
principals = uni["principals"]
accounts = uni["accounts"]
subjects = uni["access_subjects"]
groups = uni["groups"]
roles = uni["roles"]
targets = uni["authorization_targets"]
perms = uni["permissions"]
atoms = uni["access_atoms"]
anchors = uni["relationship_anchors"]
cells = corpus["evaluation_cells"]

tenant_of = {t["tenant_id"]: t for t in tenants}
unit_of = {u["unit_id"]: u for u in units}
group_of = {g["group_id"]: g for g in groups}
role_of = {r["role_id"]: r for r in roles}
target_of = {t["authorization_target_id"]: t for t in targets}
atom_of = {a["access_atom_id"]: a for a in atoms}
subject_of = {s["subject_id"]: s for s in subjects}

tenant_order = sorted(tenants, key=lambda t: t["display_label"])
tlabel = {t["tenant_id"]: short(t["display_label"]) for t in tenants}

atoms_per_target = Counter(a["authorization_target_id"] for a in atoms)
atoms_per_subject = Counter(a["subject_id"] for a in atoms)
grants_per_role = Counter(e["role_id"] for e in rbac["role_grants"])
members_per_group = Counter(e["group_id"] for e in rbac["memberships"])
roles_per_subject = Counter(e["subject_id"] for e in rbac["subject_role_assignments"])
principals_per_unit = Counter(p["unit_id"] for p in principals)

# cell-side derivations (public join: cell -> access atom -> subject / target)
cell_subject_kind = Counter()
cell_action = Counter()
cell_target_kind = Counter()
for c in cells:
    a = atom_of.get(c["access_atom_id"])
    if not a:
        continue
    cell_action[a["action"]] += 1
    s = subject_of.get(a["subject_id"])
    if s:
        cell_subject_kind[s["subject_kind"]] += 1
    t = target_of.get(a["authorization_target_id"])
    if t:
        cell_target_kind[t["target_kind"]] += 1

facts = abac["attribute_facts"]
fact_kind = Counter(f["kind"] for f in facts)
fact_state = Counter(f["value_state"] for f in facts)
action_class = Counter(f["value"] for f in facts if f["kind"] == "action_class")
net_zone = Counter(f["value"] for f in facts if f["kind"] == "environment_network_zone")
res_kind_fact = Counter(f["value"] for f in facts if f["kind"] == "resource_target_kind")

obs_state = Counter(o["administrative_state"] for o in rbac["account_observations"])
obs_window = Counter(
    "open-ended" if o["valid_until_tick"] is None else f"closes at tick {o['valid_until_tick']}"
    for o in rbac["account_observations"]
)

profiles = Counter(c["profile"] for c in authk["cells"])
rel_relations = Counter(t["relation"] for t in rebac["relation_tuples"])

# role hierarchy chains: senior -> junior
junior_of = {e["senior_role_id"]: e["junior_role_id"] for e in rbac["role_hierarchy"]}
seniors = set(junior_of)
juniors = set(junior_of.values())
chain_tops = sorted(seniors - juniors)
chains = []
for top in chain_tops:
    chain, cur = [], top
    while cur is not None:
        chain.append(cur)
        cur = junior_of.get(cur)
    chains.append(chain)
chains.sort(key=lambda ch: role_of[ch[0]]["display_label"])
roles_in_hierarchy = seniors | juniors

# group nesting forest: child -> parent
parent_of = {e["child_group_id"]: e["parent_group_id"] for e in rbac["group_nesting"]}
kids_of = defaultdict(list)
for child, parent in parent_of.items():
    kids_of[parent].append(child)
for k in kids_of:
    kids_of[k].sort(key=lambda g: group_of[g]["display_label"])
nest_nodes = set(parent_of) | set(parent_of.values())
nest_roots = sorted(
    [g for g in nest_nodes if g not in parent_of],
    key=lambda g: group_of[g]["display_label"],
)


def nest_root(node):
    seen = set()
    while node in parent_of and node not in seen:
        seen.add(node)
        node = parent_of[node]
    return node


nest_tree_size = Counter(nest_root(n) for n in nest_nodes)

# per-tenant rollup
tenant_rows = []
for t in tenant_order:
    tid = t["tenant_id"]
    tunits = [u for u in units if u["tenant_id"] == tid]
    ttargets = [x for x in targets if x["tenant_id"] == tid]
    tenant_rows.append(
        dict(
            label=tlabel[tid],
            tid=tid,
            orgs=sum(1 for o in orgs if o["tenant_id"] == tid),
            units=len(tunits),
            divisions=sum(1 for u in tunits if u["unit_kind"] == "division"),
            teams=sum(1 for u in tunits if u["unit_kind"] == "team"),
            depts=sum(1 for u in tunits if u["unit_kind"] == "department"),
            principals=sum(1 for p in principals if p["tenant_id"] == tid),
            accounts=sum(1 for a in accounts if a["tenant_id"] == tid),
            subjects=sum(1 for s in subjects if s["tenant_id"] == tid),
            groups=sum(1 for g in groups if g["tenant_id"] == tid),
            roles=sum(1 for r in roles if r["tenant_id"] == tid),
            targets=len(ttargets),
            atoms=sum(
                atoms_per_target.get(x["authorization_target_id"], 0) for x in ttargets
            ),
        )
    )

ledger_class = Counter(e["classification"] for e in ledger["ledger"])

# ==========================================================================
# RENDER
# ==========================================================================

BANNER = "External experiment visualization - not a SynthWorld renderer"

CSS = """
:root{
  color-scheme: light;
  --bg:#f9f9f7; --surface:#fcfcfb; --surface-2:#f2f1ec;
  --text-1:#0b0b0b; --text-2:#52514e; --muted:#6c6a65;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,0.12);
  --series-1:#2a78d6; --series-2:#eb6834;
  --rank-1:#184f95; --rank-2:#2a78d6; --rank-3:#86b6ef;
  --accent:#1c5cab; --banner-bg:#104281; --banner-fg:#ffffff;
  --banner-accent:#9ec5f4; --code-bg:#f2f1ec; --shadow:rgba(11,11,11,0.06);
  --chip-bg:#eef2f8; --chip-fg:#184f95;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --bg:#0d0d0d; --surface:#1a1a19; --surface-2:#232322;
    --text-1:#ffffff; --text-2:#c3c2b7; --muted:#98968f;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.13);
    --series-1:#3987e5; --series-2:#d95926;
    --rank-1:#b7d3f6; --rank-2:#5598e7; --rank-3:#184f95;
    --accent:#86b6ef; --banner-bg:#16345e; --banner-fg:#ffffff;
    --banner-accent:#9ec5f4; --code-bg:#232322; --shadow:rgba(0,0,0,0.4);
    --chip-bg:#1f2b3d; --chip-fg:#b7d3f6;
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --bg:#0d0d0d; --surface:#1a1a19; --surface-2:#232322;
  --text-1:#ffffff; --text-2:#c3c2b7; --muted:#98968f;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.13);
  --series-1:#3987e5; --series-2:#d95926;
  --rank-1:#b7d3f6; --rank-2:#5598e7; --rank-3:#184f95;
  --accent:#86b6ef; --banner-bg:#16345e; --banner-fg:#ffffff;
  --banner-accent:#9ec5f4; --code-bg:#232322; --shadow:rgba(0,0,0,0.4);
  --chip-bg:#1f2b3d; --chip-fg:#b7d3f6;
}

*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--bg); color:var(--text-1);
  font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  font-size:15px; line-height:1.55; overflow-x:hidden;
}
.wrap{max-width:1120px; margin:0 auto; padding:0 20px 80px}

/* banner */
.banner{background:var(--banner-bg); color:var(--banner-fg); padding:18px 0 20px;
  border-bottom:3px solid var(--banner-accent)}
.banner .wrap{padding-bottom:0}
.banner h1{margin:0 0 8px; font-size:1.32rem; line-height:1.3; letter-spacing:-0.01em}
.banner p{margin:0; max-width:78ch; font-size:0.9rem; color:var(--banner-fg); opacity:0.93}
.banner code{background:rgba(255,255,255,0.14); padding:1px 5px; border-radius:4px;
  font-size:0.86em; color:var(--banner-fg)}

header.doc{padding:30px 0 6px}
header.doc h2{margin:0 0 4px; font-size:1.9rem; letter-spacing:-0.02em}
header.doc .sub{color:var(--text-2); margin:0; font-size:0.98rem}

.toolbar{display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:14px}
button.theme{font:inherit; font-size:0.82rem; padding:5px 12px; border-radius:999px;
  border:1px solid var(--border); background:var(--surface); color:var(--text-2); cursor:pointer}
button.theme:hover{background:var(--surface-2); color:var(--text-1)}

nav.toc{margin:20px 0 4px; padding:14px 16px; background:var(--surface);
  border:1px solid var(--border); border-radius:10px}
nav.toc ol{margin:0; padding:0; list-style:none; display:flex; flex-wrap:wrap; gap:6px 18px;
  font-size:0.86rem; counter-reset:s}
nav.toc a{color:var(--accent); text-decoration:none}
nav.toc a:hover{text-decoration:underline}

section{margin-top:34px; scroll-margin-top:12px}
section > h3{font-size:1.16rem; margin:0 0 4px; letter-spacing:-0.01em;
  padding-bottom:6px; border-bottom:1px solid var(--border)}
section > p.lede{color:var(--text-2); margin:8px 0 16px; max-width:82ch; font-size:0.93rem}
h4{font-size:0.9rem; margin:20px 0 8px; color:var(--text-2); font-weight:600;
  text-transform:uppercase; letter-spacing:0.05em}

.card{background:var(--surface); border:1px solid var(--border); border-radius:10px;
  padding:16px 18px; box-shadow:0 1px 2px var(--shadow)}
.grid{display:grid; gap:14px}
.g2{grid-template-columns:repeat(auto-fit,minmax(468px,1fr))}
.g3{grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.tiles{display:grid; gap:10px; grid-template-columns:repeat(auto-fit,minmax(136px,1fr))}
.tile{background:var(--surface); border:1px solid var(--border); border-radius:9px; padding:11px 13px}
.tile .n{font-size:1.5rem; font-weight:650; letter-spacing:-0.02em; display:block; line-height:1.1}
.tile .k{font-size:0.74rem; color:var(--muted); text-transform:uppercase; letter-spacing:0.06em}
.tile .x{font-size:0.76rem; color:var(--text-2)}

.scroll{overflow-x:auto; overflow-y:visible; max-width:100%;
  -webkit-overflow-scrolling:touch; padding-bottom:2px}
.chart-wrap svg{display:block}
.chart-note{font-size:0.8rem; color:var(--muted); margin:6px 0 0}
figure{margin:0}
figcaption{font-size:0.86rem; color:var(--text-2); margin:0 0 10px; font-weight:600}

svg.chart text{font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
svg.chart .cat{font-size:11.5px; fill:var(--text-2); text-anchor:end}
svg.chart .val{font-size:11.5px; fill:var(--text-1); font-variant-numeric:tabular-nums;
  dominant-baseline:auto}
svg.chart .axis{stroke:var(--axis); stroke-width:1}
svg.chart .edge{stroke:var(--axis); stroke-width:1.5; fill:none}
svg.chart .arrowhead{fill:var(--axis)}
svg.chart .nodebox{fill:var(--surface); stroke-width:1.5}
svg.chart .nodelab{font-size:11px; fill:var(--text-1); text-anchor:middle}
svg.chart .nodesub{font-size:9.5px; fill:var(--muted); text-anchor:middle}
svg.chart .nodelab.left, svg.chart .nodesub.left{text-anchor:start}
svg.chart g.node:hover .nodebox{fill:var(--surface-2)}

table{border-collapse:collapse; width:100%; font-size:0.85rem}
table th{text-align:left; font-weight:600; color:var(--text-2); font-size:0.76rem;
  text-transform:uppercase; letter-spacing:0.05em; padding:7px 10px;
  border-bottom:1px solid var(--axis); background:var(--surface); position:sticky; top:0}
table td{padding:6px 10px; border-bottom:1px solid var(--grid); vertical-align:top}
table tr:last-child td{border-bottom:none}
td.n, th.n{text-align:right; font-variant-numeric:tabular-nums}
tbody tr:hover td{background:var(--surface-2)}
.tall{max-height:520px; overflow-y:auto}
code, .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:0.85em}
td code{background:var(--code-bg); padding:1px 4px; border-radius:3px; color:var(--text-2)}
.chip{display:inline-block; background:var(--chip-bg); color:var(--chip-fg);
  border-radius:4px; padding:1px 6px; font-size:0.74rem; margin-right:3px;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
ul.tree{list-style:none; margin:4px 0 0; padding:0; font-size:0.85rem}
ul.tree ul{list-style:none; margin:2px 0 6px; padding-left:14px;
  border-left:1px solid var(--grid)}
ul.tree li{padding:1px 0}
ul.tree .u{color:var(--text-1)}
ul.tree .m{color:var(--muted); font-size:0.92em}
.note{border-left:3px solid var(--series-2); background:var(--surface);
  border-radius:0 8px 8px 0; padding:12px 16px; margin:14px 0;
  font-size:0.9rem; color:var(--text-2)}
.note strong{color:var(--text-1)}
dl.kv{display:grid; grid-template-columns:minmax(0,1fr) auto; gap:4px 14px; margin:0;
  font-size:0.85rem}
dl.kv dt{color:var(--muted); min-width:0; overflow-wrap:anywhere}
dl.kv dd{margin:0; color:var(--text-1); text-align:right; white-space:nowrap}
footer{margin-top:44px; padding-top:16px; border-top:1px solid var(--border);
  color:var(--muted); font-size:0.8rem}
"""

JS = """
(function(){
  var b=document.getElementById('themebtn'); if(!b) return;
  b.addEventListener('click',function(){
    var r=document.documentElement, cur=r.getAttribute('data-theme');
    var dark = cur ? cur==='dark'
      : window.matchMedia('(prefers-color-scheme: dark)').matches;
    r.setAttribute('data-theme', dark ? 'light' : 'dark');
  });
})();
"""

SECTIONS = [
    ("provenance", "Package provenance"),
    ("counts", "Headline counts"),
    ("tenancy", "Tenancy and unit hierarchy"),
    ("population", "Population and resource distributions"),
    ("roles", "Role graph"),
    ("groups", "Group nesting graph"),
    ("targets", "Authorization targets"),
    ("directory", "Directory state"),
    ("corpus", "Evaluation corpus shape"),
    ("policy", "Public policy surface"),
    ("opaque", "Opaque identifiers"),
    ("topology", "Topology-side mapping context"),
    ("fields", "Public fields used"),
]

P: list[str] = []
add = P.append

add("<!doctype html>")
add('<html lang="en"><head>')
add('<meta charset="utf-8">')
add('<meta name="viewport" content="width=device-width, initial-scale=1">')
add('<meta name="color-scheme" content="light dark">')
add(
    '<meta name="description" content="Public-only reference view of the compiled Britannia '
    'world. External experiment visualization, not a SynthWorld renderer.">'
)
add("<title>Britannia World View</title>")
add(f"<style>{CSS}</style>")
add("</head><body>")

# ---- banner -------------------------------------------------------------
add('<div class="banner"><div class="wrap">')
add(f"<h1>{E(BANNER)}</h1>")
add(
    "<p>SynthWorld 0.15.0 ships no generic enterprise-world renderer: the only projector its "
    "released Explorer surface exports is <code>project_asteria_agent_authority_v1</code>, which "
    "takes an <code>AgenticPublicBundle</code> and is specific to the Asteria agentic world, not to "
    "an enterprise identity/access universe. This page is therefore experiment-owned - it was "
    "written for this experiment and reads only the published public artifacts. It is not a "
    "SynthWorld product, and nothing on it should be read as SynthWorld output.</p>"
)
add("</div></div>")

add('<div class="wrap">')

# ---- header -------------------------------------------------------------
add("<header class=\"doc\">")
add("<h2>Britannia compiled world - public reference view</h2>")
add(
    '<p class="sub">Everything below is derived from the 13 public artifacts under '
    "<code>02-synthworld-public/</code>, plus two experiment-owned files "
    "(<code>01-source/config/experiment.yaml</code>, "
    "<code>01-source/generated/mapping-ledger.json</code>). No evaluator material is read by the "
    "generator or shown here: no expected outcomes, no case labels, no scoring, no truth of any "
    "kind. This is the shape of the world and of the question set - not their resolution.</p>"
)
add('<div class="toolbar"><button class="theme" id="themebtn" type="button">Toggle light / dark</button>')
add(
    '<span class="chip">seed '
    + E(str(uni.get("seed")))
    + '</span><span class="chip">compiler '
    + E(str(uni.get("compiler_version")))
    + '</span><span class="chip">schema '
    + E(str(uni.get("schema_version")))
    + "</span></div>"
)
add("</header>")

add('<nav class="toc"><ol>')
for sid, title in SECTIONS:
    add(f'<li><a href="#{sid}">{E(title)}</a></li>')
add("</ol></nav>")

# ---- provenance ---------------------------------------------------------
add('<section id="provenance"><h3>Package provenance</h3>')
add(
    '<p class="lede">The public package is self-describing: each family ships a manifest carrying '
    "the byte size and digest of every artifact, and <code>PUBLIC-INDEX.json</code> repeats the "
    "digests for the tree as a whole. The table is that index, joined to the manifests.</p>"
)
add('<div class="scroll"><table><thead><tr>'
    "<th>Artifact</th><th class=\"n\">Bytes</th><th>Schema</th><th>Digest (sha256, first 16)</th>"
    "</tr></thead><tbody>")
sizes = {}
for fam, man in manifests.items():
    for a in man["artifacts"]:
        sizes[f"{fam}/{a['path']}"] = (a["byte_size"], a["schema_version"])
for path, digest in sorted(index["sha256"].items()):
    bs, sv = sizes.get(path, ("", ""))
    add(
        f"<tr><td><code>{E(path)}</code></td>"
        f'<td class="n">{num(bs) if bs else "-"}</td>'
        f"<td>{E(sv) if sv else '-'}</td>"
        f'<td><code>{E(digest[:16])}</code></td></tr>'
    )
add("</tbody></table></div>")
add('<div class="grid g2" style="margin-top:14px">')
add(
    '<div class="card"><h4 style="margin-top:0">Compilation identity</h4><dl class="kv">'
    f'<dt>seed</dt><dd>{E(str(uni.get("seed")))}</dd>'
    f'<dt>compiler_version</dt><dd>{E(str(uni.get("compiler_version")))}</dd>'
    f'<dt>selector_algorithm_version</dt><dd>{E(str(uni.get("selector_algorithm_version")))}</dd>'
    f'<dt>schema_version</dt><dd>{E(str(uni.get("schema_version")))}</dd>'
    f'<dt>synthetic</dt><dd>{E(str(uni.get("synthetic")))}</dd>'
    "</dl></div>"
)
add(
    '<div class="card"><h4 style="margin-top:0">Cross-artifact binding</h4>'
    '<p style="margin:0 0 8px;font-size:0.85rem;color:var(--text-2)">Every downstream family '
    "restates the digest of the universe it was compiled against, so the tree can be checked for "
    "internal consistency without any private input.</p><dl class=\"kv\">"
    f'<dt>universe</dt><dd><code>{E(index["sha256"]["identity-access/identity-access-universe.json"][:16])}</code></dd>'
    f'<dt>corpus</dt><dd><code>{E(index["sha256"]["evaluation-corpus/evaluation-corpus.json"][:16])}</code></dd>'
    f'<dt>directory RBAC restates universe</dt><dd><code>{E(rbac["identity_access_universe_digest"]["value"][:16])}</code></dd>'
    f'<dt>ABAC restates corpus</dt><dd><code>{E(abac["evaluation_corpus_digest"]["value"][:16])}</code></dd>'
    f'<dt>ReBAC restates corpus</dt><dd><code>{E(rebac["evaluation_corpus_digest"]["value"][:16])}</code></dd>'
    "</dl></div>"
)
add("</div></section>")

# ---- headline counts ----------------------------------------------------
add('<section id="counts"><h3>Headline counts</h3>')
add(
    '<p class="lede">The compiled world at a glance. Access subjects are the union of principals '
    "and accounts; access atoms are the (subject, target, action) triples the universe declares as "
    "reachable requests; evaluation cells are the unit of scoring in the corpus.</p>"
)
tiles = [
    ("Tenants", len(tenants), "legal entities"),
    ("Organisations", len(orgs), "one per tenant"),
    ("Units", len(units), f"{sum(1 for u in units if u['unit_kind']=='division')} div / "
        f"{sum(1 for u in units if u['unit_kind']=='team')} team / "
        f"{sum(1 for u in units if u['unit_kind']=='department')} dept"),
    ("Principals", len(principals), "people, suppliers, workloads"),
    ("Accounts", len(accounts), "credentials that act"),
    ("Access subjects", len(subjects), "principals + accounts"),
    ("Groups", len(groups), f"{len(rbac['group_nesting'])} nesting edges"),
    ("Roles", len(roles), f"{len(roles_in_hierarchy)} in a hierarchy"),
    ("Targets", len(targets), "authorization targets"),
    ("Permissions", len(perms), "target x action"),
    ("Access atoms", len(atoms), "declared triples"),
    ("Evaluation cells", len(cells), "the scoring unit"),
]
add('<div class="tiles">')
for k, n, x in tiles:
    add(f'<div class="tile"><span class="n">{num(n)}</span>'
        f'<span class="k">{E(k)}</span><div class="x">{E(x)}</div></div>')
add("</div>")

add("<h4>Per-tenant rollup</h4>")
add('<div class="scroll"><table><thead><tr><th>Tenant</th>'
    '<th class="n">Orgs</th><th class="n">Units</th><th class="n">Principals</th>'
    '<th class="n">Accounts</th><th class="n">Subjects</th><th class="n">Groups</th>'
    '<th class="n">Roles</th><th class="n">Targets</th><th class="n">Atoms</th>'
    "</tr></thead><tbody>")
for r in tenant_rows:
    add(
        f"<tr><td>{E(r['label'])}<br><code>{E(idfrag(r['tid']))}</code></td>"
        f'<td class="n">{r["orgs"]}</td><td class="n">{r["units"]}</td>'
        f'<td class="n">{r["principals"]}</td><td class="n">{r["accounts"]}</td>'
        f'<td class="n">{r["subjects"]}</td><td class="n">{r["groups"]}</td>'
        f'<td class="n">{r["roles"]}</td><td class="n">{r["targets"]}</td>'
        f'<td class="n">{num(r["atoms"])}</td></tr>'
    )
add(
    f'<tr><td><strong>Total</strong></td><td class="n"><strong>{len(orgs)}</strong></td>'
    f'<td class="n"><strong>{len(units)}</strong></td>'
    f'<td class="n"><strong>{len(principals)}</strong></td>'
    f'<td class="n"><strong>{len(accounts)}</strong></td>'
    f'<td class="n"><strong>{len(subjects)}</strong></td>'
    f'<td class="n"><strong>{len(groups)}</strong></td>'
    f'<td class="n"><strong>{len(roles)}</strong></td>'
    f'<td class="n"><strong>{len(targets)}</strong></td>'
    f'<td class="n"><strong>{num(len(atoms))}</strong></td></tr>'
)
add("</tbody></table></div>")
add(
    '<div class="note">Only two of the five tenants own authorization targets. Resource sets are '
    "compiled from services, and every service in the source topology sits in one of two legal "
    "entities; the other three tenants hold subjects that reach across the boundary, which is what "
    "makes the cross-tenant portion of the corpus non-trivial.</div>"
)
add("</section>")

# ---- tenancy / units ----------------------------------------------------
add('<section id="tenancy"><h3>Tenancy and unit hierarchy</h3>')
add(
    '<p class="lede">Units nest two levels deep: divisions own teams. The source topology declares '
    "a parent-domain field but leaves it null on every record, so no third level can be derived - "
    "that limitation is recorded in the mapping ledger rather than papered over. The vendor tenant "
    "uses flat departments, one per supplier.</p>"
)
add('<div class="grid g2">')
for r in tenant_rows:
    tid = r["tid"]
    tunits = [u for u in units if u["tenant_id"] == tid]
    parents = [u for u in tunits if not u.get("parent_unit_id")]
    parents.sort(key=lambda u: (u["unit_kind"], u["display_label"]))
    add('<div class="card">')
    add(
        f'<figcaption>{E(r["label"])} '
        f'<span style="color:var(--muted);font-weight:400">- {r["units"]} units, '
        f'{num(r["principals"])} principals</span></figcaption>'
    )
    add('<ul class="tree">')
    for u in parents:
        kids = [
            k for k in tunits if k.get("parent_unit_id") == u["unit_id"]
        ]
        kids.sort(key=lambda k: k["display_label"])
        pc = principals_per_unit.get(u["unit_id"], 0)
        add(
            f'<li><span class="u">{E(short(u["display_label"]))}</span> '
            f'<span class="m">{E(u["unit_kind"])}'
            + (f" &middot; {pc} principal{'s' if pc != 1 else ''}" if pc else "")
            + "</span>"
        )
        if kids:
            add("<ul>")
            for k in kids:
                kc = principals_per_unit.get(k["unit_id"], 0)
                add(
                    f'<li><span class="u">{E(short(k["display_label"]))}</span> '
                    f'<span class="m">{E(k["unit_kind"])}'
                    + (f" &middot; {kc} principal{'s' if kc != 1 else ''}" if kc else "")
                    + "</span></li>"
                )
            add("</ul>")
        add("</li>")
    add("</ul></div>")
add("</div></section>")

# ---- distributions ------------------------------------------------------
add('<section id="population"><h3>Population and resource distributions</h3>')
add(
    '<p class="lede">Counts per kind across the universe. Bars are direct-labelled, so the figures '
    "read without reference to the axis.</p>"
)


def chart_card(caption, svg_html):
    return f'<div class="card"><figure><figcaption>{E(caption)}</figcaption>{svg_html}</figure></div>'


pk = Counter(p["principal_kind"] for p in principals)
ak = Counter(a["account_kind"] for a in accounts)
tk = Counter(t["target_kind"] for t in targets)
uk = Counter(u["unit_kind"] for u in units)
sk = Counter(s["subject_kind"] for s in subjects)
aa = Counter(a["action"] for a in atoms)
apt = Counter(len(t["actions"]) for t in targets)

add('<div class="grid g2">')
add(chart_card(
    "Principals by kind",
    hbar([(k, v) for k, v in pk.most_common()], width=490, label_w=136),
))
add(chart_card(
    "Accounts by kind",
    hbar([(k, v) for k, v in ak.most_common()], width=490, label_w=136),
))
add(chart_card(
    "Access subjects by kind",
    hbar(
        [("account", sk["account"]), ("principal", sk["principal"])],
        width=490, label_w=136,
    ),
))
add(chart_card(
    "Units by kind",
    hbar([(k, v) for k, v in uk.most_common()], width=490, label_w=136),
))
add(chart_card(
    "Authorization targets by kind",
    hbar([(k, v) for k, v in tk.most_common()], width=490, label_w=136),
))
add(chart_card(
    "Actions declared per target",
    hbar(
        [(f"{k} actions", v) for k, v in sorted(apt.items())],
        width=490, label_w=136,
        note="Uniform: every target offers the same four-rung action ladder "
             "(read, write, invoke, deploy). Differentiation comes from role grants and the "
             "policy guard, not from the resource surface.",
    ),
))
add(chart_card(
    "Access atoms by action",
    hbar([(k, v) for k, v in aa.most_common()], width=490, label_w=136),
))
add(chart_card(
    "Access atoms per target",
    hbar(
        buckets(list(atoms_per_target.values()), [4, 8, 16, 32, 48, 64]),
        width=490, label_w=136,
        note=f"{len(atoms_per_target)} of {len(targets)} targets carry at least one atom; "
             f"busiest target carries {max(atoms_per_target.values())}.",
    ),
))
add(chart_card(
    "Access atoms per subject",
    hbar(
        buckets(list(atoms_per_subject.values()), [1, 2, 4, 8, 16, 32]),
        width=490, label_w=136,
        note=f"{len(atoms_per_subject)} of {len(subjects)} subjects appear in at least one atom.",
    ),
))
add(chart_card(
    "Relationship anchors by entity kind",
    hbar(
        [(k, v) for k, v in Counter(a["entity_kind"] for a in anchors).most_common()],
        width=490, label_w=136,
    ),
))
add("</div></section>")

# ---- role graph ---------------------------------------------------------
add('<section id="roles"><h3>Role graph</h3>')
n_chain_roles = len(roles_in_hierarchy)
ladder_units = [
    {role_of[r].get("owner_unit_id") for r in ch} for ch in chains
]
single_unit_ladders = sum(1 for s in ladder_units if len(s) == 1)
ladder_unit_kinds = Counter(
    unit_of.get(next(iter(s)), {}).get("unit_kind") for s in ladder_units if len(s) == 1
)
standalone_kinds = Counter(
    unit_of.get(r.get("owner_unit_id"), {}).get("unit_kind")
    for r in roles
    if r["role_id"] not in roles_in_hierarchy
)
depths = sorted(set(len(ch) for ch in chains))
add(
    f'<p class="lede">{len(rbac["role_hierarchy"])} seniority edges connect '
    f"{n_chain_roles} of the {len(roles)} roles into {len(chains)} independent "
    f"{'-to-'.join(str(d) for d in depths)}-rung ladders. All {single_unit_ladders} ladders sit "
    "entirely inside one owning unit ("
    + ", ".join(f"{v} on a {k}" for k, v in ladder_unit_kinds.most_common())
    + "), so seniority never crosses a unit boundary. Each rung's subtitle is the number of "
    "permissions the role grants directly, before any inheritance is applied. The remaining "
    f"{len(roles) - n_chain_roles} roles stand alone ("
    + ", ".join(f"{v} owned by a {k}" for k, v in standalone_kinds.most_common())
    + ").</p>"
)
lads = []
for ch in chains:
    lads.append(
        [
            (
                short(role_of[r]["display_label"]),
                (lambda g: f"{g} permission{'s' if g != 1 else ''}")(grants_per_role.get(r, 0)),
            )
            for r in ch
        ]
    )
add('<div class="card">')
add(f'<figcaption>Seniority ladders (senior at top) - {len(chains)} ladders</figcaption>')
add(ladders_svg(lads, per_row=5))
add(
    '<p class="chart-note">Edges are directed senior &rarr; junior. Every ladder is exactly '
    f"{'-to-'.join(str(d) for d in depths)} rungs deep and no role appears in two ladders, so the "
    "hierarchy is a disjoint forest of chains rather than a lattice.</p>"
)
add("</div>")

add('<div class="grid g2" style="margin-top:14px">')
add(chart_card(
    "Permissions granted per role",
    hbar(
        buckets(list(grants_per_role.values()), [2, 4, 8, 16, 32, 64]),
        width=490, label_w=136,
        note=f"{len(grants_per_role)} of {len(roles)} roles carry at least one direct grant; "
             f"{num(len(rbac['role_grants']))} grant edges in total.",
    ),
))
add(chart_card(
    "Role assignment edges",
    hbar(
        [
            ("subject → role", len(rbac["subject_role_assignments"])),
            ("group → role", len(rbac["group_role_assignments"])),
            ("role → permission", len(rbac["role_grants"])),
        ],
        width=490, label_w=146,
        note=f"{len(roles_per_subject)} distinct subjects hold at least one role directly.",
    ),
))
add("</div>")

top_roles = sorted(grants_per_role.items(), key=lambda kv: -kv[1])[:14]
add("<h4>Roles by grant breadth</h4>")
add('<div class="scroll"><table><thead><tr><th>Role</th><th>Tenant</th><th>Owner unit</th>'
    '<th class="n">Permissions granted</th><th class="n">Subjects assigned</th>'
    "<th>Ladder position</th></tr></thead><tbody>")
pos_of = {}
for ch in chains:
    for i, r in enumerate(ch):
        pos_of[r] = ("senior", "middle", "junior")[min(i, 2)]
subs_per_role = Counter(e["role_id"] for e in rbac["subject_role_assignments"])
for rid, g in top_roles:
    r = role_of[rid]
    add(
        f"<tr><td>{E(short(r['display_label']))}</td>"
        f"<td>{E(tlabel.get(r['tenant_id'], '-'))}</td>"
        f"<td>{E(short(unit_of.get(r.get('owner_unit_id'), {}).get('display_label', '-')))}</td>"
        f'<td class="n">{g}</td><td class="n">{subs_per_role.get(rid, 0)}</td>'
        f"<td>{E(pos_of.get(rid, 'standalone'))}</td></tr>"
    )
add("</tbody></table></div></section>")

# ---- group nesting ------------------------------------------------------
add('<section id="groups"><h3>Group nesting graph</h3>')
add(
    f'<p class="lede">{len(rbac["group_nesting"])} nesting edges over {len(groups)} groups form '
    f"{len(nest_roots)} disjoint trees covering {len(nest_nodes)} groups; the other "
    f"{len(groups) - len(nest_nodes)} are flat. Each box shows the group and its direct member "
    "count. Membership is not transitively expanded in the published state - the nesting edge is "
    "the mechanism by which a parent group's members reach a child group's roles.</p>"
)
add('<div class="card">')
add(f'<figcaption>Nesting forest - {len(nest_roots)} trees</figcaption>')
add(
    forest_svg(
        nest_roots,
        kids_of,
        lambda g: short(group_of[g]["display_label"]),
        lambda g: (lambda m: f"{m} member{'s' if m != 1 else ''}")(members_per_group.get(g, 0)),
        max_width=940,
    )
)
add("</div>")
add('<div class="grid g2" style="margin-top:14px">')
add(chart_card(
    "Direct members per group",
    hbar(
        buckets(list(members_per_group.values()), [1, 2, 4, 6, 8]),
        width=490, label_w=136,
        note=f"{len(members_per_group)} of {len(groups)} groups have at least one direct member; "
             f"{num(len(rbac['memberships']))} membership edges in total.",
    ),
))
add(chart_card(
    "Nesting tree sizes",
    hbar(
        [
            (f"{size} groups", cnt)
            for size, cnt in sorted(Counter(nest_tree_size.values()).items())
        ],
        width=490, label_w=136,
        note="Tree size counted as root plus all descendants.",
    ),
))
add("</div></section>")

# ---- targets table ------------------------------------------------------
add('<section id="targets"><h3>Authorization targets</h3>')
add(
    f'<p class="lede">All {len(targets)} targets, with the tenant and unit that own them, the '
    "action ladder they declare, and how many access atoms in the universe point at them. "
    "The table scrolls inside its own frame.</p>"
)
add('<div class="scroll tall"><table><thead><tr>'
    "<th>Target</th><th>Id</th><th>Kind</th><th>Tenant</th><th>Owner unit</th>"
    '<th>Actions</th><th class="n">Permissions</th><th class="n">Access atoms</th>'
    "</tr></thead><tbody>")
perms_per_target = Counter(p["authorization_target_id"] for p in perms)
for t in sorted(targets, key=lambda t: -atoms_per_target.get(t["authorization_target_id"], 0)):
    tid = t["authorization_target_id"]
    add(
        f"<tr><td>{E(short(t['display_label']))}</td>"
        f"<td><code>{E(idfrag(tid))}</code></td>"
        f"<td>{E(t['target_kind'])}</td>"
        f"<td>{E(tlabel.get(t['tenant_id'], '-'))}</td>"
        f"<td>{E(short(unit_of.get(t.get('owner_unit_id'), {}).get('display_label', '-')))}</td>"
        f"<td>{''.join(f'<span class=chip>{E(a)}</span>' for a in t['actions'])}</td>"
        f'<td class="n">{perms_per_target.get(tid, 0)}</td>'
        f'<td class="n">{atoms_per_target.get(tid, 0)}</td></tr>'
    )
add("</tbody></table></div></section>")

# ---- directory state ----------------------------------------------------
add('<section id="directory"><h3>Directory state</h3>')
add(
    '<p class="lede">The observed directory - what an auditor would find if they read the identity '
    "system. Edge counts, account observations and their validity windows. The derivation over "
    "these edges is exactly what the experiment asks an authorization engine to reproduce, so the "
    "edges are published and the derivation is not.</p>"
)
add('<div class="grid g2">')
add(chart_card(
    "Directory edges by kind",
    hbar(
        [
            ("memberships", len(rbac["memberships"])),
            ("group nesting", len(rbac["group_nesting"])),
            ("group → role", len(rbac["group_role_assignments"])),
            ("subject → role", len(rbac["subject_role_assignments"])),
            ("role hierarchy", len(rbac["role_hierarchy"])),
            ("role grants", len(rbac["role_grants"])),
            ("direct entitlements", len(rbac["direct_entitlements"])),
        ],
        width=490, label_w=146,
        note="Direct entitlements are empty by construction: every grant in this world flows "
             "through a role, so nothing bypasses the role graph.",
    ),
))
add(chart_card(
    "Account observations",
    hbar(
        [(k, v, S1 if k == "active" else S2) for k, v in obs_state.most_common()],
        width=490, label_w=146,
        note=f"{num(len(rbac['account_observations']))} observations, one per account. "
             + "; ".join(f"{num(v)} {k}" for k, v in obs_window.most_common())
             + ". A closing window is what makes a later tick materially different from an "
               "earlier one.",
    ),
))
add("</div></section>")

# ---- corpus -------------------------------------------------------------
add('<section id="corpus"><h3>Evaluation corpus shape</h3>')
add(
    f'<p class="lede">{num(len(cells))} evaluation cells, each paired one-to-one with an access '
    "request. A cell names an access atom, a context and a tick; the join from cell to subject and "
    "target below is a public one, through the access atom. Session slots and role activation "
    "requests are both empty in this experiment, so no cell depends on an activated session.</p>"
)
add('<div class="tiles" style="margin-bottom:14px">')
for k, n, x in [
    ("Cells", len(cells), "the scoring unit"),
    ("Access requests", len(corpus["access_requests"]), "1:1 with cells"),
    ("Contexts", len(corpus["contexts"]), "environment framings"),
    ("Ticks", len(set(c["tick"] for c in cells)), "logical time points"),
    ("Session slots", len(corpus["session_slots"]), "unused here"),
    ("Activation requests", len(corpus["role_activation_requests"]), "unused here"),
]:
    add(f'<div class="tile"><span class="n">{num(n)}</span>'
        f'<span class="k">{E(k)}</span><div class="x">{E(x)}</div></div>')
add("</div>")

tick_counts = Counter(c["tick"] for c in cells)
ctx_counts = Counter(c["context_id"] for c in cells)
ctx_names = {cid: f"context {idfrag(cid)}" for cid in ctx_counts}
add('<div class="grid g2">')
add(chart_card(
    "Cells per tick",
    hbar(
        [(f"tick {k}", v) for k, v in sorted(tick_counts.items())],
        width=490, label_w=136,
        note="The later tick carries only the cells whose validity windows have moved; it is a "
             "small, deliberate slice.",
    ),
))
add(chart_card(
    "Cells per context",
    hbar(
        [(ctx_names[k], v) for k, v in ctx_counts.most_common()],
        width=490, label_w=166,
    ),
))
add(chart_card(
    "Cells by subject kind",
    hbar(
        [(k, v) for k, v in cell_subject_kind.most_common()],
        width=490, label_w=136,
        note="Joined cell → access atom → access subject, all public tables.",
    ),
))
add(chart_card(
    "Cells by requested action",
    hbar([(k, v) for k, v in cell_action.most_common()], width=490, label_w=136),
))
add(chart_card(
    "Cells by target kind",
    hbar([(k, v) for k, v in cell_target_kind.most_common()], width=490, label_w=136),
))
add(chart_card(
    "Cells by evaluation profile",
    hbar(
        [(k.replace("_", " "), v) for k, v in profiles.most_common()],
        width=490, label_w=166,
        note="From authorization-kernel.json: every cell is evaluated under the same profile, so "
             "profile choice is not a hidden variable across the corpus.",
    ),
))
add("</div></section>")

# ---- policy -------------------------------------------------------------
add('<section id="policy"><h3>Public policy surface</h3>')
add(
    '<p class="lede">Policy is public; the state it runs against is what has to be derived. '
    "The attribute facts and the rule set below are published in full, which means the guard leg "
    "of the evaluation is openly computable. The part that is not public is the directory "
    "derivation those rules sit on top of, and the runtime gates.</p>"
)
add('<div class="grid g2">')
add(chart_card(
    "Attribute facts by kind",
    hbar(
        [(k.replace("_", " "), v) for k, v in fact_kind.most_common()],
        width=490, label_w=176,
        note=f"{num(len(facts))} facts in total, "
             + ", ".join(f"{num(v)} {k}" for k, v in fact_state.most_common())
             + " - no fact is published in an unknown state, so no cell is under-specified on the "
               "attribute side.",
    ),
))
add(chart_card(
    "Facts: action class",
    hbar([(k, v) for k, v in action_class.most_common()], width=490, label_w=176),
))
add(chart_card(
    "Facts: environment network zone",
    hbar(
        [(k, v) for k, v in net_zone.most_common()],
        width=490, label_w=176,
    ),
))
add(chart_card(
    "Facts: resource target kind",
    hbar([(k, v) for k, v in res_kind_fact.most_common()], width=490, label_w=176),
))
add("</div>")

add("<h4>Rule set</h4>")
add('<div class="scroll"><table><thead><tr><th>Family</th><th>Effect</th><th>Operator</th>'
    '<th>Predicates</th><th class="n">Cells in scope</th><th class="n">Share of corpus</th>'
    "</tr></thead><tbody>")
for r in abac["rules"]:
    preds = "; ".join(
        p["kind"].replace("_", " ") + (f" [{', '.join(p['values'])}]" if p.get("values") else "")
        for p in r["predicates"]
    )
    nc = len(r["cell_ids"])
    add(
        f"<tr><td>ABAC</td><td>{E(r['effect'])}</td><td>{E(r['operator'])}</td>"
        f"<td>{E(preds)}</td>"
        f'<td class="n">{num(nc)}</td><td class="n">{pct(nc, len(cells))}</td></tr>'
    )
for r in rebac["rules"]:
    preds = "; ".join(
        p.get("kind", "").replace("_", " ")
        + (f" [{', '.join(str(v) for v in p['values'])}]" if p.get("values") else "")
        for p in r.get("predicates", [])
    ) or "-"
    nc = len(r.get("cell_ids", []))
    add(
        f"<tr><td>ReBAC</td><td>{E(r.get('effect', '-'))}</td>"
        f"<td>{E(r.get('operator', '-'))}</td><td>{E(preds)}</td>"
        f'<td class="n">{num(nc)}</td><td class="n">{pct(nc, len(cells))}</td></tr>'
    )
add("</tbody></table></div>")
add(
    '<div class="note"><strong>Rule identifiers are deliberately elided.</strong> The published '
    "rule ids are descriptive strings that name the situation each rule is written for. They are "
    "public, and they carry no outcome for any individual cell - but printing them would embed "
    "substrings that an automated audit of this page treats as evaluator vocabulary, and a view "
    "that has to be argued about is worse than one that is obviously clean. Rules are therefore "
    "shown by effect, operator, predicate and scope size, which is the whole of their "
    "behaviour.</div>"
)
add('<div class="grid g2" style="margin-top:14px">')
add(chart_card(
    "ReBAC relation tuples by relation",
    hbar(
        [(k, v) for k, v in rel_relations.most_common()],
        width=490, label_w=146,
        note=f"{num(len(rebac['relation_tuples']))} tuples; "
             f"{num(len(rebac.get('unknown_evidence_cell_ids', [])))} cells flagged as having "
             "unknown relationship evidence.",
    ),
))
add(
    '<div class="card"><figure><figcaption>Composition</figcaption>'
    '<dl class="kv">'
    + "".join(
        f"<dt>{E(k)}</dt><dd>{E(str(v.get('family', k)))} &middot; schema "
        f"{E(str(v.get('component_schema_version', '-')))}</dd>"
        for k, v in load(PUBLIC / "authorization" / "authorization-composition.json").items()
        if isinstance(v, dict) and "component_digest" in v
    )
    + f"<dt>cells with a profile</dt><dd>{num(len(authk['cells']))}</dd>"
    + "</dl>"
    '<p class="chart-note">authorization-composition.json carries digest references only - it '
    "binds the three families to one another and to the corpus, and holds no per-cell content."
    "</p></figure></div>"
)
add("</div></section>")

# ---- opaque ids ---------------------------------------------------------
add('<section id="opaque"><h3>Opaque identifiers</h3>')
add(
    '<p class="lede">Everything on this page is labelled the way the public package labels it.</p>'
)
add(
    '<div class="note">Every identifier in the published artifacts is an opaque UUID, and every '
    "display label is a deliberately anonymised placeholder of the form "
    "<code>Example Authorization Target 000085</code>. The released package exposes "
    "<strong>no public logical-key to compiled-id index</strong>: there is no table, manifest "
    "entry or API in SynthWorld 0.15.0 that maps a compiled UUID back to the business key the "
    "adapter fed in. That is a documented gap in the released surface, not a choice made here.<br><br>"
    "The practical consequence is that the business names in the source topology - the actual "
    "service, team and domain names - cannot be shown against the compiled entities on this page. "
    "Short labels above (<code>Target 000085</code>, <code>Unit 036</code>) are cosmetic trims of "
    "the published placeholder labels, and UUID fragments are the first segment of the published "
    "UUID. Nothing has been re-identified.</div>"
)
add("</section>")

# ---- topology-side context ---------------------------------------------
add('<section id="topology"><h3>Topology-side mapping context</h3>')
add(
    '<p class="lede">This section is experiment-owned: it comes from the adapter configuration and '
    "the mapping ledger, not from SynthWorld. It records how the source topology was turned into "
    "the world above, and - just as importantly - which parts of the source could not be carried "
    "across.</p>"
)
add('<div class="tiles" style="margin-bottom:14px">')
for k, n, x in [
    ("Topology fields", len(ledger["ledger"]), "classified in the ledger"),
    ("Represented directly", ledger_class.get("represented_directly", 0), "exact construct"),
    ("Documented transformation", ledger_class.get("documented_transformation", 0),
     "approximated, with rationale"),
    ("Experiment metadata", ledger_class.get("experiment_metadata", 0), "kept outside the world"),
    ("Not representable", ledger_class.get("not_representable", 0), "no SynthWorld construct"),
]:
    add(f'<div class="tile"><span class="n">{num(n)}</span>'
        f'<span class="k">{E(k)}</span><div class="x">{E(x)}</div></div>')
add("</div>")

add('<div class="grid g2">')
add(chart_card(
    "Source fields by classification",
    hbar(
        [
            (k.replace("_", " "), v)
            for k, v in ledger_class.most_common()
        ],
        width=490, label_w=176,
        note="A field is only 'represented directly' when SynthWorld has an exact construct for "
             "it. Everything else is written down with its reason.",
    ),
))
add(chart_card(
    "Adapter output counts",
    hbar(
        [(k.replace("_", " "), v) for k, v in sorted(
            ledger["counts"].items(), key=lambda kv: -kv[1]
        )],
        width=490, label_w=236, row_h=22,
    ),
))
add("</div>")

# mapping rules pulled out of experiment.yaml
def yaml_block(*path):
    """Tiny targeted reader for the flat mapping blocks in experiment.yaml."""
    lines = exp_yaml.splitlines()
    depth = 0
    idx = 0
    for key in path:
        found = -1
        want = "  " * depth + key + ":"
        for i in range(idx, len(lines)):
            if lines[i].startswith(want):
                found = i
                break
        if found < 0:
            return []
        idx = found + 1
        depth += 1
    out = []
    indent = "  " * depth
    for line in lines[idx:]:
        if not line.strip() or line.strip().startswith("#"):
            continue
        if not line.startswith(indent):
            break
        body = line[len(indent):]
        if body.startswith(" "):
            continue
        out.append(body.split("#")[0].strip())
    return out


def kv_pairs(items):
    rows = []
    for item in items:
        if ":" not in item:
            continue
        k, v = item.split(":", 1)
        rows.append((k.strip().strip('"'), v.strip().strip('"')))
    return rows


add("<h4>Mapping rules</h4>")
add('<div class="grid g2">')
for caption, rows, lhs, rhs in [
    ("Region &rarr; tenant", kv_pairs(yaml_block("tenancy", "region_to_tenant")),
     "topology region", "tenant key"),
    ("Service type &rarr; target kind",
     kv_pairs(yaml_block("resources", "service_type_to_target_kind")),
     "service_type", "target kind"),
    ("Action &rarr; action class", kv_pairs(yaml_block("resources", "action_to_action_class")),
     "action", "action class"),
    ("Ownership type &rarr; role", kv_pairs(yaml_block("roles", "ownership_type_to_role")),
     "ownership_type", "role"),
    ("Role &rarr; granted actions", kv_pairs(yaml_block("roles", "grants")),
     "role", "actions"),
    ("Data classification &rarr; information classification",
     kv_pairs(yaml_block("resources", "data_classification_to_information_classification")),
     "data_classification", "information classification"),
]:
    if not rows:
        continue
    add('<div class="card"><figure>')
    add(f"<figcaption>{caption}</figcaption>")
    add(f'<table><thead><tr><th>{E(lhs)}</th><th>{E(rhs)}</th></tr></thead><tbody>')
    for k, v in rows:
        add(f"<tr><td>{E(k)}</td><td><code>{E(v)}</code></td></tr>")
    add("</tbody></table></figure></div>")
add("</div>")

scaling = dict(kv_pairs(yaml_block("scaling")))
temporal = dict(kv_pairs(yaml_block("temporal")))
authz = dict(kv_pairs(yaml_block("authorization")))
add('<div class="grid g3" style="margin-top:14px">')
add(
    '<div class="card"><h4 style="margin-top:0">Population scaling</h4><dl class="kv">'
    + "".join(f"<dt>{E(k)}</dt><dd>{E(v)}</dd>" for k, v in scaling.items())
    + "</dl></div>"
)
add(
    '<div class="card"><h4 style="margin-top:0">Temporal model</h4><dl class="kv">'
    + "".join(f"<dt>{E(k)}</dt><dd>{E(v)}</dd>" for k, v in temporal.items())
    + "</dl></div>"
)
add(
    '<div class="card"><h4 style="margin-top:0">Evaluation profile</h4><dl class="kv">'
    + "".join(f"<dt>{E(k)}</dt><dd>{E(v)}</dd>" for k, v in authz.items())
    + "</dl></div>"
)
add("</div>")

add("<h4>Mapping ledger</h4>")
add(
    '<p style="font-size:0.88rem;color:var(--text-2);margin:0 0 10px">Every field of the source '
    "topology, classified, with the reason. Scrolls inside its own frame.</p>"
)
add('<div class="scroll tall"><table><thead><tr><th>Topology field</th>'
    "<th>Classification</th><th>SynthWorld target</th><th>Rationale</th>"
    "</tr></thead><tbody>")
order = {"represented_directly": 0, "documented_transformation": 1,
         "experiment_metadata": 2, "not_representable": 3}
for e in sorted(ledger["ledger"], key=lambda e: (order.get(e["classification"], 9),
                                                 e["topology_field"])):
    add(
        f"<tr><td><code>{E(e['topology_field'])}</code></td>"
        f"<td>{E(e['classification'].replace('_', ' '))}</td>"
        f"<td><code>{E(e['synthworld_target'])}</code></td>"
        f"<td>{E(e['rationale'])}</td></tr>"
    )
add("</tbody></table></div>")
add(
    '<div class="note"><strong>Digests recorded by the adapter.</strong> topology '
    f"<code>{E(ledger['topology_sha256'][:16])}</code> &middot; adapter config "
    f"<code>{E(ledger['config_sha256'][:16])}</code> &middot; generated import "
    f"<code>{E(ledger['import_sha256'][:16])}</code>. The compiled world above is a function of "
    "those three inputs and the seed.</div>"
)
add("</section>")

# ---- public fields used -------------------------------------------------
FIELD_AUDIT = [
    ("02-synthworld-public/PUBLIC-INDEX.json", "sha256 (map of artifact path to digest)",
     "Provenance table"),
    ("02-synthworld-public/*/manifest.json",
     "artifacts[].path, artifacts[].byte_size, artifacts[].schema_version, "
     "artifacts[].digest.value",
     "Provenance table"),
    ("identity-access/identity-access-universe.json",
     "seed, compiler_version, selector_algorithm_version, schema_version, synthetic",
     "Compilation identity"),
    ("identity-access/identity-access-universe.json",
     "tenants[].tenant_id, tenants[].display_label", "Tenant rollup, all tenant labels"),
    ("identity-access/identity-access-universe.json",
     "organisations[].organisation_id, organisations[].tenant_id", "Per-tenant org count"),
    ("identity-access/identity-access-universe.json",
     "units[].unit_id, .tenant_id, .unit_kind, .parent_unit_id, .display_label",
     "Unit hierarchy, unit-kind chart, owner-unit columns"),
    ("identity-access/identity-access-universe.json",
     "principals[].principal_id, .tenant_id, .unit_id, .principal_kind",
     "Principal-kind chart, principals per unit"),
    ("identity-access/identity-access-universe.json",
     "accounts[].account_id, .tenant_id, .account_kind", "Account-kind chart, tenant rollup"),
    ("identity-access/identity-access-universe.json",
     "access_subjects[].subject_id, .subject_kind, .tenant_id",
     "Subject-kind charts, cell subject-kind join"),
    ("identity-access/identity-access-universe.json",
     "groups[].group_id, .tenant_id, .display_label", "Group nesting forest, tenant rollup"),
    ("identity-access/identity-access-universe.json",
     "roles[].role_id, .tenant_id, .owner_unit_id, .display_label",
     "Role ladders, role table"),
    ("identity-access/identity-access-universe.json",
     "authorization_targets[].authorization_target_id, .tenant_id, .owner_unit_id, "
     ".target_kind, .actions, .display_label",
     "Target table, target-kind and actions-per-target charts"),
    ("identity-access/identity-access-universe.json",
     "permissions[].permission_id, .authorization_target_id",
     "Permission count, permissions-per-target column"),
    ("identity-access/identity-access-universe.json",
     "access_atoms[].access_atom_id, .subject_id, .authorization_target_id, .action",
     "Atom charts, atoms-per-target column, cell joins"),
    ("identity-access/identity-access-universe.json",
     "relationship_anchors[].entity_kind", "Anchor chart"),
    ("directory-rbac/directory-rbac-kernel.json",
     "memberships[].subject_id, .group_id", "Members-per-group chart, edge counts"),
    ("directory-rbac/directory-rbac-kernel.json",
     "group_nesting[].child_group_id, .parent_group_id", "Nesting forest"),
    ("directory-rbac/directory-rbac-kernel.json",
     "group_role_assignments[] (count only)", "Edge counts"),
    ("directory-rbac/directory-rbac-kernel.json",
     "subject_role_assignments[].subject_id, .role_id", "Role table, edge counts"),
    ("directory-rbac/directory-rbac-kernel.json",
     "role_hierarchy[].senior_role_id, .junior_role_id", "Seniority ladders"),
    ("directory-rbac/directory-rbac-kernel.json",
     "role_grants[].role_id", "Permissions-per-role chart, role table"),
    ("directory-rbac/directory-rbac-kernel.json",
     "direct_entitlements[] (count only)", "Edge counts"),
    ("directory-rbac/directory-rbac-kernel.json",
     "account_observations[].administrative_state, .valid_until_tick",
     "Account observation chart"),
    ("directory-rbac/directory-rbac-kernel.json",
     "identity_access_universe_digest.value", "Cross-artifact binding"),
    ("evaluation-corpus/evaluation-corpus.json",
     "evaluation_cells[].cell_id, .access_atom_id, .context_id, .tick",
     "Corpus charts, cell joins"),
    ("evaluation-corpus/evaluation-corpus.json",
     "access_requests[], contexts[], session_slots[], role_activation_requests[] (counts only)",
     "Corpus tiles"),
    ("authorization/abac-state.json",
     "attribute_facts[].kind, .value, .value_state", "Attribute-fact charts"),
    ("authorization/abac-state.json",
     "rules[].effect, .operator, .predicates[].kind, .predicates[].values, "
     "len(rules[].cell_ids)",
     "Rule table (rule_id and the cell id list itself are not printed)"),
    ("authorization/abac-state.json",
     "evaluation_corpus_digest.value", "Cross-artifact binding"),
    ("authorization/rebac-state.json",
     "relation_tuples[].relation, unknown_evidence_cell_ids, rules[], "
     "evaluation_corpus_digest.value",
     "Relation chart, rule table, binding"),
    ("authorization/authorization-kernel.json", "cells[].profile", "Profile chart"),
    ("authorization/authorization-composition.json",
     "family, component_schema_version (digests not printed)", "Composition card"),
    ("01-source/config/experiment.yaml",
     "tenancy.region_to_tenant, resources.service_type_to_target_kind, "
     "resources.action_to_action_class, "
     "resources.data_classification_to_information_classification, "
     "roles.ownership_type_to_role, roles.grants, scaling.*, temporal.*, authorization.*",
     "Mapping-rule tables"),
    ("01-source/generated/mapping-ledger.json",
     "ledger[].topology_field, .classification, .synthworld_target, .rationale, "
     "counts.*, topology_sha256, config_sha256, import_sha256",
     "Ledger table, classification chart, adapter counts"),
]

add('<section id="fields"><h3>Public fields used</h3>')
add(
    '<p class="lede">The complete list of inputs this page is built from, field by field, so a '
    "reader can check the boundary rather than take it on trust. The generator "
    "(<code>bin/70_visualize.py</code>) refuses at read time to open any path outside these two "
    "roots, and audits its own output before writing it.</p>"
)
add('<div class="scroll tall"><table><thead><tr><th>File</th><th>Fields read</th>'
    "<th>Where it appears</th></tr></thead><tbody>")
for f, fields, where in FIELD_AUDIT:
    add(
        f"<tr><td><code>{E(f)}</code></td><td>{E(fields)}</td><td>{E(where)}</td></tr>"
    )
add("</tbody></table></div>")
add(
    '<div class="note"><strong>Not read, and not shown:</strong> anything under '
    "<code>06-evaluator/</code>. No expected outcome for any cell, no per-cell case label, no "
    "scoring result, no comparison of a predicted outcome against a stored one, and no per-cell "
    "identifier from the policy rule scopes. The rule table shows only how many cells each rule "
    "covers, never which.</div>"
)
add("</section>")

add(
    "<footer>Generated by <code>bin/70_visualize.py</code> from the public artifact set. "
    f"{BANNER}. Self-contained: no external stylesheet, script, font, image or network call.</footer>"
)
add("</div>")
add(f"<script>{JS}</script>")
add("</body></html>")

html_out = "\n".join(P)

# ==========================================================================
# SELF-AUDIT then write
# ==========================================================================

low = html_out.lower()
hits = [t for t in AUDIT_TERMS if t in low]
if hits:
    raise SystemExit(f"AUDIT FAILED - evaluator vocabulary in output: {hits}")
if BANNER not in html_out:
    raise SystemExit("AUDIT FAILED - banner string missing")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(html_out, "utf-8")
size = OUT.stat().st_size
print(f"wrote {OUT} ({size:,} bytes)")
print(f"audit: banner present, 0/{len(AUDIT_TERMS)} evaluator terms present")
if not (30_000 < size < 16_000_000):
    print("WARNING: size outside the expected 30KB..16MB window", file=sys.stderr)
    sys.exit(1)
