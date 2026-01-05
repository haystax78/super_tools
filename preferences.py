import bpy
import os
import re
import shutil
import zipfile
import tempfile
import importlib
import json
import base64
from urllib import request, error

import rna_keymap_ui


REPO_RAW_INIT_URL = "https://raw.githubusercontent.com/haystax78/super_tools/main/super_tools/__init__.py"
REPO_ZIP_URL = "https://codeload.github.com/haystax78/super_tools/zip/refs/heads/main"


def _get_local_version_tuple():
    try:
        # __package__ equals top-level package name 'super_tools'
        mod = importlib.import_module(__package__)
        bl_info = getattr(mod, 'bl_info', None)
        if bl_info and 'version' in bl_info:
            return tuple(bl_info['version'])
    except Exception:
        pass
    return (0, 0, 0)


def _parse_version_from_text(text):
    # Expect a line like: "version": (0, 0, 2),
    m = re.search(r"version\"\s*:\s*\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)\)", text)
    if not m:
        return None
    return tuple(map(int, m.groups()))


def _http_get(url, timeout=10):
    req = request.Request(url, headers={
        'User-Agent': 'super_tools_updater/1.0 (+https://github.com/haystax78/super_tools)'
    })
    return request.urlopen(req, timeout=timeout)


def _get_remote_version_tuple():
    # 1) Try raw file URL
    try:
        with _http_get(REPO_RAW_INIT_URL, timeout=10) as resp:
            data = resp.read().decode('utf-8', errors='ignore')
            vt = _parse_version_from_text(data)
            if vt:
                return vt
    except Exception:
        pass

    # 2) Try GitHub contents API
    try:
        contents_api = "https://api.github.com/repos/haystax78/super_tools/contents/super_tools/__init__.py?ref=main"
        with _http_get(contents_api, timeout=10) as resp:
            js = json.loads(resp.read().decode('utf-8', errors='ignore'))
            if isinstance(js, dict) and 'content' in js:
                raw = base64.b64decode(js['content']).decode('utf-8', errors='ignore')
                vt = _parse_version_from_text(raw)
                if vt:
                    return vt
    except Exception:
        pass

    # 3) Fallback to tags (expects names like v0.0.3)
    try:
        tags_api = "https://api.github.com/repos/haystax78/super_tools/tags"
        with _http_get(tags_api, timeout=10) as resp:
            arr = json.loads(resp.read().decode('utf-8', errors='ignore'))
            if isinstance(arr, list) and arr:
                name = arr[0].get('name', '')
                m = re.match(r"v(\d+)\.(\d+)\.(\d+)$", name)
                if m:
                    return tuple(map(int, m.groups()))
    except Exception:
        pass

    return None


def _download_and_extract_zip(dest_dir):
    # dest_dir should be the current addon directory (this file's parent)
    tmpdir = tempfile.mkdtemp(prefix="super_tools_upd_")
    zippath = os.path.join(tmpdir, "repo.zip")
    try:
        # Download ZIP
        with request.urlopen(REPO_ZIP_URL, timeout=30) as resp, open(zippath, 'wb') as f:
            shutil.copyfileobj(resp, f)

        # Extract ZIP
        with zipfile.ZipFile(zippath, 'r') as zf:
            zf.extractall(tmpdir)

        # Find extracted inner folder: typically 'super_tools-main/super_tools'
        inner_root = None
        for name in os.listdir(tmpdir):
            if name.startswith('super_tools-') and os.path.isdir(os.path.join(tmpdir, name)):
                inner_root = os.path.join(tmpdir, name)
                break
        if not inner_root:
            raise RuntimeError("Could not locate extracted repository folder")

        src_addon_dir = os.path.join(inner_root, 'super_tools')
        if not os.path.isdir(src_addon_dir):
            # Fallback: repo root directly contains files
            src_addon_dir = inner_root

        # Copy files over existing addon dir (non-destructive: will overwrite existing files but not remove stale ones)
        for root, dirs, files in os.walk(src_addon_dir):
            rel = os.path.relpath(root, src_addon_dir)
            target_root = os.path.join(dest_dir, rel) if rel != '.' else dest_dir
            os.makedirs(target_root, exist_ok=True)
            for d in dirs:
                os.makedirs(os.path.join(target_root, d), exist_ok=True)
            for fname in files:
                shutil.copy2(os.path.join(root, fname), os.path.join(target_root, fname))
        return True, "Update applied."
    except Exception as e:
        return False, f"Update failed: {e}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _auto_update_timer():
    """Timer callback to auto-check (and optionally auto-install) updates on startup."""
    try:
        addon = bpy.context.preferences.addons.get(__package__)
        if not addon:
            return None
        prefs = addon.preferences
        if not getattr(prefs, 'auto_check', False):
            return None
        local_v = _get_local_version_tuple()
        remote_v = _get_remote_version_tuple()
        if not remote_v:
            prefs.update_status = "Auto-check: unable to fetch remote version."
            return None
        if remote_v > local_v:
            prefs.update_available = True
            prefs.update_status = f"Auto-check: update available {local_v} -> {remote_v}"
            if getattr(prefs, 'auto_update', False):
                ok, msg = _download_and_extract_zip(os.path.dirname(__file__))
                prefs.update_status = (msg or "") + " (auto)"
        else:
            prefs.update_available = False
            prefs.update_status = f"Auto-check: up to date ({local_v})"
    except Exception:
        # Avoid throwing in timer
        pass
    return None


class SUPERTOOLS_OT_check_update(bpy.types.Operator):
    bl_idname = "super_tools.check_update"
    bl_label = "Check for Update"
    bl_description = "Check GitHub for a newer version"

    def execute(self, context):
        prefs = context.preferences.addons.get(__package__).preferences
        local_v = _get_local_version_tuple()
        remote_v = _get_remote_version_tuple()
        if not remote_v:
            prefs.update_status = "Unable to fetch remote version."
            self.report({'WARNING'}, prefs.update_status)
            return {'CANCELLED'}
        if remote_v > local_v:
            prefs.update_available = True
            prefs.update_status = f"Update available: {local_v} -> {remote_v}"
            self.report({'INFO'}, prefs.update_status)
        else:
            prefs.update_available = False
            prefs.update_status = f"Up to date (local {local_v}, remote {remote_v})"
            self.report({'INFO'}, prefs.update_status)
        return {'FINISHED'}


class SUPERTOOLS_OT_perform_update(bpy.types.Operator):
    bl_idname = "super_tools.perform_update"
    bl_label = "Download and Install Update"
    bl_description = "Download latest from GitHub and install over this add-on"

    def execute(self, context):
        prefs = context.preferences.addons.get(__package__).preferences
        addon_dir = os.path.dirname(__file__)
        ok, msg = _download_and_extract_zip(addon_dir)
        prefs.update_status = msg
        if ok:
            # Try reloading the package to reflect changes without restart
            try:
                mod = importlib.import_module(__package__)
                importlib.reload(mod)
            except Exception:
                pass
            self.report({'INFO'}, msg + " You may need to restart Blender.")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}


class SUPERTOOLS_OT_restore_flex_hotkey_defaults(bpy.types.Operator):
    bl_idname = "super_tools.restore_flex_hotkey_defaults"
    bl_label = "Restore Defaults"
    bl_description = "Restore flex hotkey to default (Alt+Q)"

    def execute(self, context):
        prefs = context.preferences.addons.get(__package__).preferences
        prefs.flex_key_switch_mesh = "Q"
        prefs.flex_key_switch_mesh_alt = True
        prefs.flex_key_switch_mesh_ctrl = False
        prefs.flex_key_switch_mesh_shift = False
        self.report({'INFO'}, "Flex hotkey restored to Alt+Q")
        return {'FINISHED'}


class SUPERTOOLS_OT_add_super_duplicate_shortcut(bpy.types.Operator):
    bl_idname = "super_tools.add_super_duplicate_shortcut"
    bl_label = "Add Shortcut"
    bl_description = "Create a keymap entry so it can be edited here"

    duplicate: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        try:
            from . import keymaps
        except Exception:
            return {'CANCELLED'}

        wm = context.window_manager
        kc = wm.keyconfigs.user
        if not kc:
            return {'CANCELLED'}

        km, existing_kmi = keymaps.find_super_duplicate_kmi(
            kc,
            duplicate_value=self.duplicate,
            keymap_name='Sculpt',
        )
        if not km or existing_kmi:
            return {'FINISHED'}

        kmi = km.keymap_items.new(
            'sculpt.super_duplicate',
            type='NONE',
            value='PRESS',
        )
        kmi.properties.duplicate = self.duplicate
        return {'FINISHED'}


class SuperToolsPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    def _refresh_super_keymaps(self, context):
        try:
            from . import keymaps
            keymaps.migrate_super_duplicate_hotkeys_from_prefs()
        except Exception:
            pass

    auto_check: bpy.props.BoolProperty(
        name="Auto-check for updates on startup",
        default=False,
        description="Check GitHub for updates when Blender starts"
    )
    auto_update: bpy.props.BoolProperty(
        name="Auto-install updates",
        default=False,
        description="If enabled, automatically download and install when a newer version is available"
    )
    update_available: bpy.props.BoolProperty(default=False)
    update_status: bpy.props.StringProperty(name="Status", default="")
    
    # Flex Tool Settings
    flex_default_resolution: bpy.props.IntProperty(
        name="Default Resolution",
        description="Default circumference resolution for new flex meshes",
        default=16,
        min=4,
        max=64
    )
    flex_default_segments: bpy.props.IntProperty(
        name="Default Segments",
        description="Default length segments for new flex meshes",
        default=32,
        min=8,
        max=128
    )
    flex_default_radius: bpy.props.FloatProperty(
        name="Default Radius",
        description="Default radius for new control points",
        default=0.5,
        min=0.01,
        max=10.0
    )
    flex_min_radius: bpy.props.FloatProperty(
        name="Minimum Radius",
        description="Minimum allowed radius for control points",
        default=0.05,
        min=0.0,
        max=5.0,
        precision=4
    )
    flex_max_radius: bpy.props.FloatProperty(
        name="Maximum Radius",
        description="Maximum allowed radius for control points",
        default=10.0,
        min=0.1,
        max=100.0
    )
    flex_default_bspline_mode: bpy.props.BoolProperty(
        name="B-spline Mode (Default)",
        description="Use B-spline curve mode by default when creating/editing",
        default=True
    )
    flex_default_cap_type: bpy.props.EnumProperty(
        name="Default Cap Type",
        description="Default cap type for new flex meshes",
        items=[
            ('NONE', "None", "No caps"),
            ('HEMISPHERE', "Hemisphere", "Rounded hemisphere caps"),
            ('PLANAR', "Planar", "Flat planar caps"),
        ],
        default='HEMISPHERE'
    )
    flex_add_smooth_by_angle: bpy.props.BoolProperty(
        name="Add Smooth by Angle",
        description="Add Smooth by Angle modifier to new flex meshes",
        default=False
    )
    flex_smooth_by_angle_value: bpy.props.FloatProperty(
        name="Smooth Angle",
        description="Angle threshold for Smooth by Angle modifier",
        default=0.523599,  # 30 degrees in radians
        min=0.0,
        max=3.14159,  # 180 degrees in radians
        subtype='ANGLE'
    )
    
    # Flex Hotkeys - Switch Mesh with full modifier support
    flex_key_switch_mesh: bpy.props.StringProperty(
        name="Key", 
        default="Q", 
        description="Key for switch to hovered flex mesh"
    )
    flex_key_switch_mesh_alt: bpy.props.BoolProperty(
        name="Alt",
        default=True,
        description="Require Alt modifier"
    )
    flex_key_switch_mesh_ctrl: bpy.props.BoolProperty(
        name="Ctrl",
        default=False,
        description="Require Ctrl modifier"
    )
    flex_key_switch_mesh_shift: bpy.props.BoolProperty(
        name="Shift",
        default=False,
        description="Require Shift modifier"
    )

    # Super Duplicate Hotkey - configurable but not bound by default
    super_duplicate_key: bpy.props.StringProperty(
        name="Key",
        default="",
        description="Key for Super Duplicate (leave empty for no hotkey)",
    )
    super_duplicate_alt: bpy.props.BoolProperty(
        name="Alt",
        default=False,
        description="Require Alt modifier",
    )
    super_duplicate_ctrl: bpy.props.BoolProperty(
        name="Ctrl",
        default=False,
        description="Require Ctrl modifier",
    )
    super_duplicate_shift: bpy.props.BoolProperty(
        name="Shift",
        default=False,
        description="Require Shift modifier",
    )
    
    # Super Transform Hotkey
    super_transform_key: bpy.props.StringProperty(
        name="Key",
        default="",
        description="Key for Super Transform (leave empty for no hotkey)",
    )
    super_transform_alt: bpy.props.BoolProperty(
        name="Alt",
        default=False,
        description="Require Alt modifier",
    )
    super_transform_ctrl: bpy.props.BoolProperty(
        name="Ctrl",
        default=False,
        description="Require Ctrl modifier",
    )
    super_transform_shift: bpy.props.BoolProperty(
        name="Shift",
        default=False,
        description="Require Shift modifier",
    )

    super_duplicate_keymap_migrated: bpy.props.BoolProperty(
        default=False,
        options={'HIDDEN'}
    )
    
    # Super Duplicate Modal Keys
    sd_key_move: bpy.props.StringProperty(
        name="Move",
        default="G",
        description="Key for move mode"
    )
    sd_key_rotate: bpy.props.StringProperty(
        name="Rotate",
        default="R",
        description="Key for rotate mode (hold)"
    )
    sd_key_scale: bpy.props.StringProperty(
        name="Scale",
        default="S",
        description="Key for scale mode (hold)"
    )
    sd_key_adjust_center: bpy.props.StringProperty(
        name="Adjust Center",
        default="SPACE",
        description="Key for adjusting transform center (hold)"
    )

    def draw(self, context):
        layout = self.layout
        
        # Update section
        box = layout.box()
        box.label(text="Updates", icon='FILE_REFRESH')
        col = box.column()
        col.prop(self, "auto_check")
        col.prop(self, "auto_update")
        row = col.row()
        row.operator("super_tools.check_update", icon='FILE_REFRESH')
        row2 = col.row()
        row2.enabled = self.update_available
        row2.operator("super_tools.perform_update", icon='IMPORT')
        if self.update_status:
            col.label(text=self.update_status)
        
        # Flex Tool Settings
        box = layout.box()
        box.label(text="Flex Tool Settings", icon='CURVE_DATA')
        
        col = box.column(align=True)
        col.label(text="Default Resolution:")
        col.prop(self, "flex_default_resolution", text="Circumference")
        col.prop(self, "flex_default_segments", text="Length")
        
        col.separator()
        col.label(text="Radius Limits:")
        col.prop(self, "flex_default_radius", text="Default Radius")
        col.prop(self, "flex_min_radius", text="Min Radius")
        col.prop(self, "flex_max_radius", text="Max Radius")
        
        col.separator()
        col.label(text="Behavior:")
        col.prop(self, "flex_default_bspline_mode")
        col.prop(self, "flex_default_cap_type")
        col.prop(self, "flex_add_smooth_by_angle")
        row = col.row()
        row.enabled = self.flex_add_smooth_by_angle
        row.prop(self, "flex_smooth_by_angle_value")
        
        # Flex Hotkeys
        box = layout.box()
        box.label(text="Flex Tool Hotkeys", icon='KEYINGSET')
        col = box.column(align=True)
        col.label(text="Switch to Hovered Flex Mesh:")
        row = col.row(align=True)
        row.prop(self, "flex_key_switch_mesh_ctrl", toggle=True)
        row.prop(self, "flex_key_switch_mesh_alt", toggle=True)
        row.prop(self, "flex_key_switch_mesh_shift", toggle=True)
        row.prop(self, "flex_key_switch_mesh", text="")
        col.separator()
        col.operator("super_tools.restore_flex_hotkey_defaults", icon='LOOP_BACK')
        
        # Super Duplicate/Transform Hotkeys
        box = layout.box()
        box.label(text="Super Duplicate/Transform Hotkeys", icon='KEYINGSET')
        col = box.column(align=True)

        wm = context.window_manager
        kc = wm.keyconfigs.user
        if not kc:
            col.label(text="No user keyconfig available")
        else:
            try:
                from . import keymaps
            except Exception:
                keymaps = None

            def _draw_sd_kmi(label, duplicate_value):
                sub = col.column(align=True)
                sub.label(text=label)
                if not keymaps:
                    sub.label(text="Keymap unavailable")
                    return

                km, kmi = keymaps.find_super_duplicate_kmi(
                    kc,
                    duplicate_value=duplicate_value,
                    keymap_name='Sculpt',
                )
                if not km:
                    sub.label(text="Sculpt keymap not found")
                    return
                if not kmi:
                    row = sub.row(align=True)
                    op = row.operator(
                        "super_tools.add_super_duplicate_shortcut",
                        text="Add Shortcut",
                        icon='ADD',
                    )
                    op.duplicate = duplicate_value
                    sub.label(text="Tip: you can also right-click the UI button and choose Assign Shortcut")
                    return

                rna_keymap_ui.draw_kmi(
                    [],
                    kc,
                    km,
                    kmi,
                    sub,
                    0,
                )

            _draw_sd_kmi("Super Duplicate:", True)
            col.separator()
            _draw_sd_kmi("Super Transform:", False)
        
        col.separator()
        col.label(text="Modal Keys:")
        row = col.row(align=True)
        row.prop(self, "sd_key_move", text="Move")
        row.prop(self, "sd_key_rotate", text="Rotate")
        row.prop(self, "sd_key_scale", text="Scale")
        row = col.row(align=True)
        row.prop(self, "sd_key_adjust_center", text="Center")


classes = (
    SUPERTOOLS_OT_check_update,
    SUPERTOOLS_OT_perform_update,
    SUPERTOOLS_OT_restore_flex_hotkey_defaults,
    SUPERTOOLS_OT_add_super_duplicate_shortcut,
    SuperToolsPreferences,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    # Register timer to run shortly after startup
    try:
        bpy.app.timers.register(_auto_update_timer, first_interval=3.0)
    except Exception:
        pass


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
