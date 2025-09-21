import bpy
from bpy.types import Panel

from ..utils.align_locators import SCENE_PROP_SIZE


class SUPERTOOLS_PT_main_panel(Panel):
    bl_label = "Super Tools"
    bl_idname = "SUPERTOOLS_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Super Tools'
    # Ensure this appears above other panels in this category
    bl_order = 0

    def draw_header(self, context):
        # Leave header content empty; version is appended to panel title
        pass

    def draw(self, context):
        # Intentionally empty; child panels (e.g., Modeling, Super Align) appear under this
        pass


# Append version to the main panel title so it appears inline and left-aligned
def _supertools_version_suffix():
    try:
        import importlib
        pkg = importlib.import_module('super_tools')
        bl = getattr(pkg, 'bl_info', None)
        if isinstance(bl, dict):
            ver = bl.get('version')
            if isinstance(ver, (tuple, list)) and len(ver) >= 3:
                return f" v{ver[0]}.{ver[1]}.{ver[2]}"
    except Exception:
        return ""
    return ""


_ver = _supertools_version_suffix()
if _ver:
    try:
        SUPERTOOLS_PT_main_panel.bl_label = SUPERTOOLS_PT_main_panel.bl_label + _ver
    except Exception:
        pass


class SUPERTOOLS_PT_modeling_panel(Panel):
    bl_label = "Modeling"
    bl_idname = "SUPERTOOLS_PT_modeling_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Super Tools'
    bl_parent_id = 'SUPERTOOLS_PT_main_panel'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.operator("mesh.super_extrude_modal", text="Super Extrude")
        col.operator("mesh.super_orient_modal", text="Super Orient")


class SUPERTOOLS_PT_align_panel(Panel):
    bl_label = "Super Align"
    bl_idname = "SUPERTOOLS_PT_align_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Super Tools'
    bl_parent_id = 'SUPERTOOLS_PT_main_panel'
    # Default collapsed; and order after the main panel
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="Alignment Points")
        # Size slider (absolute diameter in world units)
        if hasattr(context.scene, SCENE_PROP_SIZE):
            col.prop(context.scene, SCENE_PROP_SIZE, text="Locator Size (m)", slider=True)
        col.operator("super_tools.plot_points", text="Plot A/B/C Points")
        col.operator("super_tools.delete_points_selected", text="Delete Points (Selected)")
        col.separator()
        col.label(text="Align")
        col.operator("super_tools.align_to_active", text="Align To Active")
        # ICP settings: pick target vertex group (on active object)
        if context.active_object and hasattr(context.active_object, "vertex_groups"):
            col.prop_search(
                context.scene,
                "superalign_icp_target_group",
                context.active_object,
                "vertex_groups",
                text="ICP Target Group",
            )
        # ICP option: allow uniform scale during alignment
        if hasattr(context.scene, "superalign_icp_allow_scale"):
            col.prop(context.scene, "superalign_icp_allow_scale", text="Allow Scale")
        col.operator("super_tools.icp_align_modal", text="ICP Align (ESC to stop)")
        col.operator("super_tools.cpd_align_modal", text="CPD Align (ESC to stop)")
        col.separator()
        col.label(text="Utilities")
        col.operator("super_tools.mesh_flipbook", text="Sequential Vis (toggle)")



def register():
    bpy.utils.register_class(SUPERTOOLS_PT_main_panel)
    bpy.utils.register_class(SUPERTOOLS_PT_modeling_panel)
    bpy.utils.register_class(SUPERTOOLS_PT_align_panel)


def unregister():
    bpy.utils.unregister_class(SUPERTOOLS_PT_align_panel)
    bpy.utils.unregister_class(SUPERTOOLS_PT_modeling_panel)
    bpy.utils.unregister_class(SUPERTOOLS_PT_main_panel)
