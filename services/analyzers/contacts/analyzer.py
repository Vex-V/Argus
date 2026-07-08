"""Contacts / social-network overlap comparison (C12).

Combines a plain Jaccard index over the follower/following sets with a
weighted overlap that values interaction contacts (commenters, mentioners,
likers) above passive follows. Combined 40% Jaccard / 60% weighted.
Each contact is a dict {"id": str, "weight": float}.
"""
_JACCARD_WEIGHT = 0.4
_WEIGHTED_WEIGHT = 0.6
_MAX_MUTUAL = 20


def jaccard_similarity(set_a: set, set_b: set) -> float:
    if not set_a and not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def weighted_overlap(contacts_a: list[dict], contacts_b: list[dict]) -> float:
    ids_a = {c["id"]: c.get("weight", 1.0) for c in contacts_a}
    ids_b = {c["id"]: c.get("weight", 1.0) for c in contacts_b}
    shared = set(ids_a) & set(ids_b)
    if not shared:
        return 0.0
    weighted_sum = sum(min(ids_a[s], ids_b[s]) for s in shared)
    total_weight = sum(ids_a.values()) + sum(ids_b.values())
    return (2 * weighted_sum) / total_weight if total_weight > 0 else 0.0


def analyze_contacts(contacts_a: list[dict], contacts_b: list[dict]) -> dict:
    set_a = {c["id"] for c in contacts_a}
    set_b = {c["id"] for c in contacts_b}

    jac = jaccard_similarity(set_a, set_b)
    weighted = weighted_overlap(contacts_a, contacts_b)
    combined = _JACCARD_WEIGHT * jac + _WEIGHTED_WEIGHT * weighted

    mutual_all = set_a & set_b
    return {
        "jaccard_followers": round(jac, 4),
        "weighted_interaction_overlap": round(weighted, 4),
        "combined_score": round(combined, 4),
        "mutual_contacts": sorted(mutual_all)[:_MAX_MUTUAL],
        "evidence": [
            f"jaccard: {jac:.3f}",
            f"weighted_overlap: {weighted:.3f}",
            f"mutual_contacts: {len(mutual_all)}",
        ],
    }
