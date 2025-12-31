bl_info = {
    "name": "Super Tools",
    "author": "MattGPT",
    "version": (1, 1, 1),
    "blender": (4, 5, 0),
    "location": "View3D > Edit Mode > Face Context Menu",
    "description": "Advanced mesh editing tools including Super Extrude and Super Orient operators",
    "warning": "",
    "doc_url": "",
    "category": "Mesh",
}

import bpy
import importlib

# List of modules to import
modules = [
    # Core
    "preferences",
    "keymaps",

    # Existing operators
    "operators.extrude_modal",
    "operators.orient_modal",

    # Super Align utils and operators
    "utils.align_points",
    "utils.align_raycast",
    "utils.align_similarity",
    "utils.align_icp",
    "utils.align_cpd",
    # Properties must be registered before UI draws
    "utils.align_props",
    "utils.align_locators",
    "operators.align_plot_points",
    "operators.align_delete_points",
    "operators.align_to_active",
    "operators.utilities_sequential_vis",
    "operators.align_icp_modal",
    "operators.align_cpd_modal",
    "ui.align_panel",

    # Flex Tool - curve-based mesh creation
    "utils.flex_state",
    "utils.flex_conversion",
    "utils.flex_math",
    "utils.flex_mesh",
    "operators.flex_drawing",
    "operators.flex_interaction_base",
    "operators.flex_interaction_points",
    "operators.flex_operator_base",
    "operators.flex_tool",
    "ui.flex_panel",
]

# Store imported modules for reload
imported_modules = {}


def register():
    # Import and register modules
    for module_name in modules:
        # Import module
        full_name = f"{__name__}.{module_name}"
        if full_name in imported_modules:
            importlib.reload(imported_modules[full_name])
            module = imported_modules[full_name]
        else:
            module = __import__(full_name, fromlist=["*"])
            imported_modules[full_name] = module
        
        # Register if module has register function
        if hasattr(module, "register"):
            module.register()


def unregister():
    # Unregister modules in reverse order
    for module_name in reversed(modules):
        full_name = f"{__name__}.{module_name}"
        if full_name in imported_modules:
            module = imported_modules[full_name]
            if hasattr(module, "unregister"):
                module.unregister()


if __name__ == "__main__":
    register()
