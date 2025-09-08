import bpy
from mathutils import Vector
from typing import Tuple, Optional

PROP_POINTS = "SuperAlignPoints"
LABELS = ("A", "B", "C")


def ensure_points_dict(obj: bpy.types.Object) -> None:
    if obj is None:
        return
    if PROP_POINTS not in obj:
        obj[PROP_POINTS] = {"A": "", "B": "", "C": ""}
    else:
        d = obj[PROP_POINTS]
        for k in LABELS:
            if k not in d:
                d[k] = ""
        obj[PROP_POINTS] = d


def set_point_name(obj: bpy.types.Object, label: str, name: str) -> None:
    ensure_points_dict(obj)
    d = obj[PROP_POINTS]
    d[label] = name
    obj[PROP_POINTS] = d


def get_point_object(obj: bpy.types.Object, label: str) -> Optional[bpy.types.Object]:
    if obj is None or PROP_POINTS not in obj:
        return None
    name = obj[PROP_POINTS].get(label, "")
    if not name:
        return None
    return bpy.data.objects.get(name)


def get_object_points_world(obj: bpy.types.Object) -> Optional[Tuple[Vector, Vector, Vector]]:
    A = get_point_object(obj, "A")
    B = get_point_object(obj, "B")
    C = get_point_object(obj, "C")
    if not (A and B and C):
        return None
    return (
        A.matrix_world.translation.copy(),
        B.matrix_world.translation.copy(),
        C.matrix_world.translation.copy(),
    )
