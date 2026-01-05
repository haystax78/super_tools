import bpy

addon_keymaps = []


def _get_keymap(kc, name, space_type='EMPTY'):
    if not kc:
        return None
    km = kc.keymaps.get(name)
    if km:
        return km
    return kc.keymaps.new(name=name, space_type=space_type)


def _get_kmi_duplicate_value(kmi):
    try:
        return bool(kmi.properties.duplicate)
    except Exception:
        return None


def find_super_duplicate_kmi(kc, duplicate_value, keymap_name='Sculpt'):
    km = _get_keymap(kc, keymap_name)
    if not km:
        return None, None

    for kmi in km.keymap_items:
        if kmi.idname != 'sculpt.super_duplicate':
            continue
        if _get_kmi_duplicate_value(kmi) != duplicate_value:
            continue
        return km, kmi

    return km, None


def get_addon_prefs():
    """Get addon preferences."""
    addon = bpy.context.preferences.addons.get(__package__)
    if addon:
        return addon.preferences
    return None


def draw_extrude_menu(self, context):
    """Add our operators to the extrude menu"""
    self.layout.separator()
    # Modal operators need to be invoked properly from menus
    self.layout.operator_context = 'INVOKE_DEFAULT'
    self.layout.operator("mesh.super_extrude_modal", text="Super Extrude")
    self.layout.operator("mesh.super_orient_modal", text="Super Orient")


def register_super_duplicate_keymaps():
    """Legacy: Register keymaps for Super Duplicate/Transform.

    This is kept for backward compatibility but no longer drives the prefs UI.
    Users can (and should) bind shortcuts via Blender's keymap system.
    """
    global addon_keymaps
    
    # Unregister existing keymaps first
    unregister_super_duplicate_keymaps()
    
    prefs = get_addon_prefs()
    if not prefs:
        return
    
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if not kc:
        return
    
    # Register in Sculpt mode
    km = kc.keymaps.new(name='Sculpt', space_type='EMPTY')
    
    # Super Duplicate hotkey
    if prefs.super_duplicate_key:
        kmi = km.keymap_items.new(
            'sculpt.super_duplicate',
            type=prefs.super_duplicate_key.upper(),
            value='PRESS',
            alt=prefs.super_duplicate_alt,
            ctrl=prefs.super_duplicate_ctrl,
            shift=prefs.super_duplicate_shift
        )
        kmi.properties.duplicate = True
        addon_keymaps.append((km, kmi))
    
    # Super Transform hotkey
    if prefs.super_transform_key:
        kmi = km.keymap_items.new(
            'sculpt.super_duplicate',
            type=prefs.super_transform_key.upper(),
            value='PRESS',
            alt=prefs.super_transform_alt,
            ctrl=prefs.super_transform_ctrl,
            shift=prefs.super_transform_shift
        )
        kmi.properties.duplicate = False
        addon_keymaps.append((km, kmi))


def migrate_super_duplicate_hotkeys_from_prefs():
    """One-time migration from legacy prefs hotkeys to user keymap."""
    prefs = get_addon_prefs()
    if not prefs:
        return

    if getattr(prefs, 'super_duplicate_keymap_migrated', False):
        return

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.user
    if not kc:
        return

    def _migrate_one(
        key,
        ctrl,
        alt,
        shift,
        duplicate_value,
    ):
        if not key:
            return
        km, existing_kmi = find_super_duplicate_kmi(
            kc,
            duplicate_value=duplicate_value,
            keymap_name='Sculpt',
        )
        if existing_kmi:
            return

        if not km:
            return

        kmi = km.keymap_items.new(
            'sculpt.super_duplicate',
            type=key.upper(),
            value='PRESS',
            alt=alt,
            ctrl=ctrl,
            shift=shift,
        )
        kmi.properties.duplicate = duplicate_value

    _migrate_one(
        prefs.super_duplicate_key,
        prefs.super_duplicate_ctrl,
        prefs.super_duplicate_alt,
        prefs.super_duplicate_shift,
        True,
    )
    _migrate_one(
        prefs.super_transform_key,
        prefs.super_transform_ctrl,
        prefs.super_transform_alt,
        prefs.super_transform_shift,
        False,
    )

    prefs.super_duplicate_keymap_migrated = True


def unregister_super_duplicate_keymaps():
    """Unregister Super Duplicate/Transform keymaps."""
    global addon_keymaps
    
    for km, kmi in addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except:
            pass
    addon_keymaps.clear()


def register():
    # Add to the Alt+E extrude menu
    bpy.types.VIEW3D_MT_edit_mesh_extrude.append(draw_extrude_menu)
    
    # Register Super Duplicate/Transform keymaps
    # Use a timer to ensure preferences are available
    bpy.app.timers.register(migrate_super_duplicate_hotkeys_from_prefs, first_interval=0.1)


def unregister():
    # Remove from extrude menu
    try:
        bpy.types.VIEW3D_MT_edit_mesh_extrude.remove(draw_extrude_menu)
    except (AttributeError, ValueError):
        pass
    
    # Unregister Super Duplicate/Transform keymaps
    unregister_super_duplicate_keymaps()
