# Super Tools Addon

A Blender addon that provides advanced mesh editing tools for enhanced modeling workflows.

## What's New in v1.2.0

- **Super Duplicate & Super Transform**: New modal operators for transforming sculpt objects
  - Duplicate or transform existing sculpt objects while preserving editability
  - Visual transform center (white circle) that can be repositioned with Space key
  - Modal hotkeys: Move (G), Rotate (R), Scale (S), Mirror axes (X/Y/Z)
  - Sticky R/S keys: Hold to activate, release to return to move mode
  - Flex mesh support: Transforms object instead of vertices to maintain editability
  - Configurable hotkeys in addon preferences (invoke and modal keys)
  - Mirror modifier support with "SD Mirror" modifier and "sd_mirror_empty" object
- **Flex Tool Enhancements**:
  - Available directly from Sculpt mode
  - Automatically edits existing flex meshes when invoked from Sculpt mode
  - Proper mode restoration (returns to Sculpt mode after operation)
- **Bug fixes**:
  - Fixed Flex tool not returning to Sculpt mode after completion/cancellation
  - Improved mode switching and restoration across all operators

## What's New in v1.2.1

- **Super Duplicate & Super Transform performance and UX**:
  - Modal transforms now use object transforms for smoother interaction and bake to mesh on confirm
  - Fixed transform center behavior for parented objects
  - Added world axis constraints for move/rotate/scale (X/Y/Z)
  - Mirror hotkeys are now Alt+X / Alt+Y / Alt+Z
  - Super Duplicate / Super Transform invoke hotkeys now update immediately when changed in preferences

## What's New in v1.1.0

- **Flex Tool Profile Symmetry Mode**: Draw symmetric custom profiles with the X key
  - Symmetry state saved per profile slot and restored when editing
  - Disabling symmetry realizes mirrored points as real editable points
- **Profile Drawing Improvements**:
  - Rotation disabled during profile drawing to prevent symmetry conflicts
- **Bug fixes**:
  - Prevent re-invoking flex_create while modal is already running
  - Fixed points being unselectable if too close to the active point's radius boundary.

## What's New in v1.0.0

- **Flex Tool**: A powerful curve-based mesh creation tool for sculpting organic shapes like muscles, stylized hair, limbs and more.
  - Draw control points to define a B-spline curve with adjustable radii
  - Multiple profile types: Circular, Square, Rounded Square, and up to 6 custom drawable profiles
  - Custom profile drawing mode with transform controls (Scale, Rotate, Move)
  - Profile persistence across Blender sessions
  - Hemisphere and planar end caps
  - Mirror mode, adaptive segmentation, and twist controls
  - Edit existing flex meshes with Alt+Q switching
  - Configurable hotkeys and default settings in addon preferences

## Features

- **Flex Tool**: Curve-based mesh creation for organic shapes with customizable profiles, caps, and real-time preview
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

### Flex Tool
1. In Object Mode, click "Flex Create" in the Super Tools > Modeling panel (or press the assigned hotkey)
2. **LMB** to add control points along a curve path
3. **RMB drag** to adjust the radius uniformly across the whole curve, RMB + Mouse wheel to ramp the radius along the curve, RMB + MMB to equalize the radius of the whole curve.
4. Use number keys to change profile type:
   - `1` Circular, `2` Square, `3` Rounded Square
   - `4-9` Custom profiles (Alt+key to draw/edit)
5. Press `C` to toggle end caps, `B` for B-spline mode, `X` for mirror
6. Hold `T` and RMB drag to add twist uniformly along the curve, LMB to add twist incrementally along the curve, Click MMB to reset twist
7. Press **Enter** to accept, **Space** to accept and continue, **Esc** to cancel
8. To edit an existing flex mesh, select it and click "Reflex Mesh" or hover and press **Alt+Q** if already in the Flex Tool modal.

### Super Extrude
1. Select one or more faces in Edit Mode
2. Press `Alt+E` to open the extrude menu and select "Super Extrude"
3. Move your mouse to translate the extruded faces (they automatically rotate to face away from the selection center)
4. Left-click or press Enter to confirm the operation

### Super Duplicate & Super Transform
1. In Sculpt mode, select a mesh object
2. Use the configured hotkey (set in Preferences) or click "Super Duplicate"/"Super Transform" in the Super Tools > Sculpt panel
3. **Move mode** (default): Drag to move the object
4. Hold **R** to rotate around the white transform center, release to return to move
5. Hold **S** to scale around the transform center, release to return to move
6. Hold **Space** and drag to reposition the transform center
7. Press **X**, **Y**, or **Z** to constrain move/rotate/scale to that world axis
8. Press **Alt+X**, **Alt+Y**, or **Alt+Z** to toggle mirror modifier on that axis
9. Hold **Shift** for precision movement
10. Left-click or press Enter to confirm, Right-click or Escape to cancel

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

- Blender 4.5 or later

## Changelog

### v1.2.1
- Improved Super Duplicate / Super Transform performance by using object transforms during the modal and baking results on confirm
- Added X/Y/Z world axis constraints for move/rotate/scale
- Changed mirror hotkeys to Alt+X / Alt+Y / Alt+Z
- Fixed transform center behavior with parented objects
- Super Duplicate / Super Transform invoke hotkeys now apply immediately when updated in addon preferences

### v1.2.0
- Added Super Duplicate & Super Transform modal operators for sculpt objects
- Implemented configurable hotkey system for invoke and modal keys
- Added flex mesh support with object-level transformations
- Fixed mode restoration for Flex tool in Sculpt mode
- Added mirror modifier support with dedicated empty object

### v1.1.0
- Flex Tool Profile Symmetry Mode improvements:
  - Symmetry line now locks in place when enabled, preventing shifts as points are added/moved
  - Points on the symmetry axis are automatically detected and constrained to slide along it only
  - Center crossing points generated automatically when enabling symmetry on existing profiles
  - Symmetry state saved per profile slot and restored when editing
  - Disabling symmetry realizes mirrored points as real editable points
  - Visual distinction: center points (on axis) drawn in red
- Profile drawing improvements:
  - Rotation disabled during profile drawing to prevent symmetry conflicts
  - Prevents re-invoking flex_create while modal is already running

### v1.0.0
- Initial release of Flex Tool for curve-based mesh creation

### v0.0.8
- Super Tools UI
  - Panel title now shows the version inline (e.g., "Super Tools v0.0.8"), left-aligned with no header gap.
  - Reorganized UI into collapsible sub-panels under Super Tools:
    - Modeling: Super Extrude, Super Orient
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