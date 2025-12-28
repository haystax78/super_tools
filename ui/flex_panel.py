"""
UI Panel for the Flex tool in Super Tools addon.
"""
import bpy
from ..utils.flex_state import FlexState


def get_prefs():
    """Get addon preferences."""
    try:
        addon_prefs = bpy.context.preferences.addons.get("super_tools")
        if addon_prefs:
            return addon_prefs.preferences
    except Exception:
        pass
    return None


class VIEW3D_PT_flex_panel(bpy.types.Panel):
    """Creates a Panel in the 3D View for Flex settings"""
    bl_label = "Flex Settings"
    bl_idname = "VIEW3D_PT_flex_tool"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Super Tools'
    bl_parent_id = 'SUPERTOOLS_PT_modeling_panel'
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout
        prefs = get_prefs()
        
        col = layout.column(align=True)
        col.label(text="Default Resolution:")
        if prefs:
            col.prop(prefs, "flex_default_resolution", text="Circumference")
            col.prop(prefs, "flex_default_segments", text="Length")
        
        col.separator()
        col.label(text="Radius Limits:")
        if prefs:
            col.prop(prefs, "flex_default_radius", text="Default Radius")
            col.prop(prefs, "flex_min_radius", text="Min Radius")
            col.prop(prefs, "flex_max_radius", text="Max Radius")
        
        col.separator()
        col.label(text="Behavior:")
        if prefs:
            col.prop(prefs, "flex_default_bspline_mode")
            col.prop(prefs, "flex_default_cap_type")
            col.prop(prefs, "flex_add_smooth_by_angle")
            row = col.row()
            row.enabled = getattr(prefs, 'flex_add_smooth_by_angle', False)
            row.prop(prefs, "flex_smooth_by_angle_value")


class VIEW3D_PT_flex_shortcuts(bpy.types.Panel):
    """Keyboard shortcuts subpanel"""
    bl_label = "Keyboard Shortcuts"
    bl_idname = "VIEW3D_PT_flex_shortcuts"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Super Tools'
    bl_parent_id = 'VIEW3D_PT_flex_tool'
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout
        prefs = get_prefs()
        col = layout.column(align=True)
        
        # Build switch mesh hotkey string from preferences
        key_switch = getattr(prefs, 'flex_key_switch_mesh', 'Q') if prefs else 'Q'
        switch_ctrl = getattr(prefs, 'flex_key_switch_mesh_ctrl', False) if prefs else False
        switch_alt = getattr(prefs, 'flex_key_switch_mesh_alt', True) if prefs else True
        switch_shift = getattr(prefs, 'flex_key_switch_mesh_shift', False) if prefs else False
        
        switch_combo = ""
        if switch_ctrl:
            switch_combo += "Ctrl+"
        if switch_alt:
            switch_combo += "Alt+"
        if switch_shift:
            switch_combo += "Shift+"
        switch_combo += key_switch
        
        col.label(text="LMB: Add/drag point")
        col.label(text="RMB: Delete point / Scale radius")
        col.label(text="Enter: Accept")
        col.label(text="Space: Accept & Continue")
        col.label(text=f"{switch_combo}: Switch to hovered flex")
        col.label(text="Escape: Cancel")
        col.separator()
        col.label(text="H: Toggle Help HUD")
        col.label(text="B: Toggle B-Spline mode")
        col.label(text="A: Toggle Adaptive")
        col.label(text="X: Toggle Mirror")
        col.label(text="S: Cycle Snapping")
        col.label(text="T (hold): Twist mode")
        col.label(text="G: Group move")
        col.label(text="R: Cycle roundness")
        col.label(text="Ctrl+Z: Undo")
        col.label(text="Ctrl+Shift+Z: Redo")


classes = (
    VIEW3D_PT_flex_panel,
    VIEW3D_PT_flex_shortcuts,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
