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


class SuperToolsPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

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

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        col.prop(self, "auto_check")
        col.prop(self, "auto_update")
        row = col.row()
        row.operator("super_tools.check_update", icon='FILE_REFRESH')
        row2 = col.row()
        row2.enabled = self.update_available
        row2.operator("super_tools.perform_update", icon='IMPORT')
        if self.update_status:
            col.label(text=self.update_status)


classes = (
    SUPERTOOLS_OT_check_update,
    SUPERTOOLS_OT_perform_update,
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
