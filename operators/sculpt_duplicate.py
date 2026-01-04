import bpy
import gpu
import math
import time
from array import array
from mathutils import Vector, Matrix
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader

try:
    import numpy as np
    HAS_NUMPY = True
except Exception:
    np = None
    HAS_NUMPY = False

PRECISION_FACTOR = 0.1
CENTER_CIRCLE_RADIUS = 10  # pixels
CENTER_CIRCLE_SEGMENTS = 24

# Profiling
PROFILE_ENABLED = False
_profile_times = {}
_profile_counts = {}
_profile_frame = 0

def profile_start(name):
    if PROFILE_ENABLED:
        _profile_times[name] = time.perf_counter()

def profile_end(name):
    global _profile_frame
    if PROFILE_ENABLED and name in _profile_times:
        elapsed = (time.perf_counter() - _profile_times[name]) * 1000  # ms
        if name not in _profile_counts:
            _profile_counts[name] = {'total': 0.0, 'count': 0, 'max': 0.0}
        _profile_counts[name]['total'] += elapsed
        _profile_counts[name]['count'] += 1
        _profile_counts[name]['max'] = max(_profile_counts[name]['max'], elapsed)

def profile_report():
    """Print profile report - call this periodically."""
    if not PROFILE_ENABLED:
        return

    global _profile_frame, _profile_counts
    _profile_frame += 1
    if _profile_frame % 30 == 0 and _profile_counts:
        parts = []
        for name, data in _profile_counts.items():
            if data['count'] > 0:
                avg = data['total'] / data['count']
                parts.append(f"{name}={avg:.1f}ms")
        if parts:
            print(f"[PROFILE] {', '.join(parts)}")


def profile_report_timer():
    """Print a profile report intended to be called from a TIMER event."""
    if not PROFILE_ENABLED or not _profile_counts:
        return

    parts = []
    for name, data in _profile_counts.items():
        if data['count'] > 0:
            avg = data['total'] / data['count']
            parts.append(f"{name}={avg:.1f}ms")

    if parts:
        print(f"[PROFILE] {', '.join(parts)}")


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

        self._start_matrix_world = self._new_obj.matrix_world.copy()
        self._start_location = self._new_obj.location.copy()
        self._start_rotation = self._new_obj.rotation_euler.copy()
        self._start_scale = self._new_obj.scale.copy()
        self._current_matrix_world = self._start_matrix_world.copy()

        # Check if this is a flex mesh - use object transform instead of vertex manipulation
        self._is_flex_mesh = "flex_curve_data" in self._new_obj

        mesh = self._new_obj.data
        self._original_coords = [v.co.copy() for v in mesh.vertices]
        self._original_coords_flat = array('f', [0.0]) * (len(mesh.vertices) * 3)
        mesh.vertices.foreach_get('co', self._original_coords_flat)

        if len(self._original_coords) > 0:
            self._median_local = sum(self._original_coords, Vector()) / len(self._original_coords)
        else:
            self._median_local = Vector((0, 0, 0))

        self._current_coords = [v.copy() for v in self._original_coords]
        self._current_coords_flat = array('f', self._original_coords_flat)
        
        self._current_location = self._start_location.copy()
        self._current_rotation = self._start_rotation.copy()
        self._current_scale = self._start_scale.copy()

        self._mode = self.MODE_MOVE
        self._initial_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self._constraint_axis = None

        # Transform center (in local space) - can be adjusted with Space
        self._transform_center_local = self._median_local.copy()
        self._transform_center_initial = self._transform_center_local.copy()
        self._pivot_world = self._current_matrix_world @ self._transform_center_local
        self._adjusting_center = False
        self._center_adjust_mouse = None

        # Setup draw handler for transform center visualization
        self._draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_transform_center, (context,), 'WINDOW', 'POST_VIEW'
        )

        # Profiling timer
        self._profile_timer = None
        if PROFILE_ENABLED:
            self._profile_timer = context.window_manager.event_timer_add(
                0.5, window=context.window
            )

        # Cache hotkeys from preferences
        prefs = get_addon_prefs()
        if prefs:
            self._key_move = prefs.sd_key_move.upper()
            self._key_rotate = prefs.sd_key_rotate.upper()
            self._key_scale = prefs.sd_key_scale.upper()
            self._key_center = prefs.sd_key_adjust_center.upper()
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
        self.report({'INFO'}, f"{mode_text}: {self._key_move} | {self._key_rotate}/{self._key_scale} (hold) | X/Y/Z: Axis Constraint | Alt+X/Y/Z: Mirror | {self._key_center}: Adjust Center | Shift: Precision")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        global _profile_counts, _profile_frame
        # Reset profiling on first modal call
        if PROFILE_ENABLED and not hasattr(self, '_profile_started'):
            self._profile_started = True
            _profile_counts.clear()
            _profile_frame = 0
            print("[PROFILE] Profiling started - move mouse to see stats")

        if PROFILE_ENABLED and event.type == 'TIMER':
            profile_report_timer()
            return {'RUNNING_MODAL'}
        
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
            profile_report()
            if self._adjusting_center:
                self._update_transform_center(context, event)
            else:
                self._update_geometry(context, event)
            return {'RUNNING_MODAL'}

        elif event.type in {'X', 'Y', 'Z'} and event.value == 'PRESS' and not event.alt:
            if self._constraint_axis == event.type:
                self._constraint_axis = None
                self.report({'INFO'}, "Axis Constraint: OFF")
            else:
                self._constraint_axis = event.type
                self.report({'INFO'}, f"Axis Constraint: {event.type}")
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
            if not self._is_flex_mesh:
                self._bake_object_transform_to_mesh()

            self._cleanup_drawing()
            bpy.ops.ed.undo_push(message="Super Duplicate")
            self._restore_mode()

            mode_text = "Super Duplicate" if self.duplicate else "Super Transform"
            self.report({'INFO'}, f"{mode_text} confirmed")
            return {'FINISHED'}

        elif event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._cleanup_drawing()
            self._cancel_operation(context)
            # Undo to restore state before operation
            bpy.ops.ed.undo()
            return {'CANCELLED'}

        elif event.type == self._key_mirror_x and event.value == 'PRESS' and event.alt:
            self._toggle_mirror_axis('X')
            return {'RUNNING_MODAL'}

        elif event.type == self._key_mirror_y and event.value == 'PRESS' and event.alt:
            self._toggle_mirror_axis('Y')
            return {'RUNNING_MODAL'}

        elif event.type == self._key_mirror_z and event.value == 'PRESS' and event.alt:
            self._toggle_mirror_axis('Z')
            return {'RUNNING_MODAL'}

        elif event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'}

    def _commit_current_transform(self):
        """Commit current transform to working coords before switching modes."""
        self._current_matrix_world = self._new_obj.matrix_world.copy()
        self._pivot_world = self._current_matrix_world @ self._transform_center_local
        # Also commit the transform center
        self._transform_center_initial = self._transform_center_local.copy()

    def _bake_object_transform_to_mesh(self):
        mesh = self._new_obj.data

        mat_delta = self._start_matrix_world.inverted() @ self._new_obj.matrix_world

        if HAS_NUMPY:
            base = np.frombuffer(self._original_coords_flat, dtype=np.float32)
            coords = base.reshape((-1, 3)).copy()
            ones = np.ones((coords.shape[0], 1), dtype=np.float32)
            coords4 = np.concatenate((coords, ones), axis=1)
            mat_np = np.array(mat_delta, dtype=np.float32)
            out = coords4 @ mat_np.T
            mesh.vertices.foreach_set('co', out[:, :3].astype(np.float32).ravel())
        else:
            coords = array('f', self._original_coords_flat)
            out = array('f', [0.0]) * len(coords)
            for i in range(0, len(coords), 3):
                v = Vector((coords[i], coords[i + 1], coords[i + 2], 1.0))
                r = mat_delta @ v
                out[i] = r.x
                out[i + 1] = r.y
                out[i + 2] = r.z
            mesh.vertices.foreach_set('co', out)

        mesh.update()
        self._new_obj.matrix_world = self._start_matrix_world
        self._current_matrix_world = self._start_matrix_world.copy()

    def _apply_local_offset_to_vertices(self, local_offset):
        """Apply a local-space offset to all vertices using bulk APIs."""
        mesh = self._new_obj.data

        if HAS_NUMPY:
            base = np.frombuffer(self._current_coords_flat, dtype=np.float32)
            coords = base.reshape((-1, 3)).copy()
            coords[:, 0] += local_offset.x
            coords[:, 1] += local_offset.y
            coords[:, 2] += local_offset.z
            mesh.vertices.foreach_set('co', coords.ravel())
        else:
            coords = array('f', self._current_coords_flat)
            ox = float(local_offset.x)
            oy = float(local_offset.y)
            oz = float(local_offset.z)
            for i in range(0, len(coords), 3):
                coords[i] += ox
                coords[i + 1] += oy
                coords[i + 2] += oz
            mesh.vertices.foreach_set('co', coords)

        mesh.update()

    def _apply_rotation_to_vertices(self, rot_matrix, center_world):
        """Apply a world-space rotation around center_world to all vertices."""
        mesh = self._new_obj.data

        mat_world = self._new_obj.matrix_world
        mw3 = mat_world.to_3x3()
        mw_t = mat_world.translation

        mw3_inv = mw3.inverted()
        rot3 = rot_matrix.to_3x3()

        if HAS_NUMPY:
            base = np.frombuffer(self._current_coords_flat, dtype=np.float32)
            local = base.reshape((-1, 3)).copy()

            mw3_np = np.array(mw3, dtype=np.float32)
            mw_t_np = np.array((mw_t.x, mw_t.y, mw_t.z), dtype=np.float32)
            center_np = np.array(
                (center_world.x, center_world.y, center_world.z),
                dtype=np.float32
            )
            rot_np = np.array(rot3, dtype=np.float32)
            mw3_inv_np = np.array(mw3_inv, dtype=np.float32)

            world = local @ mw3_np.T + mw_t_np
            rel = world - center_np
            rotated_rel = rel @ rot_np.T
            new_world = center_np + rotated_rel
            new_local = (new_world - mw_t_np) @ mw3_inv_np.T

            mesh.vertices.foreach_set('co', new_local.astype(np.float32).ravel())
        else:
            coords = array('f', self._current_coords_flat)
            for i in range(0, len(coords), 3):
                local_pos = Vector((coords[i], coords[i + 1], coords[i + 2]))
                world_pos = mw3 @ local_pos + mw_t
                rel = world_pos - center_world
                rotated_rel = rot3 @ rel
                new_world = center_world + rotated_rel
                new_local = mw3_inv @ (new_world - mw_t)
                coords[i] = new_local.x
                coords[i + 1] = new_local.y
                coords[i + 2] = new_local.z
            mesh.vertices.foreach_set('co', coords)

        mesh.update()

    def _apply_scale_to_vertices(self, scale):
        """Apply a local-space scale about transform center to all vertices."""
        mesh = self._new_obj.data
        cx = float(self._transform_center_local.x)
        cy = float(self._transform_center_local.y)
        cz = float(self._transform_center_local.z)
        s = float(scale)

        if HAS_NUMPY:
            base = np.frombuffer(self._current_coords_flat, dtype=np.float32)
            coords = base.reshape((-1, 3)).copy()
            coords[:, 0] = cx + (coords[:, 0] - cx) * s
            coords[:, 1] = cy + (coords[:, 1] - cy) * s
            coords[:, 2] = cz + (coords[:, 2] - cz) * s
            mesh.vertices.foreach_set('co', coords.ravel())
        else:
            coords = array('f', self._current_coords_flat)
            for i in range(0, len(coords), 3):
                coords[i] = cx + (coords[i] - cx) * s
                coords[i + 1] = cy + (coords[i + 1] - cy) * s
                coords[i + 2] = cz + (coords[i + 2] - cz) * s
            mesh.vertices.foreach_set('co', coords)

        mesh.update()

    def _draw_transform_center(self, context):
        """Draw the transform center circle."""
        profile_start('draw_handler')
        # Always draw the transform center

        # Get transform center in world space
        center_world = self._new_obj.matrix_world @ self._transform_center_local

        # Project to screen
        center_2d = view3d_utils.location_3d_to_region_2d(self._region, self._rv3d, center_world)
        if center_2d is None:
            profile_end('draw_handler')
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
            profile_end('draw_handler')
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
        profile_end('draw_handler')

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

        if hasattr(self, '_profile_timer') and self._profile_timer:
            try:
                bpy.context.window_manager.event_timer_remove(self._profile_timer)
            except Exception:
                pass
            self._profile_timer = None

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
        profile_start('update_geometry')
        if self._mode == self.MODE_MOVE:
            self._update_move(context, event)
        elif self._mode == self.MODE_ROTATE:
            self._update_rotate(context, event)
        elif self._mode == self.MODE_SCALE:
            self._update_scale(context, event)
        profile_end('update_geometry')

    def _update_move(self, context, event):
        """Move geometry in screen space."""
        profile_start('move_total')
        current_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        mouse_delta = current_mouse - self._initial_mouse

        if event.shift:
            mouse_delta *= PRECISION_FACTOR

        obj_world = self._new_obj.matrix_world.translation
        obj_2d = view3d_utils.location_3d_to_region_2d(
            self._region, self._rv3d, obj_world
        )
        if obj_2d is None:
            profile_end('move_total')
            return

        target_2d = obj_2d + mouse_delta
        target_3d = view3d_utils.region_2d_to_location_3d(
            self._region, self._rv3d, target_2d, obj_world
        )
        world_offset = target_3d - obj_world

        if self._constraint_axis == 'X':
            axis = Vector((1.0, 0.0, 0.0))
            world_offset = axis * world_offset.dot(axis)
        elif self._constraint_axis == 'Y':
            axis = Vector((0.0, 1.0, 0.0))
            world_offset = axis * world_offset.dot(axis)
        elif self._constraint_axis == 'Z':
            axis = Vector((0.0, 0.0, 1.0))
            world_offset = axis * world_offset.dot(axis)

        self._new_obj.matrix_world = Matrix.Translation(world_offset) @ \
            self._current_matrix_world
        context.area.tag_redraw()
        profile_end('move_total')

    def _update_rotate(self, context, event):
        """Rotate geometry around transform center."""
        current_mouse = Vector((event.mouse_region_x, event.mouse_region_y))

        center_2d = view3d_utils.location_3d_to_region_2d(
            self._region, self._rv3d, self._pivot_world
        )
        if center_2d is None:
            return

        initial_vec = self._initial_mouse - center_2d
        current_vec = current_mouse - center_2d

        if initial_vec.length < 1.0 or current_vec.length < 1.0:
            return

        angle = math.atan2(current_vec.y, current_vec.x) - \
            math.atan2(initial_vec.y, initial_vec.x)

        if event.shift:
            angle *= PRECISION_FACTOR

        if self._constraint_axis == 'X':
            axis = Vector((1.0, 0.0, 0.0))
        elif self._constraint_axis == 'Y':
            axis = Vector((0.0, 1.0, 0.0))
        elif self._constraint_axis == 'Z':
            axis = Vector((0.0, 0.0, 1.0))
        else:
            view_matrix = self._rv3d.view_matrix
            axis = Vector((view_matrix[2][0], view_matrix[2][1], view_matrix[2][2])).normalized()

        rot_matrix = Matrix.Rotation(angle, 4, axis)

        pivot_t = Matrix.Translation(self._pivot_world)
        pivot_t_inv = Matrix.Translation(-self._pivot_world)
        self._new_obj.matrix_world = pivot_t @ rot_matrix @ pivot_t_inv @ \
            self._current_matrix_world

        context.area.tag_redraw()

    def _update_scale(self, context, event):
        """Scale geometry around transform center."""
        current_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        center_2d = view3d_utils.location_3d_to_region_2d(
            self._region, self._rv3d, self._pivot_world
        )
        if center_2d is None:
            return

        initial_dist = (self._initial_mouse - center_2d).length
        current_dist = (current_mouse - center_2d).length

        if initial_dist < 1.0:
            return

        scale = current_dist / initial_dist

        if event.shift:
            scale = 1.0 + (scale - 1.0) * PRECISION_FACTOR

        pivot_t = Matrix.Translation(self._pivot_world)
        pivot_t_inv = Matrix.Translation(-self._pivot_world)
        if self._constraint_axis == 'X':
            scale_matrix = Matrix.Diagonal((scale, 1.0, 1.0, 1.0))
        elif self._constraint_axis == 'Y':
            scale_matrix = Matrix.Diagonal((1.0, scale, 1.0, 1.0))
        elif self._constraint_axis == 'Z':
            scale_matrix = Matrix.Diagonal((1.0, 1.0, scale, 1.0))
        else:
            scale_matrix = Matrix.Diagonal((scale, scale, scale, 1.0))
        self._new_obj.matrix_world = pivot_t @ scale_matrix @ pivot_t_inv @ \
            self._current_matrix_world

        context.area.tag_redraw()

    def _cancel_operation(self, context):
        """Cancel: delete duplicate or restore original positions."""
        if self._did_duplicate:
            if self._new_obj:
                bpy.data.objects.remove(self._new_obj, do_unlink=True)

            # Check if original object still exists before accessing it
            if self._original_obj and self._original_obj.name in bpy.data.objects:
                if self._original_obj.name in context.view_layer.objects:
                    self._original_obj.select_set(True)
                    context.view_layer.objects.active = self._original_obj
        else:
            # Restore original state
            # Check if object still exists before accessing it
            if self._new_obj and self._new_obj.name in bpy.data.objects and self._new_obj.name in context.view_layer.objects:
                self._new_obj.matrix_world = self._start_matrix_world

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
