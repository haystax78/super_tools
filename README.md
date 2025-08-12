# Super Tools Addon

A Blender addon that provides advanced mesh editing tools for enhanced modeling workflows.

## Features

- **Super Extrude**: Modal extrude operator with automatic orientation and intuitive mouse controls
- **Super Orient**: Proportional editing tool for reorienting face selections with topology-aware falloff
- **Spatial Relationship Logic**: Maintains consistent orientation behavior across all tools
- **Proportional Editing Integration**: Seamless integration with Blender's proportional editing settings

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
