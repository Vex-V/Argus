"""Username similarity analyzer (C8).

Scores how likely two usernames belong to the same person using Jaro-Winkler,
normalized Levenshtein, leet-speak normalization, separator removal, and
substring containment. Returns a score in [0, 1] plus human-readable evidence.
"""
import re

import jellyfish

_LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}


def normalize_leet(s: str) -> str:
    s = s.lower()
    for k, v in _LEET.items():
        s = s.replace(k, v)
    return re.sub(r"[._\-]", "", s)


def analyze_username_similarity(username_a: str, username_b: str) -> dict:
    """Compare two usernames; return {score, evidence}."""
    evidence: list[str] = []

    a, b = username_a.lower(), username_b.lower()

    # 1. Exact match (case-insensitive)
    if a == b:
        return {"score": 1.0, "evidence": ["exact_match"]}

    # 2. Jaro-Winkler
    jw = jellyfish.jaro_winkler_similarity(a, b)
    evidence.append(f"jaro_winkler: {jw:.3f}")

    # 3. Normalized Levenshtein
    lev = jellyfish.levenshtein_distance(a, b)
    max_len = max(len(a), len(b))
    lev_norm = 1.0 - (lev / max_len) if max_len else 0.0
    evidence.append(f"levenshtein_normalized: {lev_norm:.3f}")

    # 4. Leet-speak + separator normalization
    leet_a, leet_b = normalize_leet(username_a), normalize_leet(username_b)
    if leet_a == leet_b:
        evidence.append("leet_normalized_exact_match")
        return {"score": 0.95, "evidence": evidence}

    leet_jw = jellyfish.jaro_winkler_similarity(leet_a, leet_b)
    evidence.append(f"leet_jaro_winkler: {leet_jw:.3f}")

    # 5. Substring containment
    if a in b or b in a:
        evidence.append("substring_match")

    score = max(jw, leet_jw, lev_norm)
    return {"score": round(score, 4), "evidence": evidence}
