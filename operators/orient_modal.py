import bpy
import bmesh
import mathutils
from mathutils import Vector
from math import radians

from ..utils import bmesh_utils, math_utils, view3d_utils, viewport_drawing, axis_constraints, performance_utils


class MESH_OT_super_orient_modal(bpy.types.Operator):
    """Modal operator to orient selected faces away from connected geometry"""
    bl_idname = "mesh.super_orient_modal"
    bl_label = "Super Orient"
    bl_description = "Orient selected faces away from connected geometry with mouse control"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH' and 
                context.edit_object and 
                context.edit_object.type == 'MESH')

    def reset_to_original_state(self, context):
        """
        Reset all vertices to original positions and reset mouse cursor to original position.
        Used when falloff parameters change during modal operation.
        """
        obj = context.active_object
        
        # Reset all affected vertices to original positions
        for vert, original_pos in self.original_vert_positions.items():
            vert.co = original_pos.copy()
        
        # Reset mouse cursor to original position (recenter on selection)
        self.current_mouse_pos = self.initial_mouse_pos.copy()
        
        # Update mesh
        bmesh.update_edit_mesh(obj.data)

    def adjust_proportional_falloff(self, context, new_size):
        """
        Modular function to handle proportional falloff size adjustments.
        Resets to original state, recalculates with new parameters, and updates visualizations.
        Also syncs with Blender's global proportional editing distance setting.
        
        Args:
            context: Blender context
            new_size: New proportional falloff size
        """
        obj = context.active_object
        self.proportional_size = new_size
        
        # Sync with Blender's global proportional editing distance setting
        context.scene.tool_settings.proportional_distance = new_size
        print(f"DEBUG: Updated global proportional distance to {new_size:.3f}")
        
        # DEBUG: Check current vertex positions before reset
        sample_vert = list(self.selected_verts)[0]
        print(f"DEBUG: Before reset - sample vertex at: {sample_vert.co}")
        
        # Store current mouse position before reset
        current_mouse_before_reset = self.current_mouse_pos.copy()
        print(f"DEBUG: Mouse position before reset: {current_mouse_before_reset}")
        
        # FIRST: Reset to original state (vertices and mouse cursor)
        self.reset_to_original_state(context)
        
        # Restore the mouse position that was current before the reset
        self.current_mouse_pos = current_mouse_before_reset
        print(f"DEBUG: Restored mouse position after reset: {self.current_mouse_pos}")
        
        # DEBUG: Check vertex positions after reset
        print(f"DEBUG: After reset - sample vertex at: {sample_vert.co}")
        
        # THEN: Recalculate proportional vertices with new size FROM ORIGINAL POSITIONS (optimized)
        obj = context.active_object
        print(f"DEBUG ORIENT: Passing center point to falloff (adjust): {self.original_selection_centroid_local}")
        self.proportional_verts = performance_utils.get_proportional_vertices_optimized(
            self.selected_faces, self.bm, self.proportional_size, self.proportional_falloff, 
            self.original_selection_centroid_local, self.falloff_cache, obj.matrix_world, use_border_anchors=True, use_topology_distance=self.use_connected_only
        )
        print(f"DEBUG: Recalculated {len(self.proportional_verts)} proportional vertices")
        
        # Check if falloff encompasses entire mesh by looking for vertices with zero weight
        total_mesh_verts = len(self.bm.verts)
        affected_verts = len(self.proportional_verts)
        
        if affected_verts < total_mesh_verts:
            # There are still unaffected vertices - calculate new pivot point normally
            self.pivot_point = math_utils.calculate_proportional_border_vertices_centroid(
                self.selected_faces, self.bm, obj.matrix_world, self.proportional_size
            )
            self.last_valid_pivot_point = self.pivot_point.copy()  # Update last valid pivot
            print(f"DEBUG: New pivot point: {self.pivot_point} (affected {affected_verts}/{total_mesh_verts} verts)")
        else:
            # Falloff encompasses entire mesh - use frozen last valid pivot point
            if self.last_valid_pivot_point:
                self.pivot_point = self.last_valid_pivot_point.copy()
                print(f"DEBUG: Falloff encompasses entire mesh ({affected_verts}/{total_mesh_verts} verts) - using frozen pivot point: {self.pivot_point}")
            else:
                # Fallback - calculate pivot anyway but warn
                self.pivot_point = math_utils.calculate_proportional_border_vertices_centroid(
                    self.selected_faces, self.bm, obj.matrix_world, self.proportional_size
                )
                print(f"DEBUG: Warning - no last valid pivot available, using calculated pivot: {self.pivot_point}")
        
        # DEBUG: Check orientation target synchronization
        print(f"DEBUG: Green cross will be drawn at: {self.pivot_point}")
        print(f"DEBUG: Rotation algorithm will use target: {self.pivot_point}")
        print(f"DEBUG: Target coordinates: X={self.pivot_point.x:.3f}, Y={self.pivot_point.y:.3f}, Z={self.pivot_point.z:.3f}")
        
        # Update original positions cache for new vertex set
        self.original_vert_positions = {}
        for vert in self.proportional_verts.keys():
            self.original_vert_positions[vert] = vert.co.copy()
        
        # Update the initial spatial relationship since pivot point may have changed
        self.initial_direction_to_pivot = (self.pivot_point - self.original_faces_centroid).normalized()
        print(f"DEBUG: Updated initial direction to pivot: {self.initial_direction_to_pivot}")
        
        # Update circle and cross visualization
        # Convert local centroid to world space for visualization
        original_centroid_world = obj.matrix_world @ self.original_selection_centroid_local
        viewport_drawing.update_proportional_circle(original_centroid_world, self.proportional_size)
        viewport_drawing.update_pivot_cross(self.pivot_point)
        
        # IMPORTANT: Reapply current mouse transformation after reset
        # This ensures the selection maintains its current position/rotation even after falloff changes
        print(f"DEBUG: About to reapply mouse transformation. Current mouse pos: {self.current_mouse_pos}")
        self.apply_mouse_transformation(context)
        print(f"DEBUG: Finished reapplying mouse transformation")

    def apply_mouse_transformation(self, context):
        """
        Apply the current mouse transformation (translation and rotation) to the selection.
        This is used both during mouse movement and after falloff radius changes.
        """
        obj = context.active_object
        region = context.region
        rv3d = context.space_data.region_3d
        
        if not region or not rv3d:
            print("DEBUG: No region or rv3d available for transformation")
            return
            
        print(f"DEBUG: Applying transformation from {self.initial_mouse} to {self.current_mouse_pos}")
            
        view_normal = rv3d.view_rotation @ mathutils.Vector((0, 0, -1))
        
        # Use original selection centroid in world space as the plane for translation
        selection_centroid_world = self.original_faces_centroid
        
        # Calculate translation from mouse movement (in world space)
        translation_world = view3d_utils.mouse_delta_to_plane_delta(
            region, rv3d, self.initial_mouse, 
            (self.current_mouse_pos.x, self.current_mouse_pos.y), 
            selection_centroid_world, view_normal
        )
        
        print(f"DEBUG: Translation world: {translation_world}")
        
        # Convert world space translation to local space for vertex operations
        translation = obj.matrix_world.inverted().to_3x3() @ translation_world
        
        # Apply axis constraints to translation
        constrained_translation = self.axis_constraints.apply_constraint(translation)
        
        print(f"DEBUG: Constrained translation: {constrained_translation}")
        
        # Calculate rotation matrix using the new utility function
        rotation_matrix = math_utils.calculate_spatial_relationship_rotation(
            self.original_faces_centroid_local, constrained_translation, 
            self.pivot_point, self.initial_direction_to_pivot, obj.matrix_world
        )
        
        if self.use_proportional:
            # Apply transformation to proportional vertices with weights
            math_utils.apply_spatial_relationship_transformation(
                list(self.proportional_verts.keys()), self.original_vert_positions,
                constrained_translation, rotation_matrix, self.original_faces_centroid_local,
                obj.matrix_world, weights=self.proportional_verts
            )
        else:
            # Apply transformation to selected vertices only (full weight)
            math_utils.apply_spatial_relationship_transformation(
                self.selected_verts, self.original_vert_positions,
                constrained_translation, rotation_matrix, self.original_faces_centroid_local,
                obj.matrix_world, weights=None
            )
        
        # Update mesh
        bmesh.update_edit_mesh(obj.data)

    def invoke(self, context, event):
        obj = context.edit_object
        if obj is None:
            self.report({'ERROR'}, "No active mesh object")
            return {'CANCELLED'}

        self.bm = bmesh.from_edit_mesh(obj.data)
        selected_faces = [f for f in self.bm.faces if f.select]
        
        if not selected_faces:
            self.report({'ERROR'}, "No faces selected")
            return {'CANCELLED'}

        # Store initial state
        self.selected_faces = selected_faces
        self.initial_mouse = (event.mouse_region_x, event.mouse_region_y)
        
        # Check if proportional editing is enabled
        tool_settings = context.scene.tool_settings
        self.use_proportional = tool_settings.use_proportional_edit
        self.proportional_size = tool_settings.proportional_size
        self.proportional_falloff = tool_settings.proportional_edit_falloff
        self.use_connected_only = tool_settings.use_proportional_connected
        
        print(f"Super Orient: Proportional editing settings - Connected Only: {self.use_connected_only}")
        print(f"Super Orient: Will use {'topology-based' if self.use_connected_only else 'radial'} falloff distance")
        
        # Calculate pivot point based on proportional editing settings
        if self.use_proportional:
            # Use proportional border vertices (outside falloff radius) as pivot
            self.pivot_point = math_utils.calculate_proportional_border_vertices_centroid(
                selected_faces, self.bm, obj.matrix_world, self.proportional_size
            )
            # Store the initial valid pivot point for fallback when falloff encompasses entire mesh
            self.last_valid_pivot_point = self.pivot_point.copy()
        else:
            # Use regular border vertices (connected to selection) as pivot
            self.pivot_point = math_utils.calculate_border_vertices_centroid(
                selected_faces, self.bm, obj.matrix_world
            )
            self.last_valid_pivot_point = None  # Not used in non-proportional mode
        
        # Get all vertices from selected faces
        self.selected_verts = list(set(v for f in selected_faces for v in f.verts))
        
        # Cache original selection centroid in LOCAL SPACE for proportional calculations
        # This ensures falloff is always calculated from the original position, not current moved position
        selected_verts = list(set(v for f in self.selected_faces for v in f.verts))
        self.original_selection_centroid_local = Vector((0, 0, 0))
        for vert in selected_verts:
            self.original_selection_centroid_local += vert.co
        self.original_selection_centroid_local /= len(selected_verts)
        
        # Cache original mouse position for proportional editing calculations
        self.initial_mouse_pos = Vector((event.mouse_region_x, event.mouse_region_y))
        self.current_mouse_pos = self.initial_mouse_pos.copy()
        
        # Axis constraint state
        self.axis_constraints = axis_constraints.create_constraint_state()
        
        # Cache original selection state for transformation calculations
        # Store both local and world space versions for consistent coordinate handling
        self.original_faces_centroid_local = math_utils.calculate_faces_centroid(self.selected_faces, mathutils.Matrix.Identity(4))
        self.original_faces_centroid = obj.matrix_world @ self.original_faces_centroid_local
        
        # Store the initial spatial relationship between selection and pivot (world space)
        self.initial_direction_to_pivot = (self.pivot_point - self.original_faces_centroid).normalized()
        print(f"Super Orient: Initial direction from selection to pivot: {self.initial_direction_to_pivot}")
        
        # Initialize performance cache for proportional falloff calculations
        self.falloff_cache = performance_utils.ProportionalFalloffCache()
        
        if self.use_proportional:
            # Get proportional vertices and their weights using original selection center (optimized)
            print(f"DEBUG ORIENT: Passing center point to falloff: {self.original_selection_centroid_local}")
            self.proportional_verts = performance_utils.get_proportional_vertices_optimized(
                self.selected_faces, self.bm, self.proportional_size, self.proportional_falloff, 
                self.original_selection_centroid_local, self.falloff_cache, obj.matrix_world, use_border_anchors=True, use_topology_distance=self.use_connected_only
            )
            print(f"Super Orient: Proportional editing enabled - {len(self.proportional_verts)} vertices affected")
            
            # Cache original positions for all affected vertices
            self.original_vert_positions = {}
            for vert in self.proportional_verts.keys():
                self.original_vert_positions[vert] = vert.co.copy()
        else:
            # Cache original vertex positions for selected vertices only
            self.original_vert_positions = {}
            for vert in self.selected_verts:
                self.original_vert_positions[vert] = vert.co.copy()
        
        print(f"Super Orient: {len(selected_faces)} faces, {len(self.selected_verts)} vertices")
        print(f"Super Orient: Pivot point at {self.pivot_point}")
        
        # Start drawing proportional circle and pivot cross if proportional editing is enabled
        if self.use_proportional:
            selection_centroid = math_utils.calculate_faces_centroid(self.selected_faces, obj.matrix_world)
            viewport_drawing.start_proportional_circle_drawing(selection_centroid, self.proportional_size)
            viewport_drawing.start_pivot_cross_drawing(self.pivot_point)
        
        # Add modal handler
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}



    def modal(self, context, event):
        obj = context.edit_object
        
        # Handle axis constraint toggles
        if self.axis_constraints.handle_constraint_event(event, "Super Orient"):
            return {'RUNNING_MODAL'}
        
        elif event.type == 'WHEELUPMOUSE' and self.use_proportional:
            # Increase proportional size
            new_size = self.proportional_size * 1.1
            print(f"Super Orient: Proportional size increased to {new_size:.3f}")
            self.adjust_proportional_falloff(context, new_size)
            
            return {'RUNNING_MODAL'}
            
        elif event.type == 'WHEELDOWNMOUSE' and self.use_proportional:
            # Decrease proportional size (minimum 0.01)
            new_size = max(0.01, self.proportional_size * 0.9)
            print(f"Super Orient: Proportional size decreased to {new_size:.3f}")
            self.adjust_proportional_falloff(context, new_size)
            
            return {'RUNNING_MODAL'}
            
        elif event.type == 'LEFT_BRACKET' and event.value == 'PRESS' and self.use_proportional:
            # Decrease proportional size (alternative to mouse wheel)
            new_size = max(0.01, self.proportional_size * 0.9)
            print(f"Super Orient: Proportional size decreased to {new_size:.3f}")
            self.adjust_proportional_falloff(context, new_size)
            
            return {'RUNNING_MODAL'}
            
        elif event.type == 'RIGHT_BRACKET' and event.value == 'PRESS' and self.use_proportional:
            # Increase proportional size (alternative to mouse wheel)
            new_size = self.proportional_size * 1.1
            print(f"Super Orient: Proportional size increased to {new_size:.3f}")
            self.adjust_proportional_falloff(context, new_size)
            
            return {'RUNNING_MODAL'}
            
        elif event.type == 'MOUSEMOVE':
            # Update current mouse position
            self.current_mouse_pos = Vector((event.mouse_region_x, event.mouse_region_y))
            
            # Apply the mouse transformation using the shared function
            self.apply_mouse_transformation(context)
            
            # Update mesh
            bmesh.update_edit_mesh(obj.data)
            
        elif (event.type == 'LEFTMOUSE' and event.value == 'PRESS') or (event.type == 'RET' and event.value == 'PRESS'):
            # Confirm operation
            print("Super Orient Modal: CONFIRMING operation")
            
            # Stop circle drawing
            if self.use_proportional:
                viewport_drawing.stop_proportional_circle_drawing()
            
            # Recalculate all face normals for final result
            bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces)
            
            # Keep selection as is (selected faces remain selected)
            bmesh.update_edit_mesh(obj.data)
            return {'FINISHED'}
            
        elif (event.type == 'RIGHTMOUSE' and event.value == 'PRESS') or (event.type == 'ESC' and event.value == 'PRESS'):
            # Cancel operation - restore original positions
            print("Super Orient Modal: CANCELLING operation")
            
            # Stop circle drawing
            if self.use_proportional:
                viewport_drawing.stop_proportional_circle_drawing()
            
            # Restore all affected vertices to original positions
            for vert, original_pos in self.original_vert_positions.items():
                vert.co = original_pos.copy()
            
            bmesh.update_edit_mesh(obj.data)
            return {'CANCELLED'}
        
        # Allow viewport navigation events to pass through
        elif event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} or \
             (event.type == 'MOUSEMOVE' and event.value == 'PRESS' and event.shift):
            # Pass through navigation events to allow viewport manipulation
            return {'PASS_THROUGH'}
            
        return {'RUNNING_MODAL'}


def register():
    bpy.utils.register_class(MESH_OT_super_orient_modal)


def unregister():
    bpy.utils.unregister_class(MESH_OT_super_orient_modal)


if __name__ == "__main__":
    register()
