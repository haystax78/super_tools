bl_info = {
    "name": "Super Tools",
    "author": "MattGPT",
    "version": (0, 0, 1),
    "blender": (4, 3, 0),
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
    "preferences",
    "keymaps",
    "operators.extrude_modal",
    "operators.orient_modal",
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
