"""
Doc feature: 'Impact-ripple tracing — follows the dependency chain: if the portal is
out of sync, everything downstream ... is automatically flagged as at-risk'.

Doc feature: 'Scale View — checking many connected entities at once (multiple district
offices, multiple portal instances, multiple form versions), surfacing which specific
locations are lagging, not just a single generic status.'

The dependency order itself (portal -> sop -> form -> notification) is still fixed, per
the pitch. What's no longer hardcoded is how many of these chains exist per check:
systems are grouped by entity_label (e.g. "District: Warangal"), and one independent
chain is built per entity, so a single rule check can span many entities/portal
instances at once. Systems with no entity_label fall into one default entity, so the
original single-chain MVP shape still works unchanged.
"""
import networkx as nx
from collections import defaultdict
from typing import Dict, List
from app.schemas import DependentSystem, SyncStatus, RippleNode

DEFAULT_DEPENDENCY_CHAIN = [
    ("portal", "sop"),
    ("sop", "form"),
    ("form", "notification"),
]

DEFAULT_ENTITY_LABEL = "__default__"


def build_dependency_graph(systems: List[DependentSystem]) -> nx.DiGraph:
    """Builds one dependency chain per entity_label, merged into a single graph.
    Edges only ever connect systems within the same entity, so ripple tracing for
    one district never bleeds into another."""
    by_entity: Dict[str, Dict[str, str]] = defaultdict(dict)
    for s in systems:
        entity = s.entity_label or DEFAULT_ENTITY_LABEL
        by_entity[entity][s.system_type.value] = s.system_id

    g = nx.DiGraph()
    for s in systems:
        g.add_node(s.system_id, system_type=s.system_type.value, entity_label=s.entity_label)

    for system_ids_by_type in by_entity.values():
        for parent_type, child_type in DEFAULT_DEPENDENCY_CHAIN:
            if parent_type in system_ids_by_type and child_type in system_ids_by_type:
                g.add_edge(system_ids_by_type[parent_type], system_ids_by_type[child_type])
    return g


def trace_ripple(g: nx.DiGraph, out_of_sync_system_ids: List[str]) -> List[RippleNode]:
    """Every node reachable (downstream) from an out-of-sync node is at-risk, even if
    its own text technically matches — it depends on an upstream system that's already
    wrong. Descendants stay scoped per-entity automatically since cross-entity edges
    are never created."""
    at_risk_ids = set()
    reasons: Dict[str, str] = {}
    for start in out_of_sync_system_ids:
        if start not in g:
            continue
        for descendant in nx.descendants(g, start):
            at_risk_ids.add(descendant)
            reasons.setdefault(descendant, f"downstream of out-of-sync system '{start}'")

    nodes = []
    for node_id in g.nodes:
        if node_id in out_of_sync_system_ids:
            nodes.append(RippleNode(system_id=node_id, at_risk=True, reason="directly out of sync"))
        elif node_id in at_risk_ids:
            nodes.append(RippleNode(system_id=node_id, at_risk=True, reason=reasons[node_id]))
        else:
            nodes.append(RippleNode(system_id=node_id, at_risk=False, reason="in sync, no at-risk ancestors"))
    return nodes


IMPACT_WEIGHTS = {
    SyncStatus.OUT_OF_SYNC: 40,
    SyncStatus.NEEDS_REVIEW: 15,
    SyncStatus.IN_SYNC: 0,
}
DOWNSTREAM_SYSTEM_BONUS = 15


def citizen_impact_score(status: SyncStatus, downstream_at_risk_count: int) -> tuple[int, str]:
    base = IMPACT_WEIGHTS[status]
    bonus = min(downstream_at_risk_count * DOWNSTREAM_SYSTEM_BONUS, 45)
    score = min(base + bonus, 100)
    reason = (
        f"base={base} (status={status.value}) + downstream_bonus={bonus} "
        f"({downstream_at_risk_count} at-risk downstream system(s), capped at 45)"
    )
    return score, reason
