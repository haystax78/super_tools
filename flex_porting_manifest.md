# Flex Tool Porting Manifest
## Porting sculpt_kit → Super Tools as "Flex" Modelling Tool

This document serves as a comprehensive checklist for porting the sculpt_kit addon
to Super Tools as a new modelling tool called "Flex".

---

## Porting Progress

### Completed Modules ✓
- [x] `flex_state.py` - State management (class-based, ~600 lines)
- [x] `flex_conversion.py` - Coordinate conversion utilities (~370 lines)
- [x] `flex_math.py` - Spline math and interpolation (~1000 lines)
- [x] `flex_mesh.py` - Mesh generation (~900 lines)
- [x] `flex_operator_base.py` - Base operator class (~280 lines)
- [x] `flex_tool.py` - Main operator (~350 lines)
- [x] `flex_drawing.py` - GPU drawing/HUD (~750 lines)
- [x] `flex_interaction_base.py` - Event handling (~550 lines)
- [x] `flex_panel.py` - UI Panel (~90 lines)
- [x] `__init__.py` registration - Flex modules added to Super Tools

### Functional Features
The Flex tool is now functional with the following features:
- **Point Creation**: LMB to add points to curve
- **Point Movement**: LMB drag on existing point to move
- **Point Deletion**: RMB on point to remove
- **Preview Mesh**: Real-time mesh preview while editing
- **Accept/Cancel**: Enter to finalize, Escape to cancel
- **Undo/Redo**: Ctrl+Z/Ctrl+Shift+Z
- **B-spline Mode**: Toggle with 'B' key
- **Mirror Mode**: Toggle with 'X' key  
- **Cap Types**: Toggle with 'C' key (None/Hemisphere/Planar)
- **Profile Types**: 1/2/3 keys (Circular/Square/Rounded Square)
- **Roundness**: 'R' key to cycle roundness values
- **Snapping**: 'S' key (Off/Face/Grid)
- **Adaptive**: 'A' key toggle adaptive densification
- **Twist Mode**: Hold 'T' key
- **Resolution**: Mouse wheel (Shift for circumference)
- **HUD Help**: 'H' key to toggle
- **Custom Profile**: Alt+4 to draw, 4 to apply
- **Radius Scaling**: RMB drag in empty space

### Not Yet Ported (Advanced Features)
- Flatten aspect mode (Shift+RMB)
- Radius ramp/equalize (wheel/MMB in radius mode)
- Parent selection mode (Tab)
- Group move (G key)
- Switch target muscle (Alt+Q)

---

## Source Structure (sculpt_kit)

```
sculpt_kit/
├── __init__.py              # Addon registration, bl_info
├── core/
│   ├── __init__.py
│   ├── properties.py        # Addon preferences
│   └── state.py             # Global state management (~600 lines)
├── operators/
│   ├── __init__.py
│   ├── curve_tool.py        # Main operator class (~22k bytes)
│   ├── curve_operator_base.py    # Base operator functionality (~30k bytes)
│   ├── curve_interaction_base.py # Event handling (~73k bytes)
│   ├── curve_interaction_points.py # Point manipulation (~110k bytes)
│   ├── curve_interaction.py  # Interaction module wrapper
│   └── curve_drawing_new.py  # GPU drawing/HUD (~54k bytes)
├── utils/
│   ├── __init__.py
│   ├── conversion.py        # Coordinate conversion (~16k bytes)
│   ├── math_utils.py        # Spline math, interpolation (~67k bytes)
│   └── mesh_utils.py        # Mesh generation (~72k bytes)
└── ui/
    ├── __init__.py
    └── panels.py            # UI Panel (~2k bytes)
```

---

## Feature Manifest

### 1. CORE FEATURES

#### 1.1 Curve Point System
- [ ] Point creation (LMB click)
- [ ] Point deletion (RMB click on point)
- [ ] Point dragging/repositioning
- [ ] Point insertion on curve segment
- [ ] Double-click to toggle tangent mode
- [ ] Per-point radius control
- [ ] Per-point tension control (0.0-1.0)
- [ ] No-tangent point mode (sharp corners)

#### 1.2 Spline Interpolation
- [ ] Catmull-Rom spline mode (default)
- [ ] B-spline mode (toggle with B key)
- [ ] Smooth tangent calculation
- [ ] Tension-based curve tightening

#### 1.3 Mesh Generation
- [ ] Tubular mesh from curve
- [ ] Variable radius along curve
- [ ] Resolution control (circumference segments)
- [ ] Segments control (length divisions)
- [ ] Adaptive segmentation mode (A key)

### 2. PROFILE FEATURES

#### 2.1 Profile Types
- [ ] Circular profile (key 1)
- [ ] Rounded square profile (key 2)
- [ ] Square profile (key 3)
- [ ] Custom profile from curve (key 4)

#### 2.2 Profile Modifications
- [ ] Aspect ratio control (flatten/widen)
- [ ] Per-point aspect ratio
- [ ] Roundness control for square profiles (R key)
- [ ] Per-point roundness

#### 2.3 Twist System
- [ ] Twist mode toggle (T key)
- [ ] Global twist (RMB drag in twist mode)
- [ ] Per-point twist (LMB on point in twist mode)
- [ ] Twist ramp (mouse wheel in twist mode)
- [ ] Twist reset (MMB in twist mode)

#### 2.4 Custom Profile
- [ ] Draw custom profile in screen space
- [ ] Edit custom profile points
- [ ] Scale custom profile (S key)
- [ ] Rotate custom profile (R key)
- [ ] Pick profile from existing curve (Alt+4)

### 3. CAP FEATURES

#### 3.1 Cap Types
- [ ] None (open ends)
- [ ] Hemisphere caps
- [ ] Planar caps

#### 3.2 Cap Controls
- [ ] Start cap type (C key cycles)
- [ ] End cap type (Shift+C cycles)
- [ ] Independent start/end cap settings

### 4. INTERACTION MODES

#### 4.1 Radius Adjustment Mode (RMB held)
- [ ] Uniform radius scaling (RMB drag)
- [ ] Radius ramp (mouse wheel while RMB held)
- [ ] Radius equalize (MMB while RMB held)

#### 4.2 Aspect Ratio Mode (Shift+RMB)
- [ ] Interactive aspect ratio adjustment
- [ ] Visual feedback during adjustment

#### 4.3 Group Operations
- [ ] Group move (G key)
- [ ] Move all points together
- [ ] Accept with LMB, cancel with RMB

#### 4.4 Parent Selection Mode (TAB held)
- [ ] Select parent object for new muscle
- [ ] Visual feedback showing potential parent
- [ ] Clear parent with click on empty space

### 5. SNAPPING FEATURES

#### 5.1 Snapping Modes (S key cycles)
- [ ] Off (default)
- [ ] Face snapping (project to surfaces)
- [ ] Grid snapping

#### 5.2 Construction Plane
- [ ] Automatic construction plane from first points
- [ ] Depth maintenance during dragging

### 6. MIRROR FEATURES

#### 6.1 Mirror Mode (X key toggle)
- [ ] Real-time mirror modifier
- [ ] Auto-detect mirror side from points
- [ ] Bisect flip based on point positions
- [ ] Mirror empty object for reference

### 7. VISUAL FEEDBACK

#### 7.1 Cursor HUD System
- [ ] Active mode display (Edit/Radius/Twist)
- [ ] Help toggle (H key)
- [ ] Context-sensitive control hints
- [ ] Spline mode indicator
- [ ] Mirror mode indicator
- [ ] Snapping mode indicator
- [ ] Adaptive mode indicator
- [ ] Profile type indicator
- [ ] Parent mode indicator

#### 7.2 3D Viewport Drawing
- [ ] Curve visualization
- [ ] Control point circles
- [ ] Radius visualization
- [ ] Tension handles
- [ ] Hover highlights
- [ ] Insertion point preview
- [ ] Twist cursor arrows
- [ ] Profile preview in custom draw mode

#### 7.3 Preview Mesh
- [ ] Real-time mesh preview
- [ ] Preview material (blue tint)
- [ ] X-ray/transparent mode

### 8. WORKFLOW FEATURES

#### 8.1 Accept/Continue
- [ ] Accept and exit (Enter)
- [ ] Accept and continue new curve (Space)
- [ ] Cancel (Escape)

#### 8.2 Edit Existing Muscle
- [ ] Click existing muscle to edit
- [ ] Switch to other muscle (Alt+Q)
- [ ] Preserve original material
- [ ] Preserve original modifiers
- [ ] Preserve original hierarchy

#### 8.3 Undo/Redo
- [ ] Internal undo system (Ctrl+Z)
- [ ] Internal redo system (Ctrl+Shift+Z)
- [ ] State history management

#### 8.4 Metadata Storage
- [ ] Store curve data in object custom properties
- [ ] Preserve curve data for re-editing
- [ ] Store profile settings
- [ ] Store twist values

### 9. PREFERENCES

#### 9.1 Default Settings
- [ ] Default radius
- [ ] Min/Max radius
- [ ] Default resolution
- [ ] Default segments
- [ ] Default B-spline mode
- [ ] Default adaptive segmentation

---

## Target Structure (Super Tools)

```
super_tools/
├── __init__.py              # Add flex modules to registration
├── preferences.py           # Add Flex preferences section
├── operators/
│   ├── flex_tool.py         # Main Flex operator
│   ├── flex_operator_base.py
│   ├── flex_interaction_base.py
│   ├── flex_interaction_points.py
│   └── flex_drawing.py
├── utils/
│   ├── flex_state.py        # Flex state management
│   ├── flex_conversion.py   # Coordinate conversion
│   ├── flex_math.py         # Spline math
│   └── flex_mesh.py         # Mesh generation
└── ui/
    └── flex_panel.py        # Flex UI panel
```

---

## Porting Steps

### Phase 1: Foundation
1. [ ] Create flex_state.py (port state.py)
2. [ ] Create flex_math.py (port math_utils.py)
3. [ ] Create flex_conversion.py (port conversion.py)
4. [ ] Create flex_mesh.py (port mesh_utils.py)

### Phase 2: Operators
5. [ ] Create flex_tool.py (port curve_tool.py)
6. [ ] Create flex_operator_base.py (port curve_operator_base.py)
7. [ ] Create flex_interaction_base.py (port curve_interaction_base.py)
8. [ ] Create flex_interaction_points.py (port curve_interaction_points.py)

### Phase 3: Drawing & UI
9. [ ] Create flex_drawing.py (port curve_drawing_new.py)
10. [ ] Create flex_panel.py (port panels.py)

### Phase 4: Integration
11. [ ] Add Flex preferences to preferences.py
12. [ ] Register Flex modules in __init__.py
13. [ ] Add keymaps if needed

### Phase 5: Testing
14. [ ] Test all point operations
15. [ ] Test all profile types
16. [ ] Test twist system
17. [ ] Test radius controls
18. [ ] Test snapping modes
19. [ ] Test mirror mode
20. [ ] Test edit existing workflow
21. [ ] Test accept/continue workflow

---

## Naming Conventions

| sculpt_kit | Flex (Super Tools) |
|------------|-------------------|
| sculpt_kit | flex |
| SCULPT_OT_ | MESH_OT_flex_ |
| SCULPT_PT_ | VIEW3D_PT_flex_ |
| Sculpt Kit | Flex Tool |
| muscle | flex_mesh |
| curve_* | flex_* |
| profile_* | flex_profile_* |

---

## Notes

- All references to "muscle" should be changed to "flex_mesh" or similar
- Operator bl_idname should follow Super Tools pattern
- State module should be self-contained (not global module variables)
- Consider using class-based state instead of module globals
- Preserve all hotkey bindings but document them clearly
- Keep sculpt_kit intact - this is a port, not a move
