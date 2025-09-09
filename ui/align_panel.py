import bpy
from bpy.types import Panel

from ..utils.align_locators import SCENE_PROP_SIZE


class SUPERTOOLS_PT_align_panel(Panel):
    bl_label = "Super Align"
    bl_idname = "SUPERTOOLS_PT_align_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Super Tools'

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
        col.separator()
        col.label(text="Utilities")
        col.operator("super_tools.mesh_flipbook", text="Sequential Vis (toggle)")
        col.label(text="Instructions:")
        col.label(text="1) Make object active.")
        col.label(text="2) Plot A, B, C on its surface.")
        col.label(text="3) Repeat for others.")
        col.label(text="4) Select all, active = target.")
        col.label(text="5) Run Align To Active.")


def register():
    bpy.utils.register_class(SUPERTOOLS_PT_align_panel)


def unregister():
    bpy.utils.unregister_class(SUPERTOOLS_PT_align_panel)
