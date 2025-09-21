# Super Tools Addon

A Blender addon that provides advanced mesh editing tools for enhanced modeling workflows.

## Features

- **Super Extrude**: Modal extrude operator with automatic orientation and intuitive mouse controls
- **Super Orient**: Proportional editing tool for reorienting face selections with topology-aware falloff
- **Super Align**: Align mesh objects by matching three surface points (A, B, C); includes tools to plot/delete A/B/C locators, align to active target, iterative ICP alignment, and sequential visibility utility.
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

### v0.0.8
- Super Tools UI
  - Panel title now shows the version inline (e.g., "Super Tools v0.0.8"), left-aligned with no header gap.
  - Reorganized UI into collapsible sub-panels under Super Tools:
    - Modeling: Super Extrude, Super Orient
    - Super Align: alignment tools; collapsed by default
- Iterative Alignment
  - Added CPD Align modal operator (`super_tools.cpd_align_modal`) implementing rigid/similarity Coherent Point Drift in pure NumPy.
  - Removed proportional editing controls/overlays; operation focuses on spatial-relationship driven movement/orientation.
- Version bumped to 0.0.8.

### v0.0.7
- Added ICP Align modal operator (`super_tools.icp_align_modal`) that iteratively aligns selected meshes to the active target until ESC. Includes robust sampling, KD-tree nearest neighbors, outlier rejection, and rigid Kabsch transform per iteration. UI button added under Super Align panel.

### v0.0.6
- Added Super Align tools for aligning arbitrary mesh objects by matching three surface points (A, B, C). Extremely useful for aligning scans.
- Version bumped to 0.0.6.

### v0.0.5
- Precision Movement: Added reusable precision mouse handling (`utils/input_utils.PrecisionMouseState`). Holding Shift slows mouse-driven transforms without jumps in both Super Orient and Super Extrude modals. Default scale set to 0.3.
- Super Orient Falloff Visualization: Falloff circle now centers on the selection border centroid (unselected verts adjacent to selected), matching border-based falloff measurement for accurate low-radius behavior.
- Refactors: Reduced duplication by centralizing precision handling; groundwork laid for further modularization of proportional overlay calls.

### v0.0.4
- Super Orient: Added twist control driven by Shift + Mouse Wheel or Shift + [ / ] to rotate selection around the pivot-direction axis.
- Fixed twist axis under object transforms by composing twist in world space and converting with rotation-only matrices to avoid scale skew.
- Corrected Sharp falloff curve to match Blender's native implementation using cubic (1-t)³ instead of quadratic curve.
- Major codebase refactoring: consolidated all falloff calculations into unified `utils/falloff_utils.py` module for consistency and maintainability.
- Fixed RANDOM falloff type implementation to match Blender's linear+random method (was falling back to smooth).
- Added RANDOM falloff to key 8 mapping in Super Orient modal for complete falloff control.
- Eliminated duplicate falloff code across multiple files, ensuring single source of truth for all proportional editing curves.
- Minor robustness improvements to spatial relationship rotation and proportional application.

### v0.0.3
- Added auto-updater to check for updates and notify the user if a new version is available. Optional auto-install toggle in Preferences.
- Super Orient proportional editing:
- Scale-aware world-space KDTree queries and distances (robust under object scale).
- Border-anchored falloff: distances measured from nearest selected vertex; selected verts keep full weight.
- Corrected falloff curves across all modes to strictly satisfy w(0)=1 and w(1)=0 (including Inverse Square).
- Major performance improvements: vectorized batched nearest-seed distances, per-frame caches, single expanded KD query for large selections, and precomputed connected components for Connected Only.
- Stable interaction: changing falloff radius preserves current mouse-applied transform for smooth UX.
- Consistent visualization: falloff circle drawn as a world-space ring on the view plane for accurate radius regardless of camera direction.

### v0.0.2
- Pass-through for modifier keys (Shift/Ctrl/Alt) during modals, enabling normal viewport navigation combos.
- Super Orient: Shift+O quick proportional menu now syncs live with the modal (enable/disable, radius, falloff, connected).
- 'O' key toggles proportional editing on and off during Super Orient modal.
- Falloff curves assigned to 1-7 keys during Super Orient modal in proportional editing mode.