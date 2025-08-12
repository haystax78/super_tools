import bpy


class SuperExtrudePreferences(bpy.types.AddonPreferences):
    bl_idname = __package__
    
    def draw(self, context):
        layout = self.layout
        layout.label(text="Super Extrude addon has no user preferences.")


def register():
    bpy.utils.register_class(SuperExtrudePreferences)


def unregister():
    bpy.utils.unregister_class(SuperExtrudePreferences)
