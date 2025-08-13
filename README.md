# Super Tools Addon

A Blender addon that provides advanced mesh editing tools for enhanced modeling workflows.

## Features

- **Super Extrude**: Modal extrude operator with automatic orientation and intuitive mouse controls
- **Super Orient**: Proportional editing tool for reorienting face selections with topology-aware falloff
- **Spatial Relationship Logic**: Maintains consistent orientation behavior across all tools
- **Proportional Editing Integration**: Seamless integration with Blender's proportional editing settings
 - **Auto-Updater**: Optionally checks and installs updates from GitHub on startup
 - **Performance-Optimized Falloff**: KDTree + NumPy powered proportional weights with connected-only support

## Installation

1. Download or clone this repository
2. In Blender, go to `Edit > Preferences > Add-ons`
3. Click `Install` and select the `super_tools.zip` file or the `super_tools` folder
4. Enable the addon by checking the checkbox

## Usage

### Super Extrude
1. Select one or more faces in Edit Mode
2. Press `Alt+E` to open the extrude menu and select "Super Extrude"
3. Move your mouse to translate the extruded faces (they automatically rotate to face away from the selection center)
4. Left-click or press Enter to confirm the operation

### Super Orient
1. Select one or more faces in Edit Mode
2. Press `Alt+E` to open the extrude menu and select "Super Orient"
3. Optionally enable proportional editing (`O` key) for falloff-based orientation affecting nearby geometry
4. Move your mouse to reorient faces while maintaining spatial relationships with the pivot point
5. Use `X`, `Y`, `Z` keys to constrain movement to specific axes
6. Use mouse wheel or square brackets to adjust proportional editing radius (when proportional editing is enabled)
7. Left-click or press Enter to confirm the operation
8. Right-click or press Escape to cancel the operation


## Requirements

- Blender 4.3 or later

## Changelog

### v0.0.2
- Pass-through for modifier keys (Shift/Ctrl/Alt) during modals, enabling normal viewport navigation combos.
- Super Orient: Shift+O quick proportional menu now syncs live with the modal (enable/disable, radius, falloff, connected).
- 'O' key toggles proportional editing on and off during Super Orient modal.
- Falloff curves assigned to 1-7 keys during Super Orient modal in proportional editing mode.

### v0.0.3
- Added auto-updater to check for updates and notify the user if a new version is available. Optional auto-install toggle in Preferences.
- Super Orient proportional editing:
  - Scale-aware world-space KDTree queries and distances (robust under object scale).
  - Border-anchored falloff: distances measured from nearest selected vertex; selected verts keep full weight.
  - Corrected falloff curves across all modes to strictly satisfy w(0)=1 and w(1)=0 (including Inverse Square).
  - Major performance improvements: vectorized batched nearest-seed distances, per-frame caches, single expanded KD query for large selections, and precomputed connected components for Connected Only.
  - Stable interaction: changing falloff radius preserves current mouse-applied transform for smooth UX.
  - Consistent visualization: falloff circle drawn as a world-space ring on the view plane for accurate radius regardless of camera direction.
