"""
Doc feature: 'Impact-ripple tracing — follows the dependency chain: if the portal is
out of sync, everything downstream ... is automatically flagged as at-risk'.

The graph is deliberately simple for the MVP: a fixed 4-node chain
  portal -> officer_sop -> form -> citizen_notification
because that's the real dependency order described in the pitch (portal is the source
of truth; the officer's SOP references it; the form encodes it; the notification tells
the citizen). Real deployments would build this graph per-scheme instead of hardcoding it,
which is called out explicitly in Constraints below.
"""
import networkx as nx
from typing import Dict, List
from app.schemas import DependentSystem, SyncStatus, RippleNode

DEFAULT_DEPENDENCY_CHAIN = [
    ("portal", "sop"),
    ("sop", "form"),
    ("form", "notification"),
]


def build_dependency_graph(system_ids_by_type: Dict[str, str]) -> nx.DiGraph:
    """system_ids_by_type maps system_type ('portal','sop','form','notification') -> system_id
    for the systems actually present in this check (MVP may only have 1-2 of the 4)."""
    g = nx.DiGraph()
    for sys_type, sys_id in system_ids_by_type.items():
        g.add_node(sys_id, system_type=sys_type)
    for parent_type, child_type in DEFAULT_DEPENDENCY_CHAIN:
        if parent_type in system_ids_by_type and child_type in system_ids_by_type:
            g.add_edge(system_ids_by_type[parent_type], system_ids_by_type[child_type])
    return g


def trace_ripple(g: nx.DiGraph, out_of_sync_system_ids: List[str]) -> List[RippleNode]:
    """Every node reachable (downstream) from an out-of-sync node is at-risk,
    even if that node's own text technically matches the rule — because it depends
    on an upstream system that's already wrong."""
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


# Weights are intentionally simple and OPEN (doc feature: "transparent priority formula
# ... shown openly, not hidden inside a black-box score"). Tune per-deployment.
IMPACT_WEIGHTS = {
    SyncStatus.OUT_OF_SYNC: 40,
    SyncStatus.NEEDS_REVIEW: 15,
    SyncStatus.IN_SYNC: 0,
}
DOWNSTREAM_SYSTEM_BONUS = 15  # per at-risk downstream system, capped below


def citizen_impact_score(status: SyncStatus, downstream_at_risk_count: int) -> tuple[int, str]:
    base = IMPACT_WEIGHTS[status]
    bonus = min(downstream_at_risk_count * DOWNSTREAM_SYSTEM_BONUS, 45)
    score = min(base + bonus, 100)
    reason = (
        f"base={base} (status={status.value}) + downstream_bonus={bonus} "
        f"({downstream_at_risk_count} at-risk downstream system(s), capped at 45)"
    )
    return score, reason
