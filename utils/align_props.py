import bpy

def register_scene_properties():
    from bpy.props import StringProperty, BoolProperty
    if not hasattr(bpy.types.Scene, "superalign_icp_target_group"):
        setattr(
            bpy.types.Scene,
            "superalign_icp_target_group",
            StringProperty(
                name="ICP Target Group",
                description="Vertex group on active (target) mesh used to limit ICP target points",
                default="",
            ),
        )
    if not hasattr(bpy.types.Scene, "superalign_icp_allow_scale"):
        setattr(
            bpy.types.Scene,
            "superalign_icp_allow_scale",
            BoolProperty(
                name="Allow Scale",
                description="Allow ICP to apply uniform scale in addition to rotation and translation",
                default=False,
            ),
        )


def unregister_scene_properties():
    if hasattr(bpy.types.Scene, "superalign_icp_target_group"):
        delattr(bpy.types.Scene, "superalign_icp_target_group")
    if hasattr(bpy.types.Scene, "superalign_icp_allow_scale"):
        delattr(bpy.types.Scene, "superalign_icp_allow_scale")


def register():
    register_scene_properties()


def unregister():
    unregister_scene_properties()
