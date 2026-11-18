def connected_groups(
    touches: dict[str, set[str]], links: dict[str, set[str]], ignored: set[str]
) -> list[list[str]]:
    parent = {key: key for key in touches}

    def top(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def join(a: str, b: str) -> None:
        parent[top(a)] = top(b)

    by_field: dict[str, str] = {}
    for key, fields in touches.items():
        for f in fields - ignored:
            if f in by_field:
                join(key, by_field[f])
            else:
                by_field[f] = key
    for key, others in links.items():
        for other in others:
            if other in parent and key in parent:
                join(key, other)
    grouped: dict[str, list[str]] = {}
    for key in touches:
        grouped.setdefault(top(key), []).append(key)
    return sorted(grouped.values(), key=lambda g: (-len(g), sorted(g)))


def cohesion_label(groups: int) -> str:
    return "high" if groups <= 1 else "medium" if groups == 2 else "low"
