# Super Tools Addon

A Blender addon that provides advanced mesh editing tools for enhanced modeling workflows.

## Features

- **Super Extrude**: Modal extrude operator with automatic orientation and intuitive mouse controls
- **Super Orient**: Proportional editing tool for reorienting face selections with topology-aware falloff
- **Spatial Relationship Logic**: Maintains consistent orientation behavior across all tools
- **Proportional Editing Integration**: Seamless integration with Blender's proportional editing settings
- **Transform Stability**: Works reliably on objects with any scale, rotation, or transformation

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
2. Access through the mesh menu or assign a custom hotkey
3. Enable proportional editing for falloff-based orientation
4. Move your mouse to reorient faces while maintaining spatial relationships
5. Right-click or press Escape to cancel the operation

## Technical Details

- Deletes original selected faces during extrusion to maintain manifold geometry
- Selects the extruded cap faces when the operation is confirmed
- Handles cancellation by restoring original vertex positions
- Fully integrated with Blender's undo system

## Requirements

- Blender 4.2 or later
