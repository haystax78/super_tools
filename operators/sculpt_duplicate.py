import bpy
import gpu
import math
from mathutils import Vector, Matrix
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader

PRECISION_FACTOR = 0.1
CENTER_CIRCLE_RADIUS = 10  # pixels
CENTER_CIRCLE_SEGMENTS = 24


def get_addon_prefs():
    """Get addon preferences."""
    addon = bpy.context.preferences.addons.get(__package__.rsplit('.', 1)[0])
    if addon:
        return addon.preferences
    return None


class SCULPT_OT_super_duplicate(bpy.types.Operator):
    """Duplicate sculpt object and interactively move geometry (origin stays fixed)"""
    bl_idname = "sculpt.super_duplicate"
    bl_label = "Super Duplicate"
    bl_options = {'REGISTER', 'UNDO'}

    MODE_MOVE = 'MOVE'
    MODE_ROTATE = 'ROTATE'
    MODE_SCALE = 'SCALE'

    duplicate: bpy.props.BoolProperty(
        name="Duplicate",
        description="Duplicate object before transforming. Set False to transform existing object",
        default=True
    )

    @classmethod
    def poll(cls, context):
        if context.area is None or context.area.type != 'VIEW_3D':
            return False
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            return False
        if obj.name not in context.view_layer.objects:
            return False
        return True

    def invoke(self, context, event):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'WARNING'}, "No active mesh object")
            return {'CANCELLED'}

        self._original_mode = context.mode
        self._original_obj = obj
        self._region = context.region
        self._rv3d = context.region_data
        self._did_duplicate = self.duplicate

        if self._original_mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except RuntimeError as e:
                self.report({'WARNING'}, f"Could not switch to Object mode: {e}")
                return {'CANCELLED'}

        # Push undo step before any modifications
        bpy.ops.ed.undo_push(message="Super Duplicate")

        if self.duplicate:
            try:
                bpy.ops.object.duplicate(linked=False)
            except RuntimeError as e:
                self.report({'WARNING'}, f"Duplicate failed: {e}")
                self._restore_mode()
                return {'CANCELLED'}

            self._new_obj = context.active_object
            if self._new_obj is None:
                self.report({'WARNING'}, "Duplicate created but not active")
                self._restore_mode()
                return {'CANCELLED'}
        else:
            self._new_obj = obj

        # Check if this is a flex mesh - use object transform instead of vertex manipulation
        self._is_flex_mesh = "flex_curve_data" in self._new_obj

        mesh = self._new_obj.data
        self._original_coords = [v.co.copy() for v in mesh.vertices]

        if len(self._original_coords) > 0:
            self._median_local = sum(self._original_coords, Vector()) / len(self._original_coords)
        else:
            self._median_local = Vector((0, 0, 0))

        self._current_coords = [v.copy() for v in self._original_coords]
        
        # For flex meshes, store original transform
        if self._is_flex_mesh:
            self._original_location = self._new_obj.location.copy()
            self._original_rotation = self._new_obj.rotation_euler.copy()
            self._original_scale = self._new_obj.scale.copy()
            self._current_location = self._original_location.copy()
            self._current_rotation = self._original_rotation.copy()
            self._current_scale = self._original_scale.copy()

        self._mode = self.MODE_MOVE
        self._initial_mouse = Vector((event.mouse_region_x, event.mouse_region_y))

        # Transform center (in local space) - can be adjusted with Space
        self._transform_center_local = self._median_local.copy()
        self._transform_center_initial = self._transform_center_local.copy()
        self._adjusting_center = False
        self._center_adjust_mouse = None

        # Setup draw handler for transform center visualization
        self._draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_transform_center, (context,), 'WINDOW', 'POST_VIEW'
        )

        # Cache hotkeys from preferences
        prefs = get_addon_prefs()
        if prefs:
            self._key_move = prefs.sd_key_move.upper()
            self._key_rotate = prefs.sd_key_rotate.upper()
            self._key_scale = prefs.sd_key_scale.upper()
            self._key_center = prefs.sd_key_adjust_center.upper()
            self._key_mirror_x = prefs.sd_key_mirror_x.upper()
            self._key_mirror_y = prefs.sd_key_mirror_y.upper()
            self._key_mirror_z = prefs.sd_key_mirror_z.upper()
        else:
            # Defaults if preferences not available
            self._key_move = 'G'
            self._key_rotate = 'R'
            self._key_scale = 'S'
            self._key_center = 'SPACE'
            self._key_mirror_x = 'X'
            self._key_mirror_y = 'Y'
            self._key_mirror_z = 'Z'

        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()

        mode_text = "Duplicate" if self.duplicate else "Transform"
        self.report({'INFO'}, f"{mode_text}: {self._key_move} | {self._key_rotate}/{self._key_scale} (hold) | {self._key_mirror_x}/{self._key_mirror_y}/{self._key_mirror_z}: Mirror | {self._key_center}: Adjust Center | Shift: Precision")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        # Handle adjust center key
        if event.type == self._key_center:
            if event.value == 'PRESS':
                self._adjusting_center = True
                self._center_adjust_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            elif event.value == 'RELEASE':
                self._adjusting_center = False
                # Commit current transform so subsequent operations don't jump
                self._commit_current_transform()
                # Reset initial mouse for current transform mode
                self._initial_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            if self._adjusting_center:
                self._update_transform_center(context, event)
            else:
                self._update_geometry(context, event)
            return {'RUNNING_MODAL'}

        elif event.type == self._key_move and event.value == 'PRESS':
            self._commit_current_transform()
            self._mode = self.MODE_MOVE
            self._initial_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
            self._transform_center_initial = self._transform_center_local.copy()
            self.report({'INFO'}, "Move mode")
            return {'RUNNING_MODAL'}

        elif event.type == self._key_rotate:
            if event.value == 'PRESS':
                self._commit_current_transform()
                self._mode = self.MODE_ROTATE
                self._initial_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
                self._transform_center_initial = self._transform_center_local.copy()
                self.report({'INFO'}, "Rotate mode (hold)")
                return {'RUNNING_MODAL'}
            elif event.value == 'RELEASE':
                self._commit_current_transform()
                self._mode = self.MODE_MOVE
                self._initial_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
                self.report({'INFO'}, "Move mode")
                return {'RUNNING_MODAL'}

        elif event.type == self._key_scale:
            if event.value == 'PRESS':
                self._commit_current_transform()
                self._mode = self.MODE_SCALE
                self._initial_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
                self._transform_center_initial = self._transform_center_local.copy()
                self.report({'INFO'}, "Scale mode (hold)")
                return {'RUNNING_MODAL'}
            elif event.value == 'RELEASE':
                self._commit_current_transform()
                self._mode = self.MODE_MOVE
                self._initial_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
                self.report({'INFO'}, "Move mode")
                return {'RUNNING_MODAL'}

        elif event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            self._cleanup_drawing()
            # Push final undo step with the result
            bpy.ops.ed.undo_push(message="Super Duplicate")
            self._restore_mode()
            self.report({'INFO'}, "Super Duplicate confirmed")
            return {'FINISHED'}

        elif event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._cleanup_drawing()
            self._cancel_operation(context)
            # Undo to restore state before operation
            bpy.ops.ed.undo()
            return {'CANCELLED'}

        elif event.type == self._key_mirror_x and event.value == 'PRESS':
            self._toggle_mirror_axis('X')
            return {'RUNNING_MODAL'}

        elif event.type == self._key_mirror_y and event.value == 'PRESS':
            self._toggle_mirror_axis('Y')
            return {'RUNNING_MODAL'}

        elif event.type == self._key_mirror_z and event.value == 'PRESS':
            self._toggle_mirror_axis('Z')
            return {'RUNNING_MODAL'}

        elif event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'}

    def _commit_current_transform(self):
        """Commit current transform to working coords before switching modes."""
        if self._is_flex_mesh:
            # Commit object transform
            self._current_location = self._new_obj.location.copy()
            self._current_rotation = self._new_obj.rotation_euler.copy()
            self._current_scale = self._new_obj.scale.copy()
        else:
            mesh = self._new_obj.data
            self._current_coords = [v.co.copy() for v in mesh.vertices]
            if len(self._current_coords) > 0:
                self._median_local = sum(self._current_coords, Vector()) / len(self._current_coords)
        # Also commit the transform center
        self._transform_center_initial = self._transform_center_local.copy()

    def _draw_transform_center(self, context):
        """Draw the transform center circle."""
        # Always draw the transform center

        # Get transform center in world space
        center_world = self._new_obj.matrix_world @ self._transform_center_local

        # Project to screen
        center_2d = view3d_utils.location_3d_to_region_2d(self._region, self._rv3d, center_world)
        if center_2d is None:
            return

        # Generate circle vertices in screen space, convert to 3D
        radius = CENTER_CIRCLE_RADIUS
        if self._adjusting_center:
            radius = CENTER_CIRCLE_RADIUS * 1.5  # Larger when adjusting

        vertices = []
        for i in range(CENTER_CIRCLE_SEGMENTS):
            angle = 2.0 * math.pi * i / CENTER_CIRCLE_SEGMENTS
            screen_x = center_2d.x + radius * math.cos(angle)
            screen_y = center_2d.y + radius * math.sin(angle)
            world_pos = view3d_utils.region_2d_to_location_3d(
                self._region, self._rv3d, (screen_x, screen_y), center_world
            )
            if world_pos:
                vertices.append((world_pos.x, world_pos.y, world_pos.z))

        if not vertices:
            return

        # Create indices for line loop
        indices = [(i, (i + 1) % len(vertices)) for i in range(len(vertices))]

        # Draw
        shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINES', {"pos": vertices}, indices=indices)

        gpu.state.line_width_set(2.0)
        gpu.state.blend_set('ALPHA')

        viewport = gpu.state.viewport_get()
        shader.uniform_float("viewportSize", (viewport[2], viewport[3]))
        shader.uniform_float("lineWidth", 2.0)

        # White color, brighter when adjusting
        alpha = 1.0 if self._adjusting_center else 0.6
        shader.uniform_float("color", (1.0, 1.0, 1.0, alpha))

        batch.draw(shader)
        gpu.state.blend_set('NONE')

    def _update_transform_center(self, context, event):
        """Update transform center position based on mouse movement."""
        current_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        mouse_delta = current_mouse - self._center_adjust_mouse

        if event.shift:
            mouse_delta *= PRECISION_FACTOR

        # Get current center in world space
        center_world = self._new_obj.matrix_world @ self._transform_center_local
        center_2d = view3d_utils.location_3d_to_region_2d(self._region, self._rv3d, center_world)
        if center_2d is None:
            return

        # New screen position
        new_2d = center_2d + mouse_delta

        # Unproject to 3D at same depth
        new_3d = view3d_utils.region_2d_to_location_3d(self._region, self._rv3d, new_2d, center_world)

        # Convert to local space
        mat_inv = self._new_obj.matrix_world.inverted()
        self._transform_center_local = mat_inv @ new_3d

        # Update mouse reference
        self._center_adjust_mouse = current_mouse
        context.area.tag_redraw()

    def _cleanup_drawing(self):
        """Remove draw handler."""
        if hasattr(self, '_draw_handler') and self._draw_handler:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handler, 'WINDOW')
            self._draw_handler = None

    def _toggle_mirror_axis(self, axis):
        """Toggle mirror modifier on specified axis (X, Y, or Z)."""
        axis_idx = {'X': 0, 'Y': 1, 'Z': 2}[axis]

        mirror_mod = None
        for mod in self._new_obj.modifiers:
            if mod.type == 'MIRROR':
                mirror_mod = mod
                break

        if mirror_mod is None:
            # Get or create the mirror empty
            mirror_empty = bpy.data.objects.get("sd_mirror_empty")
            if mirror_empty is None:
                mirror_empty = bpy.data.objects.new("sd_mirror_empty", None)
                mirror_empty.empty_display_type = 'PLAIN_AXES'
                mirror_empty.empty_display_size = 0.1
                mirror_empty.location = (0, 0, 0)
                bpy.context.collection.objects.link(mirror_empty)
            
            mirror_mod = self._new_obj.modifiers.new(name="SD Mirror", type='MIRROR')
            mirror_mod.mirror_object = mirror_empty
            mirror_mod.use_axis[0] = False
            mirror_mod.use_axis[1] = False
            mirror_mod.use_axis[2] = False
            mirror_mod.use_axis[axis_idx] = True
            self.report({'INFO'}, f"Mirror {axis} ON")
        else:
            current = mirror_mod.use_axis[axis_idx]
            mirror_mod.use_axis[axis_idx] = not current

            any_axis = mirror_mod.use_axis[0] or mirror_mod.use_axis[1] or mirror_mod.use_axis[2]
            if not any_axis:
                self._new_obj.modifiers.remove(mirror_mod)
                self.report({'INFO'}, f"Mirror removed")
            else:
                state = "ON" if not current else "OFF"
                self.report({'INFO'}, f"Mirror {axis} {state}")

    def _update_geometry(self, context, event):
        """Update vertex positions based on mouse movement."""
        if self._mode == self.MODE_MOVE:
            self._update_move(context, event)
        elif self._mode == self.MODE_ROTATE:
            self._update_rotate(context, event)
        elif self._mode == self.MODE_SCALE:
            self._update_scale(context, event)

    def _update_move(self, context, event):
        """Move geometry in screen space."""
        current_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        mouse_delta = current_mouse - self._initial_mouse

        if event.shift:
            mouse_delta *= PRECISION_FACTOR

        if self._is_flex_mesh:
            # For flex meshes, move the object itself
            obj_world = self._new_obj.matrix_world.translation
            obj_2d = view3d_utils.location_3d_to_region_2d(self._region, self._rv3d, obj_world)
            if obj_2d is None:
                return
            
            target_2d = obj_2d + mouse_delta
            target_3d = view3d_utils.region_2d_to_location_3d(self._region, self._rv3d, target_2d, obj_world)
            world_offset = target_3d - obj_world
            
            self._new_obj.location = self._current_location + world_offset
            context.area.tag_redraw()
        else:
            # Get median in world space and its screen position
            median_world = self._new_obj.matrix_world @ self._median_local
            median_2d = view3d_utils.location_3d_to_region_2d(self._region, self._rv3d, median_world)
            if median_2d is None:
                return

            # Target screen position
            target_2d = median_2d + mouse_delta

            # Unproject target back to 3D at same depth as median
            target_3d = view3d_utils.region_2d_to_location_3d(self._region, self._rv3d, target_2d, median_world)

            # World space offset
            world_offset = target_3d - median_world

            # Convert to local space
            mat_inv = self._new_obj.matrix_world.inverted()
            local_offset = mat_inv.to_3x3() @ world_offset

            mesh = self._new_obj.data
            for i, v in enumerate(mesh.vertices):
                v.co = self._current_coords[i] + local_offset

            # Move transform center along with mesh (same offset as vertices)
            self._transform_center_local = self._transform_center_initial + local_offset

            mesh.update()
            context.area.tag_redraw()

    def _update_rotate(self, context, event):
        """Rotate geometry around transform center."""
        current_mouse = Vector((event.mouse_region_x, event.mouse_region_y))

        if self._is_flex_mesh:
            # For flex meshes, rotate the object around the transform center
            center_world = self._new_obj.matrix_world @ self._transform_center_local
            center_2d = view3d_utils.location_3d_to_region_2d(self._region, self._rv3d, center_world)
            if center_2d is None:
                return
            
            initial_vec = self._initial_mouse - center_2d
            current_vec = current_mouse - center_2d
            
            if initial_vec.length < 1.0 or current_vec.length < 1.0:
                return
            
            angle = math.atan2(current_vec.y, current_vec.x) - math.atan2(initial_vec.y, initial_vec.x)
            
            if event.shift:
                angle *= PRECISION_FACTOR
            
            view_matrix = self._rv3d.view_matrix
            view_dir = Vector((view_matrix[2][0], view_matrix[2][1], view_matrix[2][2])).normalized()
            
            # Apply rotation to object around transform center
            rot_matrix = Matrix.Rotation(angle, 4, view_dir)
            
            # Rotate object orientation
            current_rot_matrix = self._current_rotation.to_matrix().to_4x4()
            new_rot_matrix = rot_matrix @ current_rot_matrix
            self._new_obj.rotation_euler = new_rot_matrix.to_euler()
            
            # Rotate object location around center
            obj_rel = self._current_location - center_world
            rotated_rel = rot_matrix @ obj_rel
            self._new_obj.location = center_world + rotated_rel
            
            context.area.tag_redraw()
        else:
            center_world = self._new_obj.matrix_world @ self._transform_center_local
            center_2d = view3d_utils.location_3d_to_region_2d(self._region, self._rv3d, center_world)
            if center_2d is None:
                return

            initial_vec = self._initial_mouse - center_2d
            current_vec = current_mouse - center_2d

            if initial_vec.length < 1.0 or current_vec.length < 1.0:
                return

            angle = math.atan2(current_vec.y, current_vec.x) - math.atan2(initial_vec.y, initial_vec.x)

            if event.shift:
                angle *= PRECISION_FACTOR

            view_matrix = self._rv3d.view_matrix
            view_dir = Vector((view_matrix[2][0], view_matrix[2][1], view_matrix[2][2])).normalized()

            rot_matrix = Matrix.Rotation(angle, 4, view_dir)

            mat_world = self._new_obj.matrix_world
            mat_inv = mat_world.inverted()

            mesh = self._new_obj.data
            for i, v in enumerate(mesh.vertices):
                local_pos = self._current_coords[i]
                world_pos = mat_world @ local_pos
                rel_pos = world_pos - center_world

                rotated_rel = rot_matrix @ rel_pos

                new_world = center_world + rotated_rel
                v.co = mat_inv @ new_world

            mesh.update()
            context.area.tag_redraw()

    def _update_scale(self, context, event):
        """Scale geometry around transform center."""
        current_mouse = Vector((event.mouse_region_x, event.mouse_region_y))

        if self._is_flex_mesh:
            # For flex meshes, scale the object around transform center
            center_world = self._new_obj.matrix_world @ self._transform_center_local
            center_2d = view3d_utils.location_3d_to_region_2d(self._region, self._rv3d, center_world)
            if center_2d is None:
                return
            
            initial_dist = (self._initial_mouse - center_2d).length
            current_dist = (current_mouse - center_2d).length
            
            if initial_dist < 1.0:
                return
            
            scale = current_dist / initial_dist
            
            if event.shift:
                scale = 1.0 + (scale - 1.0) * PRECISION_FACTOR
            
            # Scale object
            self._new_obj.scale = self._current_scale * scale
            
            # Scale object location relative to center
            obj_rel = self._current_location - center_world
            self._new_obj.location = center_world + obj_rel * scale
            
            context.area.tag_redraw()
        else:
            center_world = self._new_obj.matrix_world @ self._transform_center_local
            center_2d = view3d_utils.location_3d_to_region_2d(self._region, self._rv3d, center_world)
            if center_2d is None:
                return

            initial_dist = (self._initial_mouse - center_2d).length
            current_dist = (current_mouse - center_2d).length

            if initial_dist < 1.0:
                return

            scale = current_dist / initial_dist

            if event.shift:
                scale = 1.0 + (scale - 1.0) * PRECISION_FACTOR

            mesh = self._new_obj.data
            for i, v in enumerate(mesh.vertices):
                rel_pos = self._current_coords[i] - self._transform_center_local
                v.co = self._transform_center_local + rel_pos * scale

            mesh.update()
            context.area.tag_redraw()

    def _cancel_operation(self, context):
        """Cancel: delete duplicate or restore original positions."""
        if self._did_duplicate:
            if self._new_obj:
                bpy.data.objects.remove(self._new_obj, do_unlink=True)

            if self._original_obj and self._original_obj.name in context.view_layer.objects:
                self._original_obj.select_set(True)
                context.view_layer.objects.active = self._original_obj
        else:
            # Restore original state
            if self._new_obj and self._new_obj.name in context.view_layer.objects:
                if self._is_flex_mesh:
                    # Restore original transform for flex meshes
                    self._new_obj.location = self._original_location
                    self._new_obj.rotation_euler = self._original_rotation
                    self._new_obj.scale = self._original_scale
                else:
                    # Restore original vertex positions
                    mesh = self._new_obj.data
                    for i, v in enumerate(mesh.vertices):
                        v.co = self._original_coords[i]
                    mesh.update()

        self._restore_mode()
        self.report({'INFO'}, "Super Duplicate cancelled")

    def _restore_mode(self):
        """Restore to the original mode (typically Sculpt)."""
        try:
            if self._original_mode == 'SCULPT':
                bpy.ops.object.mode_set(mode='OBJECT')
                bpy.ops.sculpt.sculptmode_toggle()
            elif self._original_mode == 'EDIT_MESH':
                bpy.ops.object.mode_set(mode='EDIT')
            elif self._original_mode == 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            else:
                bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            pass


def menu_func(self, context):
    op = self.layout.operator(SCULPT_OT_super_duplicate.bl_idname, text="Super Duplicate")
    op.duplicate = True
    op = self.layout.operator(SCULPT_OT_super_duplicate.bl_idname, text="Super Transform")
    op.duplicate = False


classes = (
    SCULPT_OT_super_duplicate,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_sculpt.append(menu_func)


def unregister():
    bpy.types.VIEW3D_MT_sculpt.remove(menu_func)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
