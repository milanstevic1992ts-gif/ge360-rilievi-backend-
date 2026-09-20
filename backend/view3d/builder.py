from __future__ import annotations

import math

import numpy as np
import trimesh
from shapely.geometry import Polygon
from shapely.ops import triangulate

from backend.models import PlanModel


def _box_segment(start_xy, angle, along_start_mm, along_end_mm, thickness_mm, z0_mm, z1_mm, name: str):
    length_mm = along_end_mm - along_start_mm
    height_mm = z1_mm - z0_mm
    if length_mm <= 0.1 or height_mm <= 0.1:
        return None
    mesh = trimesh.creation.box(extents=[length_mm / 1000, thickness_mm / 1000, height_mm / 1000])
    center_along = (along_start_mm + along_end_mm) / 2 / 1000
    sx, sy = start_xy[0] / 1000, start_xy[1] / 1000
    cx = sx + math.cos(angle) * center_along
    cy = sy + math.sin(angle) * center_along
    cz = (z0_mm + z1_mm) / 2 / 1000
    transform = trimesh.transformations.rotation_matrix(angle, [0, 0, 1])
    transform[:3, 3] = [cx, cy, cz]
    mesh.apply_transform(transform)
    mesh.metadata["name"] = name
    return mesh


def _wall_meshes(model: PlanModel):
    openings_by_wall = {}
    for o in model.openings:
        openings_by_wall.setdefault(o.wallId, []).append(o)
    meshes = []
    for wall in model.walls:
        dx, dy = wall.end.x - wall.start.x, wall.end.y - wall.start.y
        angle = math.atan2(dy, dx)
        length = wall.lengthMm
        cuts = []
        for o in openings_by_wall.get(wall.id, []):
            start = max(0.0, o.centerFromStartMm - o.widthMm / 2)
            end = min(length, o.centerFromStartMm + o.widthMm / 2)
            bottom = max(0.0, o.sillHeightMm)
            top = min(wall.heightMm, bottom + o.heightMm)
            cuts.append((start, end, bottom, top, o.id))
        breaks = {0.0, length}
        for start, end, *_ in cuts:
            breaks.add(start); breaks.add(end)
        ordered = sorted(breaks)
        for i in range(len(ordered) - 1):
            a, b = ordered[i], ordered[i+1]
            mid = (a+b)/2
            covering = [c for c in cuts if c[0] <= mid <= c[1]]
            if not covering:
                mesh = _box_segment((wall.start.x, wall.start.y), angle, a, b, wall.thicknessMm, 0, wall.heightMm, wall.id)
                if mesh is not None: meshes.append(mesh)
            else:
                bottom = min(c[2] for c in covering)
                top = max(c[3] for c in covering)
                if bottom > 0:
                    mesh = _box_segment((wall.start.x, wall.start.y), angle, a, b, wall.thicknessMm, 0, bottom, wall.id+"-below-opening")
                    if mesh is not None: meshes.append(mesh)
                if top < wall.heightMm:
                    mesh = _box_segment((wall.start.x, wall.start.y), angle, a, b, wall.thicknessMm, top, wall.heightMm, wall.id+"-above-opening")
                    if mesh is not None: meshes.append(mesh)
    return meshes


def _floor_mesh(room):
    poly = Polygon([(p.x/1000, p.y/1000) for p in room.polygon])
    if not poly.is_valid or poly.area <= 1e-8:
        return None
    vertices = []
    faces = []
    for tri in triangulate(poly):
        if not poly.covers(tri.representative_point()):
            continue
        coords = list(tri.exterior.coords)[:3]
        base = len(vertices)
        vertices.extend([[x,y,0] for x,y in coords])
        faces.append([base,base+1,base+2])
    if not faces:
        return None
    mesh = trimesh.Trimesh(vertices=np.asarray(vertices), faces=np.asarray(faces), process=False)
    mesh.metadata["name"] = "floor-"+room.roomId
    return mesh


def build_scene(model: PlanModel) -> trimesh.Scene:
    scene = trimesh.Scene()
    for i, mesh in enumerate(_wall_meshes(model)):
        scene.add_geometry(mesh, node_name=f"wallpart-{i}")
    for room in model.rooms:
        floor = _floor_mesh(room)
        if floor is not None:
            scene.add_geometry(floor, node_name=f"floor-{room.roomId}")
    return scene
