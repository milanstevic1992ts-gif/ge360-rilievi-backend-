from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
from shapely.geometry import LineString, Point

from backend.geometry.normalizer import NormalizedPlan


@dataclass
class TopologyResult:
    graph: nx.MultiGraph
    components: list[set[str]]
    intersections: list[dict]
    dangling_nodes: list[str]


def build_topology(plan: NormalizedPlan, intersection_tolerance_mm: float = 5.0) -> TopologyResult:
    graph = nx.MultiGraph()
    for node_id, node in plan.nodes.items():
        graph.add_node(node_id, sketch=(node.sketch_x, node.sketch_y))
    for wall in plan.walls:
        graph.add_edge(
            wall.start_node,
            wall.end_node,
            key=wall.id,
            wall_id=wall.id,
            length_mm=wall.length_mm,
        )

    components = [set(c) for c in nx.connected_components(graph)]
    dangling = [n for n, degree in graph.degree() if degree == 1]

    intersections: list[dict] = []
    scale = plan.scale_mm_per_unit
    lines = []
    for wall in plan.walls:
        lines.append((wall, LineString([
            (wall.sketch_a[0] * scale, wall.sketch_a[1] * scale),
            (wall.sketch_b[0] * scale, wall.sketch_b[1] * scale),
        ])))
    for i, (wa, la) in enumerate(lines):
        for wb, lb in lines[i + 1:]:
            if {wa.start_node, wa.end_node} & {wb.start_node, wb.end_node}:
                continue
            inter = la.intersection(lb)
            if isinstance(inter, Point):
                end_dist = min(
                    inter.distance(Point(la.coords[0])), inter.distance(Point(la.coords[-1])),
                    inter.distance(Point(lb.coords[0])), inter.distance(Point(lb.coords[-1])),
                )
                if end_dist > intersection_tolerance_mm:
                    intersections.append({"wallA": wa.id, "wallB": wb.id, "x": inter.x, "y": inter.y})

    return TopologyResult(graph=graph, components=components, intersections=intersections, dangling_nodes=dangling)
