"""
State management for the Flex tool in Super Tools addon.
This module manages the global state of the Flex tool using a class-based approach
for better encapsulation and to avoid polluting the global namespace.
"""
import bpy
from mathutils import Vector, Matrix
import time


class FlexState:
    """
    Centralized state management for the Flex tool.
    All state variables are instance attributes to allow for clean reset.
    """
    
    # Snapping mode constants
    SNAPPING_OFF = 0
    SNAPPING_FACE = 1
    
    # Profile type constants
    PROFILE_CIRCULAR = 0
    PROFILE_SQUARE_ROUNDED = 1
    PROFILE_SQUARE = 2
    PROFILE_CUSTOM = 3
    
    # Configuration constants
    DEFAULT_RADIUS = 0.5
    MIN_RADIUS = 0.05
    MAX_RADIUS = 10.0
    
    # Hotkey configuration (Blender event.type names) - defaults, overridden by addon prefs
    KEY_CANCEL = 'ESC'
    KEY_TWIST = 'T'
    KEY_PARENT_MODE = 'TAB'
    KEY_MIRROR = 'X'
    KEY_ADAPTIVE = 'A'
    KEY_PROFILE_TYPE_1 = 'ONE'
    KEY_PROFILE_TYPE_2 = 'TWO'
    KEY_PROFILE_TYPE_3 = 'THREE'
    KEY_PROFILE_TYPE_4 = 'FOUR'
    KEY_PROFILE_TYPE_5 = 'FIVE'
    KEY_PROFILE_TYPE_6 = 'SIX'
    KEY_PROFILE_TYPE_7 = 'SEVEN'
    KEY_PROFILE_TYPE_8 = 'EIGHT'
    KEY_PROFILE_TYPE_9 = 'NINE'
    KEY_PROFILE_ROUNDNESS = 'R'
    KEY_PROFILE_CAP_TOGGLE = 'C'
    KEY_PROFILE_RESOLUTION_DECREASE = 'LEFT_BRACKET'
    KEY_PROFILE_RESOLUTION_INCREASE = 'RIGHT_BRACKET'
    KEY_PROFILE_ASPECT_DEC = 'COMMA'
    KEY_PROFILE_ASPECT_INC = 'PERIOD'
    KEY_PROFILE_ASPECT_RESET = 'SLASH'
    KEY_GROUP_MOVE = 'G'
    KEY_SWITCH_MESH = 'Q'
    KEY_SNAPPING_MODE = 'S'
    KEY_BSPLINE = 'B'
    KEY_TOGGLE_HUD = 'H'
    KEY_UNDO = 'Z'
    KEY_REDO = 'C'
    
    @classmethod
    def load_hotkeys_from_prefs(cls):
        """Load hotkey settings from addon preferences."""
        try:
            addon_prefs = bpy.context.preferences.addons.get("super_tools")
            if addon_prefs:
                prefs = addon_prefs.preferences
                # Only switch mesh key is customizable in preferences
                cls.KEY_SWITCH_MESH = getattr(prefs, 'flex_key_switch_mesh', 'Q')
        except Exception:
            pass
    
    @classmethod
    def get_prefs(cls):
        """Get addon preferences."""
        try:
            addon_prefs = bpy.context.preferences.addons.get("super_tools")
            if addon_prefs:
                return addon_prefs.preferences
        except Exception:
            pass
        return None
    
    def __init__(self):
        """Initialize all state variables to default values."""
        self.initialize()
    
    def initialize(self):
        """Initialize/reset the state to default values."""
        # Load hotkeys from addon preferences
        FlexState.load_hotkeys_from_prefs()
        
        # Load radius limits from preferences
        prefs = FlexState.get_prefs()
        if prefs:
            FlexState.DEFAULT_RADIUS = getattr(prefs, 'flex_default_radius', 0.5)
            FlexState.MIN_RADIUS = getattr(prefs, 'flex_min_radius', 0.05)
            FlexState.MAX_RADIUS = getattr(prefs, 'flex_max_radius', 10.0)
        
        # Curve state
        self.points_3d = []
        self.point_radii_3d = []
        self.point_tensions = []
        self.no_tangent_points = set()
        self.reveal_control_index = -1
        
        # Drawing state
        self.draw_handle = None
        self.is_running = False
        
        # Interaction state
        self.active_point_index = -1
        self.hover_point_index = -1
        self.adjusting_radius_index = -1
        self.hover_radius_index = -1
        self.adjusting_tension_index = -1
        self.hover_tension_index = -1
        self.creating_point_index = -1
        self.creating_point_start_pos = None
        self.creating_point_threshold_crossed = False
        self.last_drag_radius = None
        self.drag_start_world_point = None
        
        # Curve hover state
        self.hover_on_curve = False
        self.hover_curve_point_3d = None
        self.hover_curve_segment = -1
        
        # Curve mode toggle - load from preferences
        self.bspline_mode = True
        if prefs:
            self.bspline_mode = getattr(prefs, 'flex_default_bspline_mode', True)
        
        # Double-click detection
        self.last_click_time = 0
        self.last_click_point = -1
        
        # Mesh preview
        self.preview_mesh_obj = None
        
        # Configuration
        self.current_depth = 10.0
        self.snapping_mode = self.SNAPPING_OFF
        self.face_projection_enabled = False
        
        # Construction plane
        self.construction_plane_origin = None
        self.construction_plane_normal = None
        
        # Cap types: 0=None, 1=Hemisphere, 2=Planar
        # Load default cap type from preferences
        default_cap = 1  # Default to Hemisphere
        if prefs:
            cap_pref = getattr(prefs, 'flex_default_cap_type', 'HEMISPHERE')
            if cap_pref == 'NONE':
                default_cap = 0
            elif cap_pref == 'HEMISPHERE':
                default_cap = 1
            elif cap_pref == 'PLANAR':
                default_cap = 2
        self.start_cap_type = default_cap
        self.end_cap_type = default_cap
        self.adaptive_segmentation = False
        
        # Custom profile settings - 6 slots (keys 4-9)
        self.custom_profile_slots = [[] for _ in range(6)]  # 6 profile slots
        self.custom_profile_slot_names = ["Custom 1", "Custom 2", "Custom 3", "Custom 4", "Custom 5", "Custom 6"]
        self.active_custom_profile_slot = 0  # 0-4 for slots 1-5
        self.custom_profile_curve_name = None
        self.custom_profile_points = []
        self.custom_profile_draw_mode = False
        self._custom_profile_data = {'screen_points': []}
        self._custom_profile_backup = None  # Backup for cancel/restore
        
        # Custom profile point interaction
        self.custom_profile_hover_index = -1
        self.custom_profile_active_index = -1
        self.custom_profile_hover_edge = -1
        self.custom_profile_hover_edge_point = None
        self.custom_profile_scaling = False
        self.custom_profile_rotating = False
        self.custom_profile_moving = False
        self.custom_profile_transform_start_pos = None
        
        # Profile settings
        self.profile_aspect_ratio = 1.0
        self.profile_twist_mode = False
        self.profile_global_twist = 0.0
        self.profile_point_twists = []
        self.twist_dragging_point = -2
        self.twist_drag_start_angle = None
        self.twist_drag_start_mouse = None
        
        # Profile type settings
        self.profile_global_type = self.PROFILE_CIRCULAR
        self.profile_point_types = []
        self.profile_roundness = 0.3
        self.profile_point_roundness = []
        
        # Camera tracking
        self.last_camera_matrix = None
        
        # Object transformation
        self.object_matrix_world = None
        self.edited_object_name = None
        
        # Input tracking
        self.last_mouse_pos = None
        self.tension_drag_start_angle = None
        self.tension_drag_start_value = None
        self.tension_anim_current_index = -1
        self.tension_anim_prev_index = -1
        self.tension_anim_value_current = 0.0
        self.tension_anim_value_prev = 0.0
        self.last_anim_time = None
        
        # Parent mode
        self.parent_mode_active = False
        self.selected_parent_name = None
        self.parent_mode_lockout = False
        
        # Mirror mode
        self.mirror_mode_active = False
        self.mirror_flip_x = False
        self.mirror_empty_name = "flex_mirror_empty"
        
        # Face projection drag reference
        self.face_drag_ref_world = None
        self.last_face_hit_world = None
        self.face_drag_depth_t = None
        self.face_drag_is_ortho = False
        self.face_drag_view_normal = None
        
        # Original mesh modifiers
        self.original_modifiers = []
        
        # Group move mode
        self.group_move_active = False
        self.group_move_start_point = None
        self.group_move_start_mouse_pos = None
        self.group_move_affected_indices = []
        self.group_move_original_positions = []
        
        # Group rotate mode
        self.group_rotate_active = False
        self.group_rotate_start_point = None
        self.group_rotate_center = None
        self.group_rotate_affected_indices = []
        self.group_rotate_original_positions = []
        
        # Radius scale mode
        self.radius_scale_active = False
        self.radius_scale_start_mouse = None
        self.radius_scale_original_radii = []
        
        # Radius ramp mode
        self.radius_ramp_active = False
        self.radius_ramp_start_mouse = None
        self.radius_ramp_original_radii = []
        self.radius_ramp_amount = 0.0
        
        # Radius equalize lock
        self.radius_equalize_active = False
        
        # Flatten aspect mode
        self.flatten_aspect_active = False
        self.flatten_aspect_start_mouse = None
        self.flatten_aspect_start_value = 1.0
        
        # Twist scale mode
        self.twist_scale_active = False
        self.twist_ramp_amount = 0.0
        self.twist_ramp_base = 0.0
        
        # HUD help visibility
        self.hud_help_visible = False
        
        # Undo/Redo manager
        self.undo_redo_manager = UndoRedoManager(self)
    
    def cleanup(self):
        """Clean up resources when the tool is disabled."""
        self.is_running = False
        
        if self.draw_handle is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(self.draw_handle, 'WINDOW')
            except:
                print("Flex: Failed to remove drawing handler")
            self.draw_handle = None
        
        if self.preview_mesh_obj is not None:
            try:
                if self.preview_mesh_obj.name in bpy.data.objects:
                    mesh_data = self.preview_mesh_obj.data
                    # Clear material slots before deletion to avoid stale references
                    if self.preview_mesh_obj.data.materials:
                        self.preview_mesh_obj.data.materials.clear()
                    for collection in self.preview_mesh_obj.users_collection:
                        collection.objects.unlink(self.preview_mesh_obj)
                    bpy.data.objects.remove(self.preview_mesh_obj)
                    if mesh_data and mesh_data.name in bpy.data.meshes and mesh_data.users == 0:
                        bpy.data.meshes.remove(mesh_data)
                self.preview_mesh_obj = None
            except ReferenceError:
                self.preview_mesh_obj = None
            except Exception as e:
                print(f"Flex: Failed to remove preview mesh: {e}")
                self.preview_mesh_obj = None
    
    def reset_for_new_curve(self):
        """Reset state for creating a new curve."""
        self.points_3d = []
        self.point_radii_3d = []
        self.point_tensions = []
        self.no_tangent_points = set()
        
        self.active_point_index = -1
        self.hover_point_index = -1
        self.adjusting_radius_index = -1
        self.hover_radius_index = -1
        self.adjusting_tension_index = -1
        self.hover_tension_index = -1
        
        self.last_click_time = 0
        self.last_click_point = -1
        
        self.undo_redo_manager.clear()
        
        self.profile_twist_mode = False
        self.profile_global_twist = 0.0
        self.profile_point_twists = []
        self.twist_dragging_point = -1
        self.twist_drag_start_angle = None
        
        self.object_matrix_world = None
        self.current_depth = 10.0
        self.last_camera_matrix = None
        self.construction_plane_origin = None
        self.construction_plane_normal = None
        self.original_modifiers = []
        
        # Reset parent mode state but KEEP selected_parent_name for subsequent meshes
        self.parent_mode_active = False
        # Don't reset selected_parent_name here - it should persist across new curves in session
        self.parent_mode_lockout = False
    
    def save_history_state(self):
        """Save the current state to history for undo/redo."""
        self.undo_redo_manager.save_state()
    
    def undo_action(self):
        """Undo the last action by restoring a previous state."""
        return self.undo_redo_manager.undo()
    
    def redo_action(self):
        """Redo a previously undone action."""
        return self.undo_redo_manager.redo()


class UndoRedoManager:
    """Manages undo/redo history for the Flex tool."""
    
    def __init__(self, state):
        self.state = state
        self.history = []
        self.index = -1
    
    def save_state(self):
        """Deep copy all relevant state."""
        current_state = {
            'points_3d': [p.copy() for p in self.state.points_3d],
            'point_radii_3d': self.state.point_radii_3d.copy(),
            'point_tensions': self.state.point_tensions.copy() if self.state.point_tensions else [],
            'no_tangent_points': self.state.no_tangent_points.copy(),
            'start_cap_type': self.state.start_cap_type,
            'end_cap_type': self.state.end_cap_type,
            'adaptive_segmentation': self.state.adaptive_segmentation,
            'profile_aspect_ratio': self.state.profile_aspect_ratio,
            'profile_twist_mode': self.state.profile_twist_mode,
            'profile_global_twist': self.state.profile_global_twist,
            'profile_point_twists': self.state.profile_point_twists.copy() if self.state.profile_point_twists else [],
            'profile_global_type': self.state.profile_global_type,
            'profile_point_types': self.state.profile_point_types.copy() if self.state.profile_point_types else [],
            'profile_roundness': self.state.profile_roundness,
            'profile_point_roundness': self.state.profile_point_roundness.copy() if self.state.profile_point_roundness else []
        }
        if self.index < len(self.history) - 1:
            self.history = self.history[:self.index + 1]
        self.history.append(current_state)
        self.index = len(self.history) - 1
    
    def can_undo(self):
        return self.index > 0
    
    def can_redo(self):
        return self.index < len(self.history) - 1
    
    def undo(self):
        if self.can_undo():
            self.index -= 1
            self.restore_state(self.history[self.index])
            return True
        return False
    
    def redo(self):
        if self.can_redo():
            self.index += 1
            self.restore_state(self.history[self.index])
            return True
        return False
    
    def restore_state(self, saved_state):
        """Restore state from a saved snapshot."""
        self.state.points_3d = [p.copy() for p in saved_state['points_3d']]
        self.state.point_radii_3d = saved_state['point_radii_3d'].copy()
        self.state.point_tensions = saved_state['point_tensions'].copy() if 'point_tensions' in saved_state else []
        self.state.no_tangent_points = saved_state['no_tangent_points'].copy()
        self.state.start_cap_type = saved_state.get('start_cap_type', 1)
        self.state.end_cap_type = saved_state.get('end_cap_type', 1)
        self.state.adaptive_segmentation = saved_state.get('adaptive_segmentation', False)
        self.state.profile_aspect_ratio = saved_state.get('profile_aspect_ratio', 1.0)
        self.state.profile_twist_mode = saved_state.get('profile_twist_mode', False)
        self.state.profile_global_twist = saved_state.get('profile_global_twist', 0.0)
        self.state.profile_point_twists = saved_state.get('profile_point_twists', []).copy()
        self.state.profile_global_type = saved_state.get('profile_global_type', FlexState.PROFILE_CIRCULAR)
        self.state.profile_point_types = saved_state.get('profile_point_types', []).copy()
        self.state.profile_roundness = saved_state.get('profile_roundness', 0.3)
        self.state.profile_point_roundness = saved_state.get('profile_point_roundness', []).copy()
    
    def clear(self):
        self.history = []
        self.index = -1


# Global state instance for the Flex tool
# This is accessed by operators and drawing functions
state = FlexState()


def save_custom_profiles_to_scene():
    """Save custom profile slots to scene data for persistence."""
    scene = bpy.context.scene
    if scene is None:
        return
    
    # Store profiles as JSON strings in scene custom properties
    import json
    for i, profile in enumerate(state.custom_profile_slots):
        prop_name = f"flex_custom_profile_{i}"
        if profile and len(profile) >= 3:
            # Convert tuples to lists for JSON serialization
            profile_data = [list(pt) for pt in profile]
            scene[prop_name] = json.dumps(profile_data)
        elif prop_name in scene:
            del scene[prop_name]


def load_custom_profiles_from_scene():
    """Load custom profile slots from scene data."""
    scene = bpy.context.scene
    if scene is None:
        return
    
    import json
    for i in range(6):
        prop_name = f"flex_custom_profile_{i}"
        if prop_name in scene:
            try:
                profile_data = json.loads(scene[prop_name])
                # Convert lists back to tuples
                state.custom_profile_slots[i] = [tuple(pt) for pt in profile_data]
            except (json.JSONDecodeError, TypeError):
                state.custom_profile_slots[i] = []
        else:
            state.custom_profile_slots[i] = []


def register():
    """Register function (no-op, state is module-level)."""
    pass


def unregister():
    """Unregister function - cleanup state."""
    state.cleanup()
