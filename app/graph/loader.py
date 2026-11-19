"""그래프 입출력. 현장 실측값을 JSON으로 두고 그대로 읽는다."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from app.graph.schema import Graph, Node, Edge, SchemaError


def load_graph(nodes_path: str | Path, edges_path: str | Path) -> Graph:
    g = Graph()
    for row in json.loads(Path(nodes_path).read_text(encoding="utf-8")):
        g.add_node(Node(**row))
    for row in json.loads(Path(edges_path).read_text(encoding="utf-8")):
        g.add_edge(Edge(**row))
    problems = g.validate()
    if problems:
        raise SchemaError("그래프 참조 오류:\n  " + "\n  ".join(problems))
    return g


def save_graph(g: Graph, nodes_path: str | Path, edges_path: str | Path) -> None:
    Path(nodes_path).write_text(
        json.dumps([asdict(n) for n in g.nodes.values()],
                   ensure_ascii=False, indent=2), encoding="utf-8")
    Path(edges_path).write_text(
        json.dumps([asdict(e) for e in g.edges.values()],
                   ensure_ascii=False, indent=2), encoding="utf-8")
