from __future__ import annotations

import math
from dataclasses import dataclass

from backend.models import PlanModel, WallModel


@dataclass
class Bounds:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return max(1.0, self.max_x - self.min_x)

    @property
    def height(self) -> float:
        return max(1.0, self.max_y - self.min_y)


def model_bounds(model: PlanModel, margin_mm: float = 600.0) -> Bounds:
    xs, ys = [], []
    for wall in model.walls:
        xs.extend([wall.start.x, wall.end.x])
        ys.extend([wall.start.y, wall.end.y])
    if not xs:
        return Bounds(0, 0, 1000, 1000)
    return Bounds(min(xs) - margin_mm, min(ys) - margin_mm, max(xs) + margin_mm, max(ys) + margin_mm)


def wall_unit(wall: WallModel) -> tuple[float, float, float]:
    dx, dy = wall.end.x - wall.start.x, wall.end.y - wall.start.y
    length = math.hypot(dx, dy) or 1.0
    return dx / length, dy / length, length


def point_along(wall: WallModel, distance_mm: float) -> tuple[float, float]:
    ux, uy, _ = wall_unit(wall)
    return wall.start.x + ux * distance_mm, wall.start.y + uy * distance_mm
