import bpy
import bmesh
from mathutils import Vector
from typing import Optional

# Constants
VCOL_NAME = "SuperAlignColor"
MAT_RED = "SuperAlign_Locator_RED"
MAT_GREEN = "SuperAlign_Locator_GREEN"
MAT_BLUE = "SuperAlign_Locator_BLUE"
SCENE_PROP_SIZE = "superalign_size_factor"  # absolute diameter (world units)


def _get_or_create_locator_material(mat_name: str, rgba: tuple[float, float, float, float]) -> bpy.types.Material:
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()
        out = nt.nodes.new('ShaderNodeOutputMaterial')
        emis = nt.nodes.new('ShaderNodeEmission')
        emis.inputs['Color'].default_value = rgba
        emis.inputs['Strength'].default_value = 3.0
        nt.links.new(emis.outputs['Emission'], out.inputs['Surface'])
        mat.diffuse_color = rgba
    else:
        if mat.use_nodes and mat.node_tree:
            emis = next((n for n in mat.node_tree.nodes if n.type == 'EMISSION'), None)
            if emis is not None:
                emis.inputs['Color'].default_value = rgba
        mat.diffuse_color = rgba
    return mat


def get_material_for_label(label: str) -> bpy.types.Material:
    if label == 'A':
        return _get_or_create_locator_material(MAT_RED, (1.0, 0.1, 0.1, 1.0))
    if label == 'B':
        return _get_or_create_locator_material(MAT_GREEN, (0.1, 1.0, 0.1, 1.0))
    return _get_or_create_locator_material(MAT_BLUE, (0.1, 0.1, 1.0, 1.0))


def get_rgba_for_label(label: str) -> tuple[float, float, float, float]:
    if label == 'A':
        return (1.0, 0.1, 0.1, 1.0)
    if label == 'B':
        return (0.1, 1.0, 0.1, 1.0)
    return (0.1, 0.1, 1.0, 1.0)


def get_global_diameter(context: Optional[bpy.types.Context] = None) -> float:
    context = context or bpy.context
    scn = context.scene
    return max(0.001, float(getattr(scn, SCENE_PROP_SIZE, 0.1)))


def _world_bbox_max_radius(obj: bpy.types.Object) -> float:
    if obj is None or not obj.bound_box:
        return 0.0
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    min_v = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    max_v = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    size = max_v - min_v
    return 0.5 * max(size.x, size.y, size.z)


def rescale_all_locators(context: Optional[bpy.types.Context] = None) -> None:
    context = context or bpy.context
    scn = context.scene
    desired_radius = max(0.0005, 0.5 * get_global_diameter(context))

    from .align_points import PROP_POINTS, LABELS, get_point_object

    for parent in [o for o in scn.objects if o.type == 'MESH' and PROP_POINTS in o]:
        for label in LABELS:
            loc = get_point_object(parent, label)
            if loc is None or loc.type != 'MESH':
                continue
            current_radius = _world_bbox_max_radius(loc)
            if current_radius <= 1e-9:
                continue
            ratio = desired_radius / current_radius
            try:
                loc.scale = (loc.scale.x * ratio, loc.scale.y * ratio, loc.scale.z * ratio)
                if hasattr(loc, "show_name"):
                    loc.show_name = False
            except Exception:
                pass


def update_size_callback(self, context):
    rescale_all_locators(context)


def register_scene_properties():
    from bpy.props import FloatProperty
    if not hasattr(bpy.types.Scene, SCENE_PROP_SIZE):
        setattr(
            bpy.types.Scene,
            SCENE_PROP_SIZE,
            FloatProperty(
                name="Locator Size",
                description="Locator diameter in world units (applies to all Super Align locators)",
                default=0.1,
                min=0.001,
                max=100.0,
                subtype='DISTANCE',
                update=update_size_callback,
            ),
        )


def unregister_scene_properties():
    if hasattr(bpy.types.Scene, SCENE_PROP_SIZE):
        delattr(bpy.types.Scene, SCENE_PROP_SIZE)


def link_to_parent_collections(obj: bpy.types.Object, parent: Optional[bpy.types.Object]) -> None:
    linked = False
    if parent is not None and getattr(parent, 'users_collection', None):
        for coll in parent.users_collection:
            try:
                coll.objects.link(obj)
                linked = True
            except Exception:
                pass
    if not linked:
        bpy.context.scene.collection.objects.link(obj)


def create_locator(parent: bpy.types.Object, label: str, location: Vector) -> bpy.types.Object:
    diameter = get_global_diameter()
    radius = max(0.0005, 0.5 * diameter)

    mesh = bpy.data.meshes.new(f"{label}_mesh")
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=radius)
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(label, mesh)
    mat = get_material_for_label(label)

    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

    # Vertex color attribute
    rgba = get_rgba_for_label(label)
    try:
        if VCOL_NAME in mesh.color_attributes:
            col_attr = mesh.color_attributes[VCOL_NAME]
        else:
            col_attr = mesh.color_attributes.new(name=VCOL_NAME, type='FLOAT_COLOR', domain='CORNER')
        for i in range(len(col_attr.data)):
            col_attr.data[i].color = rgba
    except Exception:
        pass

    if hasattr(obj, "show_in_front"):
        obj.show_in_front = True
    if hasattr(obj, "show_name"):
        obj.show_name = False

    # Link to same collections as parent
    link_to_parent_collections(obj, parent)

    obj.matrix_world.translation = location

    # Parent to target object, keep world transform
    if parent is not None:
        obj.parent = parent
        obj.matrix_parent_inverse = parent.matrix_world.inverted()

    return obj


def register():
    # Expose properties via standard register for super_tools module loader
    register_scene_properties()


def unregister():
    unregister_scene_properties()
