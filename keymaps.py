import bpy


def draw_extrude_menu(self, context):
    """Add our operators to the extrude menu"""
    self.layout.separator()
    # Modal operators need to be invoked properly from menus
    self.layout.operator_context = 'INVOKE_DEFAULT'
    self.layout.operator("mesh.super_extrude_modal", text="Super Extrude")
    self.layout.operator("mesh.super_orient_modal", text="Super Orient")


def register():
    # Add to the Alt+E extrude menu
    bpy.types.VIEW3D_MT_edit_mesh_extrude.append(draw_extrude_menu)


def unregister():
    # Remove from extrude menu
    try:
        bpy.types.VIEW3D_MT_edit_mesh_extrude.remove(draw_extrude_menu)
    except (AttributeError, ValueError):
        pass
