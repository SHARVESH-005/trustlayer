"""Which views and dashboards depend on a table, read from Exasol's own dependency catalog."""
from collections import deque


def walk(edges: dict[str, list[str]], start: str) -> list[tuple[str, int]]:
    """Breadth-first walk of 'object -> objects that read it'. Returns (object, depth)."""
    seen = {start}
    out = []
    queue = deque([(start, 0)])
    while queue:
        node, depth = queue.popleft()
        for child in sorted(edges.get(node, [])):
            if child not in seen:
                seen.add(child)
                out.append((child, depth + 1))
                queue.append((child, depth + 1))
    return out


def dependency_edges(conn) -> dict[str, list[str]]:
    rows = conn.execute("""
        SELECT REFERENCED_OBJECT_SCHEMA || '.' || REFERENCED_OBJECT_NAME,
               OBJECT_SCHEMA || '.' || OBJECT_NAME
        FROM EXA_DBA_DEPENDENCIES""").fetchall()
    edges: dict[str, list[str]] = {}
    for parent, child in rows:
        edges.setdefault(parent, []).append(child)
    return edges


def affected(conn, table: str) -> dict:
    """Downstream views (with depth) and the dashboards built on them."""
    views = walk(dependency_edges(conn), table)
    names = {v for v, _ in views}
    dashboards = [
        {"dashboard": d, "owner": o, "view": f"{s}.{v}"}
        for d, o, s, v in conn.execute(
            "SELECT DASHBOARD_NAME, OWNER, VIEW_SCHEMA, VIEW_NAME FROM TRUSTLAYER.DASHBOARDS ORDER BY 1"
        ).fetchall()
        if f"{s}.{v}" in names
    ]
    return {"table": table, "views": [{"view": v, "depth": d} for v, d in views], "dashboards": dashboards}
