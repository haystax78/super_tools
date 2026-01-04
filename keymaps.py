import bpy

addon_keymaps = []


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
    """Register keymaps for Super Duplicate/Transform based on preferences."""
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
    bpy.app.timers.register(register_super_duplicate_keymaps, first_interval=0.1)


def unregister():
    # Remove from extrude menu
    try:
        bpy.types.VIEW3D_MT_edit_mesh_extrude.remove(draw_extrude_menu)
    except (AttributeError, ValueError):
        pass
    
    # Unregister Super Duplicate/Transform keymaps
    unregister_super_duplicate_keymaps()
