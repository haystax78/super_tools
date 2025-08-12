import bpy
import bmesh
import mathutils
from math import radians
from ..utils import bmesh_utils, math_utils, view3d_utils, axis_constraints, viewport_drawing


class MESH_OT_super_extrude_modal(bpy.types.Operator):
    """Modal extrude operator that keeps extruded faces facing away from selection center"""
    bl_idname = "mesh.super_extrude_modal"
    bl_label = "Super Extrude"
    bl_options = {'REGISTER', 'UNDO'}
    
    # Class variables to store state
    bm = None
    original_faces = []
    original_top_verts_positions = []
    top_faces = []
    top_verts = []
    side_faces = []
    selection_center = mathutils.Vector((0, 0, 0))
    initial_mouse = (0, 0)
    original_mesh_state = None
    use_proportional = False
    
    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH' and 
                context.object is not None and 
                context.object.type == 'MESH')
    
    def invoke(self, context, event):
        # Get the active object and its mesh
        obj = context.edit_object
        if obj is None:
            self.report({'ERROR'}, "No active mesh object")
            return {'CANCELLED'}
        
        # Get bmesh representation
        self.bm = bmesh.from_edit_mesh(obj.data)
        
        # Validate selection
        selected_faces = [f for f in self.bm.faces if f.select]
        if not selected_faces:
            self.report({'ERROR'}, "No faces selected")
            return {'CANCELLED'}
        
        # Store the original faces for potential cancel operation
        self.original_faces = [f for f in selected_faces]
        
        # Store initial mouse position
        self.initial_mouse = (event.mouse_region_x, event.mouse_region_y)
        
        # Calculate selection center in world space for mouse interaction
        self.selection_center = math_utils.calculate_faces_centroid(selected_faces, obj.matrix_world)
        
        # Also store selection center in local space for vertex operations
        self.selection_center_local = math_utils.calculate_faces_centroid(selected_faces, mathutils.Matrix.Identity(4))
        
        # Calculate average normal before we potentially modify the mesh
        avg_normal = math_utils.calculate_faces_average_normal(selected_faces, obj.matrix_world)
        
        # Identify top faces (those not sharing edges with original selection border)
        # We need to do this BEFORE deleting the original faces
        original_border_edges = bmesh_utils.get_border_edges(self.original_faces)
        
        # Perform extrude operation
        try:
            ret = bmesh.ops.extrude_face_region(self.bm, geom=selected_faces)
        except Exception as e:
            self.report({'ERROR'}, f"Extrude operation failed: {str(e)}")
            return {'CANCELLED'}
        
        # Check if extrude operation succeeded
        if 'geom' not in ret:
            self.report({'ERROR'}, "Extrude operation returned no geometry")
            return {'CANCELLED'}
        
        # Delete original faces (they are no longer needed)
        bmesh.ops.delete(self.bm, geom=selected_faces, context='FACES')
        
        # Separate extruded geometry
        extruded_geom = ret['geom']
        extruded_verts = [elem for elem in extruded_geom if isinstance(elem, bmesh.types.BMVert)]
        extruded_faces = [elem for elem in extruded_geom if isinstance(elem, bmesh.types.BMFace)]
        
        # Debug: Print what was extruded
        print(f"Super Extrude: Extruded {len(extruded_faces)} faces, {len(extruded_verts)} verts")
        
        # Identify top faces (those not sharing edges with original selection border)
        self.top_faces = bmesh_utils.identify_top_faces(extruded_faces, original_border_edges)
        
        # Find side faces by looking at all faces that share vertices with the extruded vertices
        # but are not top faces and were created during the extrusion
        extruded_vert_set = set(extruded_verts)
        self.side_faces = []
        
        # Look through all faces in the mesh to find the side faces
        for face in self.bm.faces:
            # Skip if it's a top face
            if face in self.top_faces:
                continue
            # Check if this face shares vertices with the extruded vertices
            face_verts = set(face.verts)
            if face_verts.intersection(extruded_vert_set):
                # This face shares vertices with the extrusion, likely a side face
                self.side_faces.append(face)
        
        print(f"Super Extrude: Found {len(self.top_faces)} top faces, {len(self.side_faces)} side faces")
        
        # Get top vertices
        self.top_verts = list(set(v for f in self.top_faces for v in f.verts))
        
        # Store original positions for cancel operation and spatial relationship transformation
        self.original_top_verts_positions = [v.co.copy() for v in self.top_verts]
        self.original_vert_positions = {v: v.co.copy() for v in self.top_verts}
        
        # Store initial mouse position for delta calculations
        self.initial_mouse = (event.mouse_region_x, event.mouse_region_y)
        
        # Set up spatial relationship data for the new orientation approach
        # Use selection center as pivot point for extrude (faces orient away from original selection)
        self.pivot_point = self.selection_center
        
        # Calculate top faces centroid in both local and world space
        self.original_faces_centroid_local = math_utils.calculate_faces_centroid(self.top_faces, mathutils.Matrix.Identity(4))
        
        # Apply a small offset along the average normal to establish initial spatial relationship
        # This gives us a reliable direction vector for the orientation system
        avg_normal = math_utils.calculate_faces_average_normal(self.top_faces, obj.matrix_world)
        small_offset = 0.001  # Very small offset in world space
        offset_vector_local = obj.matrix_world.inverted().to_3x3() @ (avg_normal * small_offset)
        
        # Apply the offset to top vertices to establish initial position
        for v in self.top_verts:
            v.co += offset_vector_local
        
        # Update the original positions cache to include the offset
        for v in self.top_verts:
            self.original_vert_positions[v] = v.co.copy()
        
        # Now calculate the centroid with the offset applied
        self.original_faces_centroid_local = math_utils.calculate_faces_centroid(self.top_faces, mathutils.Matrix.Identity(4))
        self.original_faces_centroid = obj.matrix_world @ self.original_faces_centroid_local
        
        # Calculate initial direction from top faces centroid to pivot (selection center) in world space
        self.initial_direction_to_pivot = (self.pivot_point - self.original_faces_centroid).normalized()
        
        print(f"Super Extrude: Applied small offset along normal: {avg_normal * small_offset}")
        print(f"Super Extrude: Top faces centroid (world): {self.original_faces_centroid}")
        print(f"Super Extrude: Pivot point (selection center): {self.pivot_point}")
        print(f"Super Extrude: Initial direction to pivot: {self.initial_direction_to_pivot}")
        
        # Axis constraint state
        self.axis_constraints = axis_constraints.create_constraint_state()
        
        print(f"Super Extrude: {len(selected_faces)} faces, {len(self.top_verts)} top vertices")
        print(f"Super Extrude: Selection center at {self.selection_center}")
        
        # Apply a small offset to avoid coplanarity issues
        for v in extruded_verts:
            v.co += avg_normal * 0.001
        
        # Update mesh
        bmesh.update_edit_mesh(obj.data)
        
        # Optional proportional circle visualization (HUD disabled)
        ts = context.scene.tool_settings
        self.use_proportional = ts.use_proportional_edit
        if self.use_proportional:
            viewport_drawing.start_proportional_circle_drawing(self.selection_center, ts.proportional_size)
            viewport_drawing.start_pivot_cross_drawing(self.selection_center)

        # Add modal handler
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    


    def modal(self, context, event):
        obj = context.edit_object
        # Pass through raw modifier keys to allow viewport navigation combos
        if event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT', 'LEFT_CTRL', 'RIGHT_CTRL', 'LEFT_ALT', 'RIGHT_ALT'}:
            return {'PASS_THROUGH'}
        
        # Debug: Print event info to help diagnose the issue
        if event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'ESC', 'RET'}:
            print(f"Super Extrude Modal: {event.type} - {event.value}")
        
        # Handle axis constraint toggles
        if self.axis_constraints.handle_constraint_event(event, "Super Extrude"):
            return {'RUNNING_MODAL'}

        # Proportional controls and quick menu
        ts = context.scene.tool_settings
        if event.type == 'O' and event.shift:
            bpy.ops.wm.call_menu(name="VIEW3D_MT_super_tools_proportional")
            return {'RUNNING_MODAL'}
        elif event.type == 'O' and event.value == 'PRESS':
            self.use_proportional = not self.use_proportional
            ts.use_proportional_edit = self.use_proportional
            if self.use_proportional:
                viewport_drawing.start_proportional_circle_drawing(self.selection_center, ts.proportional_size)
                viewport_drawing.start_pivot_cross_drawing(self.selection_center)
            else:
                viewport_drawing.stop_proportional_circle_drawing()
            return {'RUNNING_MODAL'}
        elif event.type == 'LEFT_BRACKET' and event.value == 'PRESS' and self.use_proportional:
            ts.proportional_size = max(0.01, ts.proportional_size * 0.9)
            viewport_drawing.update_proportional_circle(self.selection_center, ts.proportional_size)
            return {'RUNNING_MODAL'}
        elif event.type == 'RIGHT_BRACKET' and event.value == 'PRESS' and self.use_proportional:
            ts.proportional_size = ts.proportional_size * 1.1
            viewport_drawing.update_proportional_circle(self.selection_center, ts.proportional_size)
            return {'RUNNING_MODAL'}
        elif event.type == 'WHEELUPMOUSE' and self.use_proportional:
            ts.proportional_size = ts.proportional_size * 1.1
            viewport_drawing.update_proportional_circle(self.selection_center, ts.proportional_size)
            self.update_hud(context)
            return {'RUNNING_MODAL'}
        elif event.type == 'WHEELDOWNMOUSE' and self.use_proportional:
            ts.proportional_size = max(0.01, ts.proportional_size * 0.9)
            viewport_drawing.update_proportional_circle(self.selection_center, ts.proportional_size)
            self.update_hud(context)
            return {'RUNNING_MODAL'}
        elif event.type in {"ONE","TWO","THREE","FOUR","FIVE","SIX","SEVEN"} and event.value == 'PRESS' and self.use_proportional:
            falloffs = ['SMOOTH','SPHERE','ROOT','INVERSE_SQUARE','SHARP','LINEAR','CONSTANT']
            idx_map = {'ONE':0,'TWO':1,'THREE':2,'FOUR':3,'FIVE':4,'SIX':5,'SEVEN':6}
            ts.proportional_edit_falloff = falloffs[idx_map[event.type]]
            return {'RUNNING_MODAL'}
        
        # Handle different events
        elif event.type == 'MOUSEMOVE':
            # Convert mouse movement to 3D translation
            region = context.region
            rv3d = context.space_data.region_3d
            
            # Get view plane normal
            view_normal = rv3d.view_rotation @ mathutils.Vector((0, 0, -1))
            
            # Calculate translation vector in world space
            translation_world = view3d_utils.mouse_delta_to_plane_delta(
                region, rv3d, 
                self.initial_mouse, 
                (event.mouse_region_x, event.mouse_region_y),
                self.selection_center,
                view_normal
            )
            
            # Convert world space translation to local space for vertex operations
            translation_local = obj.matrix_world.inverted().to_3x3() @ translation_world
            
            # Apply axis constraints to local translation
            constrained_translation = self.axis_constraints.apply_constraint(translation_local)
            
            # Use new spatial relationship utilities for consistent orientation behavior
            if self.top_faces and self.top_verts:
                # Calculate rotation matrix using spatial relationship approach
                rotation_matrix = math_utils.calculate_spatial_relationship_rotation(
                    self.original_faces_centroid_local, constrained_translation,
                    self.pivot_point, self.initial_direction_to_pivot, obj.matrix_world
                )
                
                # Apply transformation to top vertices (translation + rotation)
                math_utils.apply_spatial_relationship_transformation(
                    self.top_verts, self.original_vert_positions,
                    constrained_translation, rotation_matrix, self.original_faces_centroid_local,
                    obj.matrix_world, weights=None
                )
                
                # Recalculate normals for the extrusion geometry to ensure proper orientation
                # This includes both the cap (top faces) and the sides
                extrusion_faces = self.top_faces + self.side_faces
                bmesh.ops.recalc_face_normals(self.bm, faces=extrusion_faces)
            
            # Update mesh
            bmesh.update_edit_mesh(obj.data)
            
        elif (event.type == 'LEFTMOUSE' and event.value == 'PRESS') or (event.type == 'RET' and event.value == 'PRESS'):
            # Confirm operation
            print("Super Extrude Modal: CONFIRMING operation")
            # Stop overlays (HUD disabled)
            if self.use_proportional:
                viewport_drawing.stop_proportional_circle_drawing()
            # Recalculate face normals for the entire mesh
            bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces)
            
            # Select the extruded cap faces
            for face in self.bm.faces:
                face.select = False
            for face in self.top_faces:
                face.select = True
            
            bmesh.update_edit_mesh(obj.data)
            return {'FINISHED'}
            
        elif (event.type == 'RIGHTMOUSE' and event.value == 'PRESS') or (event.type == 'ESC' and event.value == 'PRESS'):
            # Cancel operation - use Blender's undo system to restore original state
            print("Super Extrude Modal: CANCELLING operation")
            # Stop overlays (HUD disabled)
            if self.use_proportional:
                viewport_drawing.stop_proportional_circle_drawing()
            
            # Use Blender's undo system to restore the mesh to its state before the operation
            bpy.ops.ed.undo_push(message="Super Extrude Cancel")
            bpy.ops.ed.undo()
            
            return {'CANCELLED'}
        
        # Allow viewport navigation events to pass through
        elif event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} or \
             (event.type == 'MOUSEMOVE' and event.value == 'PRESS' and event.shift):
            # Pass through navigation events to allow viewport manipulation
            return {'PASS_THROUGH'}
        
        # For any other events, continue running modal
        return {'RUNNING_MODAL'}


def register():
    bpy.utils.register_class(MESH_OT_super_extrude_modal)


def unregister():
    bpy.utils.unregister_class(MESH_OT_super_extrude_modal)
