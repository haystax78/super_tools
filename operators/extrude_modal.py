import bpy
import bmesh
import mathutils
import gpu
import blf
import colorsys
from math import radians
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader
from ..utils import math_utils, viewport_drawing, axis_constraints, view3d_utils, input_utils, bmesh_utils


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
    top_edges = []
    connector_edges = []
    top_verts = []
    side_faces = []
    initial_mouse = (0, 0)
    original_mesh_state = None
    use_proportional = False

    def _is_edge_extrusion_mode(self):
        """Return True when current stage originated from edge selection."""
        return bool(getattr(self, '_edge_selection_mode', False))

    def _get_view_normal_world(self, context):
        """Return active viewport forward normal in world space."""
        space_data = getattr(context, 'space_data', None)
        rv3d = space_data.region_3d if space_data else None
        if rv3d is None:
            return None
        view_normal = rv3d.view_rotation @ mathutils.Vector((0.0, 0.0, -1.0))
        if view_normal.length <= 1e-8:
            return None
        return view_normal.normalized()

    def _rotation_from_screen_space_vectors(self, context, source_world, target_world):
        """Rotate around view normal using vectors projected in screen plane."""
        if source_world.length <= 1e-8 or target_world.length <= 1e-8:
            return mathutils.Matrix.Identity(3)

        view_normal = self._get_view_normal_world(context)
        if view_normal is None:
            return mathutils.Matrix.Identity(3)

        source_flat = source_world - (view_normal * source_world.dot(view_normal))
        target_flat = target_world - (view_normal * target_world.dot(view_normal))

        if source_flat.length <= 1e-8 or target_flat.length <= 1e-8:
            return mathutils.Matrix.Identity(3)

        source_flat.normalize()
        target_flat.normalize()
        angle = source_flat.angle(target_flat)
        if angle <= 1e-8:
            return mathutils.Matrix.Identity(3)

        cross = source_flat.cross(target_flat)
        sign = 1.0 if cross.dot(view_normal) >= 0.0 else -1.0
        return mathutils.Matrix.Rotation(angle * sign, 3, view_normal)

    def _screen_space_signed_angle(
        self,
        context,
        center_world,
        source_world,
        target_world,
    ):
        """Return signed 2D angle from source to target around screen center."""
        source_len = source_world.length
        target_len = target_world.length
        if source_len <= 1e-8 or target_len <= 1e-8:
            return None

        ref_world_len = self._pixels_to_world_length(context, center_world, 96.0)
        if ref_world_len <= 1e-8:
            ref_world_len = max(source_len, target_len)
        if ref_world_len <= 1e-8:
            return None

        source_dir = source_world.normalized() * ref_world_len
        target_dir = target_world.normalized() * ref_world_len

        center_2d = self._world_to_screen(context, center_world)
        source_2d = self._world_to_screen(context, center_world + source_dir)
        target_2d = self._world_to_screen(context, center_world + target_dir)
        if center_2d is None or source_2d is None or target_2d is None:
            return None

        source_vec = mathutils.Vector((
            source_2d.x - center_2d.x,
            source_2d.y - center_2d.y,
        ))
        target_vec = mathutils.Vector((
            target_2d.x - center_2d.x,
            target_2d.y - center_2d.y,
        ))
        if source_vec.length <= 1e-8 or target_vec.length <= 1e-8:
            return None

        source_vec.normalize()
        target_vec.normalize()
        angle = source_vec.angle(target_vec)
        if angle <= 1e-8:
            return 0.0

        cross_z = (source_vec.x * target_vec.y) - (source_vec.y * target_vec.x)
        return angle if cross_z >= 0.0 else -angle

    def _calculate_edge_mode_rotation(self, context, target_center_world):
        """Return edge-mode rotation toward pivot in screen space."""
        target_to_pivot = self.pivot_point - target_center_world
        source_normal = self._resolve_edge_source_normal(
            context,
            target_center_world,
            target_to_pivot,
        )
        if source_normal.length <= 1e-8:
            return mathutils.Matrix.Identity(3)

        if target_to_pivot.length <= 1e-8:
            target_to_pivot = source_normal.copy()

        view_normal = self._get_view_normal_world(context)
        if view_normal is None:
            return mathutils.Matrix.Identity(3)

        signed_angle = self._screen_space_signed_angle(
            context,
            target_center_world,
            source_normal,
            target_to_pivot,
        )
        if signed_angle is not None:
            if abs(signed_angle) <= 1e-8:
                return mathutils.Matrix.Identity(3)
            return self._choose_best_screen_space_rotation(
                context,
                target_center_world,
                source_normal,
                target_to_pivot,
                signed_angle,
                view_normal,
            )

        return self._rotation_from_screen_space_vectors(
            context,
            source_normal,
            target_to_pivot,
        )

    def _resolve_edge_source_normal(
        self,
        context,
        center_world,
        target_to_pivot,
    ):
        """Return stable source normal for edge-mode screen-space rotation."""
        base = getattr(self, '_edge_initial_screen_normal_world', None)
        if base is None or base.length <= 1e-8:
            base = -getattr(
                self,
                'initial_direction_to_pivot',
                mathutils.Vector((0.0, 0.0, 1.0)),
            )
        if base.length <= 1e-8:
            return mathutils.Vector((0.0, 0.0, 1.0))

        candidate_a = base.normalized()
        candidate_b = -candidate_a

        winding_ref = getattr(
            self,
            '_edge_target_winding_normal_world',
            None,
        )
        if winding_ref is not None and winding_ref.length > 1e-8:
            winding_dir = winding_ref.normalized()
            if candidate_a.dot(winding_dir) < candidate_b.dot(winding_dir):
                candidate_a, candidate_b = candidate_b, candidate_a

        if target_to_pivot.length <= 1e-8:
            return candidate_a

        angle_a = self._screen_space_signed_angle(
            context,
            center_world,
            candidate_a,
            target_to_pivot,
        )
        angle_b = self._screen_space_signed_angle(
            context,
            center_world,
            candidate_b,
            target_to_pivot,
        )

        if angle_a is None and angle_b is None:
            chosen = candidate_a
        elif angle_b is None:
            chosen = candidate_a
        elif angle_a is None:
            chosen = candidate_b
        elif abs(angle_b) < abs(angle_a):
            chosen = candidate_b
        else:
            chosen = candidate_a
        return chosen

    def _choose_best_screen_space_rotation(
        self,
        context,
        center_world,
        source_world,
        target_world,
        signed_angle,
        view_normal,
    ):
        """Choose between +angle and -angle by projected alignment error."""
        rot_pos = mathutils.Matrix.Rotation(signed_angle, 3, view_normal)
        rot_neg = mathutils.Matrix.Rotation(-signed_angle, 3, view_normal)

        norm_source = source_world.normalized()
        cand_pos = (rot_pos @ norm_source).normalized()
        cand_neg = (rot_neg @ norm_source).normalized()

        residual_pos = self._screen_space_signed_angle(
            context,
            center_world,
            cand_pos,
            target_world,
        )
        residual_neg = self._screen_space_signed_angle(
            context,
            center_world,
            cand_neg,
            target_world,
        )

        err_pos = abs(residual_pos) if residual_pos is not None else float('inf')
        err_neg = abs(residual_neg) if residual_neg is not None else float('inf')

        chosen_rot = rot_neg if err_neg < err_pos else rot_pos
        chosen_normal = cand_neg if err_neg < err_pos else cand_pos

        if abs(err_pos - err_neg) <= 1e-4:
            prev_normal = getattr(self, '_edge_last_oriented_normal_world', None)
            if prev_normal is not None and prev_normal.length > 1e-8:
                prev_dir = prev_normal.normalized()
                if cand_neg.dot(prev_dir) > cand_pos.dot(prev_dir):
                    chosen_rot = rot_neg
                    chosen_normal = cand_neg
                else:
                    chosen_rot = rot_pos
                    chosen_normal = cand_pos

        self._edge_last_oriented_normal_world = chosen_normal.copy()
        return chosen_rot
    
    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH' and 
                context.object is not None and 
                context.object.type == 'MESH')

    def _remove_draw_handler(self):
        """Remove preview draw handler if present."""
        if getattr(self, "_stamp_draw_handler", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(
                self._stamp_draw_handler,
                'WINDOW',
            )
            self._stamp_draw_handler = None

    def _remove_cursor_help_handler(self):
        """Remove cursor-help draw handler if present."""
        if getattr(self, "_cursor_help_draw_handler", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(
                self._cursor_help_draw_handler,
                'WINDOW',
            )
            self._cursor_help_draw_handler = None

    def _stop_overlays(self):
        """Stop all modal overlays used by Super Extrude."""
        self._remove_draw_handler()
        self._remove_cursor_help_handler()
        viewport_drawing.stop_hud_drawing()

    def _get_cursor_help_slots(self):
        """Return cursor-help lines for Super Extrude."""
        hud_visible = bool(getattr(self, '_hud_help_visible', False))
        hud_status = 'Hide' if hud_visible else 'Show'
        mode_label = 'Edge' if self._is_edge_extrusion_mode() else 'Face'
        slots = [
            {
                'id': 'active_mode',
                'text': f"Mode: Super Extrude ({mode_label})",
                'color': (0.9, 0.9, 0.9),
            },
            {
                'id': 'hud_toggle',
                'text': f"{hud_status} Help [H]",
                'color': (0.7, 0.7, 0.7),
            },
        ]
        if not hud_visible:
            return slots

        slots.extend([
            {
                'id': 'confirm_cancel',
                'text': 'LMB/Enter: Confirm  RMB/Esc: Cancel',
                'color': (0.9, 0.9, 0.9),
            },
            {
                'id': 'drag_stamp',
                'text': 'LMB Drag: Interval Stamping',
                'color': (0.85, 0.85, 0.85),
            },
            {
                'id': 'wheel',
                'text': 'Wheel: Stamp Spacing',
                'color': (0.8, 0.8, 0.3),
            },
            {
                'id': 'constraints',
                'text': 'X/Y/Z: Axis Constraint',
                'color': (0.2, 0.8, 1.0),
            },
            {
                'id': 'precision',
                'text': 'Shift: Precision',
                'color': (0.7, 0.7, 0.7),
            },
        ])
        return slots

    def _draw_cursor_help(self):
        """Draw cursor-help text near mouse position."""
        mouse_pos = getattr(self, '_mouse_pos', None)
        if mouse_pos is None:
            return

        mx, my = float(mouse_pos.x), float(mouse_pos.y)
        offset_x = 20
        offset_y = 50
        line_height = 20
        font_size = 16
        font_id = 0

        slots = self._get_cursor_help_slots()
        if not slots:
            return

        try:
            visible_index = 0
            for slot in slots:
                red, green, blue = slot['color']
                blf.color(font_id, red, green, blue, 1.0)
                if slot['id'] == 'active_mode':
                    blf.size(font_id, int(font_size * 1.4))
                else:
                    blf.size(font_id, font_size)
                y_pos = my - offset_y - (visible_index * line_height)
                blf.position(font_id, mx + offset_x, y_pos, 0)
                blf.draw(font_id, slot['text'])
                visible_index += 1
        except Exception:
            pass

    def _get_current_top_centroid_world(self, obj):
        """Return current cap border-vertex centroid in world space."""
        border_edges = self._get_top_boundary_edges()
        border_verts = {vert for edge in border_edges for vert in edge.verts}
        if not border_verts:
            return obj.matrix_world.translation.copy()
        centroid = mathutils.Vector((0.0, 0.0, 0.0))
        for vert in border_verts:
            centroid += obj.matrix_world @ vert.co
        return centroid / len(border_verts)

    def _get_current_top_centroid_local(self):
        """Return current cap border-vertex centroid in local space."""
        border_edges = self._get_top_boundary_edges()
        border_verts = {vert for edge in border_edges for vert in edge.verts}
        if not border_verts:
            return None
        centroid = mathutils.Vector((0.0, 0.0, 0.0))
        for vert in border_verts:
            centroid += vert.co
        return centroid / len(border_verts)

    def _get_top_boundary_edges(self):
        """Return edges on the boundary of the top-face region."""
        if getattr(self, 'top_edges', None):
            return list(set(self.top_edges))

        top_face_set = set(self.top_faces)
        boundary_edges = []
        for face in self.top_faces:
            for edge in face.edges:
                linked_count = 0
                for linked_face in edge.link_faces:
                    if linked_face in top_face_set:
                        linked_count += 1
                if linked_count == 1:
                    boundary_edges.append(edge)
        return list(set(boundary_edges))

    def _world_to_screen(self, context, world_pos):
        """Project world position into region-space coordinates."""
        region = context.region
        rv3d = context.space_data.region_3d if context.space_data else None
        if not region or not rv3d:
            return None
        return location_3d_to_region_2d(region, rv3d, world_pos)

    def _pixels_to_world_length(self, context, world_pos, pixels):
        """Approximate world-space length for a screen-space pixel distance."""
        base = self._world_to_screen(context, world_pos)
        region = context.region
        rv3d = context.space_data.region_3d if context.space_data else None
        if base is None or not region or not rv3d:
            return 0.0

        target_2d = (base.x + pixels, base.y)
        target_world = view3d_utils.region_2d_to_location_3d(
            region,
            rv3d,
            target_2d,
            world_pos,
        )
        if target_world is None:
            return 0.0
        return (target_world - world_pos).length

    def _world_length_to_pixels(self, context, world_pos, world_length):
        """Approximate pixel length for a world-space distance."""
        world_per_pixel = self._pixels_to_world_length(context, world_pos, 1.0)
        if world_per_pixel <= 1e-8:
            return 0.0
        return world_length / world_per_pixel

    def _get_live_extrusion_max_edge_length_px(self, context, obj):
        """Return max current live extrusion edge length in pixels."""
        if not self.top_verts:
            return 0.0

        top_vert_set = set(self.top_verts)
        candidate_edges = set(getattr(self, 'connector_edges', []))
        if not candidate_edges:
            for face in self.side_faces:
                for edge in face.edges:
                    v0_in = edge.verts[0] in top_vert_set
                    v1_in = edge.verts[1] in top_vert_set
                    if v0_in != v1_in:
                        candidate_edges.add(edge)

        if not candidate_edges:
            return 0.0

        max_len_px = 0.0
        for edge in candidate_edges:
            w0 = obj.matrix_world @ edge.verts[0].co
            w1 = obj.matrix_world @ edge.verts[1].co
            s0 = self._world_to_screen(context, w0)
            s1 = self._world_to_screen(context, w1)

            if s0 is not None and s1 is not None:
                dx = s1.x - s0.x
                dy = s1.y - s0.y
                edge_len_px = (dx * dx + dy * dy) ** 0.5
            else:
                midpoint = (w0 + w1) * 0.5
                edge_len_px = self._world_length_to_pixels(
                    context,
                    midpoint,
                    (w1 - w0).length,
                )

            if edge_len_px > max_len_px:
                max_len_px = edge_len_px

        return max_len_px

    def _get_stamp_preview_visuals(self, context, obj):
        """Return eased alpha and color for stamp preview."""
        threshold_px = getattr(self, 'max_edge_length_px', 0.0)
        if threshold_px <= 1e-8:
            return 0.0, (0.2, 1.0, 0.25)

        live_max_px = self._get_live_extrusion_max_edge_length_px(context, obj)
        ratio = live_max_px / threshold_px
        ratio = max(0.0, min(1.0, ratio))

        # Slower ramp for a softer visual lead-in.
        eased = ratio ** 8.0
        alpha = eased
        saturation = 0.15 + (0.85 * eased)
        red, green, blue = colorsys.hsv_to_rgb(0.33, saturation, 1.0)
        return alpha, (red, green, blue)

    def _get_preview_offset_world(self, context, current_center, last_stamp_center):
        """Compute preview offset using screen-space threshold."""
        region = context.region
        rv3d = context.space_data.region_3d if context.space_data else None
        if not region or not rv3d:
            return mathutils.Vector((0.0, 0.0, 0.0))

        current_2d = self._world_to_screen(context, current_center)
        last_2d = self._world_to_screen(context, last_stamp_center)

        if current_2d is not None and last_2d is not None:
            direction_2d = mathutils.Vector((
                current_2d.x - last_2d.x,
                current_2d.y - last_2d.y,
            ))
            if direction_2d.length <= 1e-6:
                direction_2d = getattr(
                    self,
                    '_last_move_screen_dir',
                    mathutils.Vector((1.0, 0.0)),
                )

            if direction_2d.length > 1e-6:
                direction_2d.normalize()
                target_2d = (
                    last_2d.x + direction_2d.x * self.max_edge_length_px,
                    last_2d.y + direction_2d.y * self.max_edge_length_px,
                )
                target_world = view3d_utils.region_2d_to_location_3d(
                    region,
                    rv3d,
                    target_2d,
                    current_center,
                )
                if target_world is not None:
                    return target_world - current_center

        fallback_dir = current_center - last_stamp_center
        if fallback_dir.length <= 1e-8:
            fallback_dir = getattr(
                self,
                '_last_move_world_dir',
                mathutils.Vector((0.0, 0.0, 1.0)),
            )
        if fallback_dir.length <= 1e-8:
            return mathutils.Vector((0.0, 0.0, 0.0))

        fallback_world_len = self._pixels_to_world_length(
            context,
            current_center,
            self.max_edge_length_px,
        )
        if fallback_world_len <= 0.0:
            return mathutils.Vector((0.0, 0.0, 0.0))
        return fallback_dir.normalized() * fallback_world_len

    def _get_next_stamp_target_world(
        self,
        context,
        current_center,
        last_stamp_center,
    ):
        """Return exact world-space target at one threshold step."""
        current_2d = self._world_to_screen(context, current_center)
        last_2d = self._world_to_screen(context, last_stamp_center)

        if current_2d is not None and last_2d is not None:
            direction_2d = mathutils.Vector((
                current_2d.x - last_2d.x,
                current_2d.y - last_2d.y,
            ))
            if direction_2d.length <= 1e-6:
                return None
            direction_2d.normalize()
            target_2d = (
                last_2d.x + direction_2d.x * self.max_edge_length_px,
                last_2d.y + direction_2d.y * self.max_edge_length_px,
            )
            region = context.region
            rv3d = context.space_data.region_3d if context.space_data else None
            if not region or not rv3d:
                return None
            return view3d_utils.region_2d_to_location_3d(
                region,
                rv3d,
                target_2d,
                current_center,
            )

        direction_3d = current_center - last_stamp_center
        if direction_3d.length <= 1e-8:
            return None
        world_step = self._pixels_to_world_length(
            context,
            current_center,
            self.max_edge_length_px,
        )
        if world_step <= 0.0:
            return None
        return last_stamp_center + direction_3d.normalized() * world_step

    def _get_stamp_preview_segments(self, obj):
        """Build world-space line segments for green stamp loop preview."""
        if not self.top_verts:
            return []

        boundary_edges = self._get_top_boundary_edges()
        if not boundary_edges:
            return []

        current_center = self._get_current_top_centroid_world(obj)
        last_stamp_center = getattr(self, '_last_stamp_world_centroid', None)
        if last_stamp_center is None:
            last_stamp_center = current_center

        context = bpy.context
        offset_world = self._get_preview_offset_world(
            context,
            current_center,
            last_stamp_center,
        )
        preview_center = current_center + offset_world

        edge_preview_rotation = mathutils.Matrix.Identity(3)
        if self._is_edge_extrusion_mode():
            current_edge_rotation = self._calculate_edge_mode_rotation(
                context,
                current_center,
            )
            preview_edge_rotation = self._calculate_edge_mode_rotation(
                context,
                preview_center,
            )
            edge_preview_rotation = (
                preview_edge_rotation @ current_edge_rotation.transposed()
            )

        segments = []
        for edge in boundary_edges:
            v0_world = obj.matrix_world @ edge.verts[0].co
            v1_world = obj.matrix_world @ edge.verts[1].co

            if self._is_edge_extrusion_mode():
                v0 = (
                    edge_preview_rotation @ (v0_world - current_center)
                ) + preview_center
                v1 = (
                    edge_preview_rotation @ (v1_world - current_center)
                ) + preview_center
            else:
                v0 = v0_world + offset_world
                v1 = v1_world + offset_world
            segments.append((v0, v1))
        return segments

    def _draw_stamp_preview(self):
        """Draw green edge-loop style preview for stamp interval."""
        obj = bpy.context.edit_object
        if not obj or obj.type != 'MESH':
            return

        context = bpy.context
        alpha, color_rgb = self._get_stamp_preview_visuals(context, obj)
        if alpha <= 0.0:
            return

        segments = self._get_stamp_preview_segments(obj)
        if not segments:
            return

        vertices = []
        indices = []
        for i, segment in enumerate(segments):
            v0, v1 = segment
            vertices.append((v0.x, v0.y, v0.z))
            vertices.append((v1.x, v1.y, v1.z))
            indices.append((i * 2, i * 2 + 1))

        shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        batch = batch_for_shader(
            shader,
            'LINES',
            {"pos": vertices},
            indices=indices,
        )

        gpu.state.blend_set('ALPHA')
        gpu.state.line_width_set(2.0)
        viewport = gpu.state.viewport_get()
        shader.uniform_float("viewportSize", (viewport[2], viewport[3]))
        shader.uniform_float("lineWidth", 2.0)
        shader.uniform_float(
            "color",
            (color_rgb[0], color_rgb[1], color_rgb[2], alpha),
        )
        batch.draw(shader)
        gpu.state.blend_set('NONE')

    def _confirm_current_extrude_state(self, obj):
        """Select current top geometry and recalculate normals."""
        extrusion_faces = [
            face for face in (self.top_faces + self.side_faces)
            if face.is_valid
        ]
        if extrusion_faces:
            bmesh.ops.recalc_face_normals(self.bm, faces=extrusion_faces)
            self._enforce_extrusion_winding(obj, extrusion_faces)

        for edge in self.bm.edges:
            edge.select = False
        for face in self.bm.faces:
            face.select = False

        if self.top_edges:
            for edge in self.top_edges:
                edge.select = True
        for face in self.top_faces:
            face.select = True

        if self.top_edges and not self.top_faces:
            for vert in self.bm.verts:
                vert.select = False
            for edge in self.top_edges:
                edge.verts[0].select = True
                edge.verts[1].select = True

        bmesh.update_edit_mesh(obj.data)

    def _enforce_extrusion_winding(self, obj, extrusion_faces):
        """Keep extrusion face winding aligned with initial cap normal."""
        valid_faces = [face for face in extrusion_faces if face.is_valid]
        if not valid_faces:
            return

        if self._is_edge_extrusion_mode():
            sample_faces = [
                face for face in self.side_faces
                if face.is_valid and face in valid_faces
            ]
        else:
            sample_faces = [
                face for face in self.top_faces
                if face.is_valid and face in valid_faces
            ]
        if not sample_faces:
            sample_faces = valid_faces

        obj_rot = obj.matrix_world.to_3x3()
        avg_normal_world = mathutils.Vector((0.0, 0.0, 0.0))
        for face in sample_faces:
            face_normal_world = obj_rot @ face.normal
            if face_normal_world.length <= 1e-8:
                continue
            avg_normal_world += face_normal_world.normalized()

        if avg_normal_world.length <= 1e-8:
            return

        current_normal = avg_normal_world.normalized()

        if self._is_edge_extrusion_mode():
            prev_normal = getattr(self, '_edge_last_extrusion_normal_world', None)
            ref_normal = None
            if prev_normal is not None and prev_normal.length > 1e-8:
                ref_normal = prev_normal.normalized()
            else:
                target_normal = getattr(
                    self,
                    '_edge_target_winding_normal_world',
                    None,
                )
                if target_normal is not None and target_normal.length > 1e-8:
                    ref_normal = target_normal.normalized()

            if ref_normal is not None and current_normal.dot(ref_normal) < 0.0:
                for face in valid_faces:
                    face.normal_flip()
                self.bm.normal_update()
                current_normal = -current_normal
            self._edge_last_extrusion_normal_world = current_normal.copy()
            return

        ref_normal = getattr(self, 'initial_top_normal_world', None)
        if ref_normal is None or ref_normal.length <= 1e-8:
            return

        if current_normal.dot(ref_normal.normalized()) < 0.0:
            for face in valid_faces:
                face.normal_flip()
            self.bm.normal_update()

    def _snap_current_stage_to_world_center(
        self,
        obj,
        target_center_world,
        target_tangent_world=None,
    ):
        """Snap current stage to a specific world-space centroid."""
        if not self.top_verts:
            return

        target_center_local = obj.matrix_world.inverted() @ target_center_world
        constrained_translation = (
            target_center_local - self.original_faces_centroid_local
        )
        if self._is_edge_extrusion_mode():
            rotation_matrix = self._calculate_edge_mode_rotation(
                bpy.context,
                target_center_world,
            )
        elif target_tangent_world is not None and target_tangent_world.length > 1e-8:
            rotation_matrix = self._calculate_path_perpendicular_rotation(
                target_tangent_world,
            )
        else:
            rotation_matrix = math_utils.calculate_spatial_relationship_rotation(
                self.original_faces_centroid_local,
                constrained_translation,
                self.pivot_point,
                self.initial_direction_to_pivot,
                obj.matrix_world,
            )
        math_utils.apply_spatial_relationship_transformation(
            self.top_verts,
            self.original_vert_positions,
            constrained_translation,
            rotation_matrix,
            self.original_faces_centroid_local,
            obj.matrix_world,
            weights=None,
        )
        extrusion_faces = self.top_faces + self.side_faces
        bmesh.ops.recalc_face_normals(self.bm, faces=extrusion_faces)
        self._enforce_extrusion_winding(obj, extrusion_faces)
        bmesh.update_edit_mesh(obj.data)

    def _calculate_path_perpendicular_rotation(self, target_direction_world):
        """Return world-space rotation aligning cap normal to path tangent."""
        if target_direction_world.length <= 1e-8:
            return mathutils.Matrix.Identity(3)

        target_dir = target_direction_world.normalized()
        initial_normal = getattr(self, 'initial_top_normal_world', None)
        if initial_normal is None or initial_normal.length <= 1e-8:
            return mathutils.Matrix.Identity(3)
        initial_normal = initial_normal.normalized()

        dot = max(-1.0, min(1.0, initial_normal.dot(target_dir)))
        if dot >= 1.0 - 1e-8:
            return mathutils.Matrix.Identity(3)

        if dot <= -1.0 + 1e-8:
            fallback_axis = initial_normal.cross(mathutils.Vector((1.0, 0.0, 0.0)))
            if fallback_axis.length <= 1e-8:
                fallback_axis = initial_normal.cross(mathutils.Vector((0.0, 1.0, 0.0)))
            if fallback_axis.length <= 1e-8:
                return mathutils.Matrix.Identity(3)
            return mathutils.Matrix.Rotation(
                radians(180.0),
                3,
                fallback_axis.normalized(),
            )

        rot_axis = initial_normal.cross(target_dir)
        if rot_axis.length <= 1e-8:
            return mathutils.Matrix.Identity(3)

        angle = initial_normal.angle(target_dir)
        return mathutils.Matrix.Rotation(angle, 3, rot_axis.normalized())

    def _rotation_from_normal_to_direction(self, source_normal_world, target_dir_world):
        """Return world rotation from source normal to target direction."""
        if source_normal_world.length <= 1e-8 or target_dir_world.length <= 1e-8:
            return mathutils.Matrix.Identity(3)

        source = source_normal_world.normalized()
        target = target_dir_world.normalized()
        dot = max(-1.0, min(1.0, source.dot(target)))

        if dot >= 1.0 - 1e-8:
            return mathutils.Matrix.Identity(3)

        if dot <= -1.0 + 1e-8:
            axis = source.cross(mathutils.Vector((1.0, 0.0, 0.0)))
            if axis.length <= 1e-8:
                axis = source.cross(mathutils.Vector((0.0, 1.0, 0.0)))
            if axis.length <= 1e-8:
                return mathutils.Matrix.Identity(3)
            return mathutils.Matrix.Rotation(radians(180.0), 3, axis.normalized())

        axis = source.cross(target)
        if axis.length <= 1e-8:
            return mathutils.Matrix.Identity(3)
        angle = source.angle(target)
        return mathutils.Matrix.Rotation(angle, 3, axis.normalized())

    def _apply_pending_stamp_correction(self, obj, outgoing_tangent_world):
        """Reorient prior committed stamp once next tangent is known."""
        pending = getattr(self, '_pending_stamp_correction', None)
        if not pending:
            return

        incoming = pending.get('incoming_tangent_world')
        ring_verts = pending.get('verts', [])
        centroid_local = pending.get('centroid_local')
        source_normal = pending.get('normal_world')
        self._pending_stamp_correction = None

        edge_mode = self._is_edge_extrusion_mode()

        if (
            incoming is None
            or incoming.length <= 1e-8
            or outgoing_tangent_world is None
            or outgoing_tangent_world.length <= 1e-8
            or centroid_local is None
            or not ring_verts
        ):
            return

        if (
            not edge_mode
            and (source_normal is None or source_normal.length <= 1e-8)
        ):
            return

        blended = incoming.normalized() + outgoing_tangent_world.normalized()
        if blended.length <= 1e-8:
            target_dir = outgoing_tangent_world.normalized()
        else:
            target_dir = blended.normalized()

        if edge_mode:
            rotation_world = self._rotation_from_screen_space_vectors(
                bpy.context,
                incoming,
                target_dir,
            )
        else:
            rotation_world = self._rotation_from_normal_to_direction(
                source_normal,
                target_dir,
            )
        if rotation_world == mathutils.Matrix.Identity(3):
            return

        obj_rot = obj.matrix_world.to_quaternion().to_matrix()
        obj_rot_inv = obj_rot.transposed()
        rotation_local = obj_rot_inv @ rotation_world @ obj_rot

        for vert in ring_verts:
            if not vert.is_valid:
                continue
            pos = vert.co - centroid_local
            vert.co = (rotation_local @ pos) + centroid_local

        bmesh.update_edit_mesh(obj.data)

    def _commit_stamp_and_continue(
        self,
        context,
        event,
        obj,
        outgoing_tangent_world=None,
    ):
        """Commit current stage and start the next stage from selected cap."""
        pending_centroid_local = self._get_current_top_centroid_local()
        if pending_centroid_local is None:
            pending_centroid_local = mathutils.Vector((0.0, 0.0, 0.0))
            for vert in self.top_verts:
                pending_centroid_local += vert.co
            if self.top_verts:
                pending_centroid_local /= len(self.top_verts)

        border_centroid_local = self._get_current_top_centroid_local()
        if border_centroid_local is not None:
            pending_centroid_local = border_centroid_local
        if self.top_faces:
            pending_normal_world = math_utils.calculate_faces_average_normal(
                self.top_faces,
                obj.matrix_world,
            )
        else:
            pending_normal_world = -self.initial_direction_to_pivot
        pending_verts = list(self.top_verts)
        pending_faces = list(self.top_faces)
        pending_edges = list(self.top_edges)
        pending_centroid_world = obj.matrix_world @ pending_centroid_local
        pending_incoming = None
        if outgoing_tangent_world is not None and outgoing_tangent_world.length > 1e-8:
            pending_incoming = outgoing_tangent_world.normalized()

        self._confirm_current_extrude_state(obj)
        ok = self._setup_extrusion_from_selected_faces(
            context,
            (event.mouse_region_x, event.mouse_region_y),
            delete_source_faces=True,
        )
        if ok:
            self._last_stamp_world_centroid = self._get_current_top_centroid_world(obj)
            if self._is_edge_extrusion_mode():
                self.pivot_point = pending_centroid_world.copy()
                current_center_world = self._get_current_top_centroid_world(obj)
                dir_to_pivot = self.pivot_point - current_center_world
                if dir_to_pivot.length > 1e-8:
                    self.initial_direction_to_pivot = dir_to_pivot.normalized()
            elif pending_normal_world.length > 1e-8:
                self.initial_top_normal_world = pending_normal_world.normalized()
                extrusion_faces = self.top_faces + self.side_faces
                self._enforce_extrusion_winding(obj, extrusion_faces)
                bmesh.update_edit_mesh(obj.data)
            self._previous_committed_stage = {
                'top_faces': pending_faces,
                'top_edges': pending_edges,
                'top_verts': pending_verts,
                'normal_world': pending_normal_world.copy(),
            }
            self._pending_stamp_correction = {
                'verts': pending_verts,
                'centroid_local': pending_centroid_local.copy(),
                'normal_world': pending_normal_world.copy(),
                'incoming_tangent_world': pending_incoming,
            }
            if pending_incoming is not None:
                self._last_move_world_dir = pending_incoming.copy()

    def _setup_extrusion_from_selected_faces(
        self,
        context,
        mouse_pos,
        delete_source_faces=True,
    ):
        """Create one super-extrude stage from selected faces or edges."""
        obj = context.edit_object
        if obj is None:
            self.report({'ERROR'}, "No active mesh object")
            return False

        self.bm = bmesh.from_edit_mesh(obj.data)
        selected_faces = [f for f in self.bm.faces if f.select]
        selected_edges = [e for e in self.bm.edges if e.select]
        if not selected_faces and not selected_edges:
            self.report({'ERROR'}, "No faces or edges selected")
            return False

        self.original_faces = [f for f in selected_faces]
        self.initial_mouse = mouse_pos
        self.precision = input_utils.PrecisionMouseState(scale=0.3)
        self.precision.reset(self.initial_mouse)

        self.top_faces = []
        self.top_edges = []
        self.connector_edges = []
        self._edge_selection_mode = False
        self._edge_target_winding_normal_world = None

        if selected_faces:
            selected_faces_centroid_world = math_utils.calculate_faces_centroid(
                selected_faces,
                obj.matrix_world,
            )
            original_border_edges = bmesh_utils.get_border_edges(self.original_faces)
            border_verts = {vert for edge in original_border_edges for vert in edge.verts}
            if border_verts:
                pivot_point_world = mathutils.Vector((0.0, 0.0, 0.0))
                for vert in border_verts:
                    pivot_point_world += obj.matrix_world @ vert.co
                pivot_point_world /= len(border_verts)
            else:
                pivot_point_world = selected_faces_centroid_world.copy()

            try:
                ret = bmesh.ops.extrude_face_region(self.bm, geom=selected_faces)
            except Exception as exc:
                self.report({'ERROR'}, f"Extrude operation failed: {str(exc)}")
                return False

            if 'geom' not in ret:
                self.report({'ERROR'}, "Extrude operation returned no geometry")
                return False

            if delete_source_faces:
                bmesh.ops.delete(self.bm, geom=selected_faces, context='FACES')

            extruded_geom = ret['geom']
            extruded_verts = [
                elem for elem in extruded_geom if isinstance(elem, bmesh.types.BMVert)
            ]
            extruded_faces = [
                elem for elem in extruded_geom if isinstance(elem, bmesh.types.BMFace)
            ]

            self.top_faces = bmesh_utils.identify_top_faces(
                extruded_faces,
                original_border_edges,
            )

            self.top_edges = self._get_top_boundary_edges()
            extruded_vert_set = set(extruded_verts)
            self.side_faces = []
            for face in self.bm.faces:
                if face in self.top_faces:
                    continue
                face_verts = set(face.verts)
                if face_verts.intersection(extruded_vert_set):
                    self.side_faces.append(face)

            self.top_verts = list(set(v for f in self.top_faces for v in f.verts))
            top_vert_set = set(self.top_verts)
            self.connector_edges = []
            for face in self.side_faces:
                for edge in face.edges:
                    v0_in = edge.verts[0] in top_vert_set
                    v1_in = edge.verts[1] in top_vert_set
                    if v0_in != v1_in:
                        self.connector_edges.append(edge)

        else:
            self._edge_selection_mode = True
            selected_edge_verts = {
                vert for edge in selected_edges for vert in edge.verts
            }
            source_face_normal_world = mathutils.Vector((0.0, 0.0, 0.0))
            for edge in selected_edges:
                for face in edge.link_faces:
                    face_normal_world = obj.matrix_world.to_3x3() @ face.normal
                    if face_normal_world.length <= 1e-8:
                        continue
                    source_face_normal_world += face_normal_world.normalized()
            if source_face_normal_world.length > 1e-8:
                self._edge_target_winding_normal_world = (
                    source_face_normal_world.normalized()
                )
            pivot_point_world = obj.matrix_world.translation.copy()

            try:
                ret = bmesh.ops.extrude_edge_only(self.bm, edges=selected_edges)
            except Exception as exc:
                self.report({'ERROR'}, f"Extrude operation failed: {str(exc)}")
                return False

            if 'geom' not in ret:
                self.report({'ERROR'}, "Extrude operation returned no geometry")
                return False

            extruded_geom = ret['geom']
            extruded_verts = [
                elem for elem in extruded_geom if isinstance(elem, bmesh.types.BMVert)
            ]
            extruded_edges = [
                elem for elem in extruded_geom if isinstance(elem, bmesh.types.BMEdge)
            ]

            extruded_vert_set = set(extruded_verts)
            self.top_edges = [
                edge for edge in extruded_edges
                if edge.verts[0] in extruded_vert_set
                and edge.verts[1] in extruded_vert_set
            ]
            self.connector_edges = [
                edge for edge in extruded_edges
                if (edge.verts[0] in extruded_vert_set)
                != (edge.verts[1] in extruded_vert_set)
            ]

            self.top_faces = []
            self.side_faces = []
            for face in self.bm.faces:
                face_verts = set(face.verts)
                if face_verts.intersection(extruded_vert_set):
                    if face_verts.issubset(extruded_vert_set):
                        self.top_faces.append(face)
                    else:
                        self.side_faces.append(face)

            self.top_verts = list({vert for edge in self.top_edges for vert in edge.verts})
            if not self.top_verts:
                self.top_verts = list(extruded_vert_set)

            base_verts = set()
            for edge in self.connector_edges:
                v0, v1 = edge.verts
                if v0 in extruded_vert_set and v1 not in extruded_vert_set:
                    base_verts.add(v1)
                elif v1 in extruded_vert_set and v0 not in extruded_vert_set:
                    base_verts.add(v0)

            if base_verts:
                pivot_point_world = mathutils.Vector((0.0, 0.0, 0.0))
                for vert in base_verts:
                    pivot_point_world += obj.matrix_world @ vert.co
                pivot_point_world /= len(base_verts)
            elif selected_edge_verts:
                pivot_point_world = mathutils.Vector((0.0, 0.0, 0.0))
                for vert in selected_edge_verts:
                    pivot_point_world += obj.matrix_world @ vert.co
                pivot_point_world /= len(selected_edge_verts)

        self.original_top_verts_positions = [v.co.copy() for v in self.top_verts]
        self.original_vert_positions = {v: v.co.copy() for v in self.top_verts}
        self._edge_initial_screen_normal_world = None
        self._edge_effective_source_normal_world = None
        self._edge_last_oriented_normal_world = None

        self.pivot_point = pivot_point_world
        self.original_faces_centroid_local = self._get_current_top_centroid_local()
        if self.original_faces_centroid_local is None:
            self.original_faces_centroid_local = mathutils.Vector((0.0, 0.0, 0.0))
            for vert in self.top_verts:
                self.original_faces_centroid_local += vert.co
            if self.top_verts:
                self.original_faces_centroid_local /= len(self.top_verts)

        if self.top_faces:
            avg_normal = math_utils.calculate_faces_average_normal(
                self.top_faces,
                obj.matrix_world,
            )
        else:
            center_world = obj.matrix_world @ self.original_faces_centroid_local
            avg_normal = center_world - self.pivot_point
            if avg_normal.length <= 1e-8:
                avg_normal = mathutils.Vector((0.0, 0.0, 1.0))
            else:
                avg_normal.normalize()
        self.initial_top_normal_world = avg_normal.normalized()
        if self.top_faces:
            small_offset = 0.001
            offset_vector_local = (
                obj.matrix_world.inverted().to_3x3() @ (avg_normal * small_offset)
            )
            for vert in self.top_verts:
                vert.co += offset_vector_local
                self.original_vert_positions[vert] = vert.co.copy()

        self.original_faces_centroid_local = self._get_current_top_centroid_local()
        if self.original_faces_centroid_local is None:
            self.original_faces_centroid_local = mathutils.Vector((0.0, 0.0, 0.0))
            for vert in self.top_verts:
                self.original_faces_centroid_local += vert.co
            if self.top_verts:
                self.original_faces_centroid_local /= len(self.top_verts)
        self.original_faces_centroid = (
            obj.matrix_world @ self.original_faces_centroid_local
        )

        initial_dir = self.pivot_point - self.original_faces_centroid
        if initial_dir.length > 1e-8:
            self.initial_direction_to_pivot = initial_dir.normalized()
        else:
            self.initial_direction_to_pivot = mathutils.Vector((0.0, 0.0, -1.0))

        if self.top_faces:
            for vert in extruded_verts:
                vert.co += avg_normal * 0.001

        if self._is_edge_extrusion_mode() and self.top_edges:
            edge_dir_world = mathutils.Vector((0.0, 0.0, 0.0))
            longest_edge_len_sq = 0.0
            obj_rot = obj.matrix_world.to_3x3()
            for edge in self.top_edges:
                v0 = self.original_vert_positions.get(edge.verts[0], edge.verts[0].co)
                v1 = self.original_vert_positions.get(edge.verts[1], edge.verts[1].co)
                edge_vec_world = obj_rot @ (v1 - v0)
                edge_len_sq = edge_vec_world.length_squared
                if edge_len_sq > longest_edge_len_sq:
                    longest_edge_len_sq = edge_len_sq
                    edge_dir_world = edge_vec_world

            view_normal = self._get_view_normal_world(context)
            if edge_dir_world.length > 1e-8 and view_normal is not None:
                edge_dir_world.normalize()
                screen_normal = edge_dir_world.cross(view_normal)
                if screen_normal.length <= 1e-8:
                    screen_normal = view_normal.cross(edge_dir_world)
                if screen_normal.length > 1e-8:
                    self._edge_initial_screen_normal_world = screen_normal.normalized()

            extrusion_faces = [
                face for face in (self.top_faces + self.side_faces)
                if face.is_valid
            ]
            if extrusion_faces:
                bmesh.ops.recalc_face_normals(self.bm, faces=extrusion_faces)
                self._enforce_extrusion_winding(obj, extrusion_faces)

        self._current_mouse_effective = mouse_pos
        self._last_move_world_dir = mathutils.Vector((0.0, 0.0, 1.0))
        bmesh.update_edit_mesh(obj.data)
        return True

    def _maybe_stamp_on_drag(self, context, event, obj):
        """Create a new stamp stage when distance exceeds threshold."""
        if not self.drag_stamping_active:
            return

        current_center = self._get_current_top_centroid_world(obj)

        if getattr(self, '_pending_first_drag_stamp', False):
            first_target = getattr(self, '_first_drag_stamp_target_world', None)
            first_origin = getattr(self, '_first_drag_stamp_origin_world', None)
            if first_target is None or first_origin is None:
                self._pending_first_drag_stamp = False
            else:
                current_2d = self._world_to_screen(context, current_center)
                origin_2d = self._world_to_screen(context, first_origin)
                target_2d = self._world_to_screen(context, first_target)
                reached_first = False

                if current_2d is not None and origin_2d is not None and target_2d is not None:
                    total_x = target_2d.x - origin_2d.x
                    total_y = target_2d.y - origin_2d.y
                    traveled_x = current_2d.x - origin_2d.x
                    traveled_y = current_2d.y - origin_2d.y
                    total_len_sq = total_x * total_x + total_y * total_y
                    traveled_len_sq = traveled_x * traveled_x + traveled_y * traveled_y
                    reached_first = traveled_len_sq >= total_len_sq
                else:
                    total_len = (first_target - first_origin).length
                    traveled_len = (current_center - first_origin).length
                    reached_first = traveled_len >= total_len

                if not reached_first:
                    return

                outgoing_tangent = first_target - self.original_faces_centroid
                self._apply_pending_stamp_correction(obj, outgoing_tangent)
                self._snap_current_stage_to_world_center(obj, first_target)
                self._pending_first_drag_stamp = False
                self._commit_stamp_and_continue(
                    context,
                    event,
                    obj,
                    outgoing_tangent,
                )
                return

        if getattr(self, '_last_stamp_world_centroid', None) is None:
            self._last_stamp_world_centroid = current_center
            return

        current_2d = self._world_to_screen(context, current_center)
        last_2d = self._world_to_screen(context, self._last_stamp_world_centroid)
        needs_stamp = False
        if current_2d is not None and last_2d is not None:
            delta_x = current_2d.x - last_2d.x
            delta_y = current_2d.y - last_2d.y
            needs_stamp = (delta_x * delta_x + delta_y * delta_y) >= (
                self.max_edge_length_px * self.max_edge_length_px
            )
        else:
            fallback_world_len = self._pixels_to_world_length(
                context,
                current_center,
                self.max_edge_length_px,
            )
            if fallback_world_len > 0.0:
                needs_stamp = (
                    (current_center - self._last_stamp_world_centroid).length
                    >= fallback_world_len
                )

        if not needs_stamp:
            return

        next_target = self._get_next_stamp_target_world(
            context,
            current_center,
            self._last_stamp_world_centroid,
        )
        if next_target is None:
            return

        outgoing_tangent = next_target - self.original_faces_centroid
        self._apply_pending_stamp_correction(obj, outgoing_tangent)
        self._snap_current_stage_to_world_center(obj, next_target)
        self._commit_stamp_and_continue(
            context,
            event,
            obj,
            outgoing_tangent,
        )

    def _current_stage_reached_stamp_threshold(self, context, obj):
        """Return True when current stage reached stamp spacing threshold."""
        last_stamp = getattr(self, '_last_stamp_world_centroid', None)
        if last_stamp is None:
            return False

        current_center = self._get_current_top_centroid_world(obj)
        current_2d = self._world_to_screen(context, current_center)
        last_2d = self._world_to_screen(context, last_stamp)
        if current_2d is not None and last_2d is not None:
            delta_x = current_2d.x - last_2d.x
            delta_y = current_2d.y - last_2d.y
            return (delta_x * delta_x + delta_y * delta_y) >= (
                self.max_edge_length_px * self.max_edge_length_px
            )

        world_len = self._pixels_to_world_length(
            context,
            current_center,
            self.max_edge_length_px,
        )
        if world_len <= 0.0:
            return False
        return (current_center - last_stamp).length >= world_len

    def _discard_in_progress_stage(self, obj):
        """Delete unstamped live stage and keep previously committed geometry."""
        live_top_verts = [vert for vert in self.top_verts if vert.is_valid]
        if not live_top_verts:
            return

        live_top_set = set(live_top_verts)
        base_verts = set()
        for edge in self.connector_edges:
            if not edge.is_valid:
                continue
            v0, v1 = edge.verts
            if v0 in live_top_set and v1 not in live_top_set:
                base_verts.add(v1)
            elif v1 in live_top_set and v0 not in live_top_set:
                base_verts.add(v0)

        bmesh.ops.delete(self.bm, geom=live_top_verts, context='VERTS')

        previous_stage = getattr(self, '_previous_committed_stage', None)

        for edge in self.bm.edges:
            edge.select = False
        for face in self.bm.faces:
            face.select = False
        for vert in self.bm.verts:
            vert.select = False

        if previous_stage:
            valid_faces = [
                face for face in previous_stage.get('top_faces', [])
                if face.is_valid
            ]
            valid_edges = [
                edge for edge in previous_stage.get('top_edges', [])
                if edge.is_valid
            ]
            valid_verts = [
                vert for vert in previous_stage.get('top_verts', [])
                if vert.is_valid
            ]

            target_normal_world = previous_stage.get('normal_world')
            if (
                target_normal_world is not None
                and target_normal_world.length > 1e-8
                and valid_faces
            ):
                target_normal_world = target_normal_world.normalized()
                obj_rot = obj.matrix_world.to_3x3()
                self.bm.normal_update()
                for face in valid_faces:
                    face_normal_world = obj_rot @ face.normal
                    if face_normal_world.length <= 1e-8:
                        continue
                    if face_normal_world.normalized().dot(target_normal_world) < 0.0:
                        face.normal_flip()

                self.bm.normal_update()

            for face in valid_faces:
                face.select = True
            for edge in valid_edges:
                edge.select = True
            for vert in valid_verts:
                vert.select = True

            self.top_faces = valid_faces
            self.top_edges = valid_edges
            self.top_verts = valid_verts
            self.original_top_verts_positions = [v.co.copy() for v in self.top_verts]
            self.original_vert_positions = {
                vert: vert.co.copy() for vert in self.top_verts
            }
            self._previous_committed_stage = None
            bmesh.update_edit_mesh(obj.data)
            return

        valid_base = [vert for vert in base_verts if vert.is_valid]
        if valid_base:
            base_set = set(valid_base)
            for vert in valid_base:
                vert.select = True
            for edge in self.bm.edges:
                if edge.verts[0] in base_set and edge.verts[1] in base_set:
                    edge.select = True
            for face in self.bm.faces:
                if all(vert in base_set for vert in face.verts):
                    face.select = True

        self._previous_committed_stage = None
        bmesh.update_edit_mesh(obj.data)

    def invoke(self, context, event):
        mouse_pos = (event.mouse_region_x, event.mouse_region_y)
        ok = self._setup_extrusion_from_selected_faces(context, mouse_pos)
        if not ok:
            return {'CANCELLED'}

        # Axis constraint and stamping state
        self.axis_constraints = axis_constraints.create_constraint_state()
        self.max_edge_length_px = 64.0
        self.drag_stamping_active = False
        self.drag_stamp_started = False
        self.drag_start_mouse = mouse_pos
        self.drag_pixel_threshold = 6.0
        self._mouse_pos = mathutils.Vector(mouse_pos)
        self._hud_help_visible = False
        self._last_stamp_world_centroid = getattr(
            self,
            'original_faces_centroid',
            None,
        )
        self._edge_last_extrusion_normal_world = None
        self._previous_committed_stage = None
        self._pending_stamp_correction = None

        self._stamp_draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_stamp_preview,
            (),
            'WINDOW',
            'POST_VIEW',
        )
        self._cursor_help_draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_cursor_help,
            (),
            'WINDOW',
            'POST_PIXEL',
        )
        viewport_drawing.start_hud_drawing([
            f"Stamp spacing (px): {self.max_edge_length_px:.1f}",
            "Wheel: adjust threshold",
            "LMB click: confirm once",
            "LMB drag: interval stamping",
        ])

        # Add modal handler
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    


    def modal(self, context, event):
        obj = context.edit_object
        if obj is None:
            self._stop_overlays()
            return {'CANCELLED'}

        # Pass through raw modifier keys to allow viewport navigation combos
        if event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT', 'LEFT_CTRL', 'RIGHT_CTRL', 'LEFT_ALT', 'RIGHT_ALT'}:
            return {'PASS_THROUGH'}
        
        # Debug: Print event info to help diagnose the issue
        if event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'ESC', 'RET'}:
            print(f"Super Extrude Modal: {event.type} - {event.value}")
        
        # Handle axis constraint toggles
        if self.axis_constraints.handle_constraint_event(event, "Super Extrude"):
            return {'RUNNING_MODAL'}

        # Proportional editing and quick menu are disabled for Super Extrude
        # Ignore 'O' and related inputs to prevent toggling global proportional edit during the modal
        if event.type in {'O', 'LEFT_BRACKET', 'RIGHT_BRACKET'}:
            return {'RUNNING_MODAL'}

        if event.type == 'H' and event.value == 'PRESS':
            self._hud_help_visible = not getattr(self, '_hud_help_visible', False)
            status = "ON" if self._hud_help_visible else "OFF"
            self.report({'INFO'}, f"HUD Help: {status}")
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.value == 'PRESS':
            step = 1.0 if event.shift else 4.0
            if event.type == 'WHEELUPMOUSE':
                self.max_edge_length_px += step
            else:
                self.max_edge_length_px -= step
            self.max_edge_length_px = max(8.0, self.max_edge_length_px)
            viewport_drawing.update_hud_text([
                f"Stamp spacing (px): {self.max_edge_length_px:.1f}",
                "Wheel: adjust threshold",
                "LMB click: confirm once",
                "LMB drag: interval stamping",
            ])
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self.drag_stamping_active = True
            self.drag_stamp_started = False
            self.drag_start_mouse = (event.mouse_region_x, event.mouse_region_y)

            current_center = self._get_current_top_centroid_world(obj)
            stamp_origin = getattr(self, '_last_stamp_world_centroid', None)
            if stamp_origin is None:
                stamp_origin = current_center

            preview_offset_world = self._get_preview_offset_world(
                context,
                current_center,
                stamp_origin,
            )
            self._first_drag_stamp_origin_world = stamp_origin.copy()
            self._first_drag_stamp_target_world = (
                current_center + preview_offset_world
            )
            self._pending_first_drag_stamp = True
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self._confirm_current_extrude_state(obj)

            self.drag_stamping_active = False
            self._stop_overlays()
            return {'FINISHED'}
        
        # Handle different events
        elif event.type == 'MOUSEMOVE':
            # Convert mouse movement to 3D translation
            self._mouse_pos = mathutils.Vector((
                event.mouse_region_x,
                event.mouse_region_y,
            ))
            region = context.region
            rv3d = context.space_data.region_3d
            
            # Get view plane normal
            view_normal = rv3d.view_rotation @ mathutils.Vector((0, 0, -1))
            
            # Calculate translation vector in world space
            # Precision-adjusted mouse using helper
            raw = (event.mouse_region_x, event.mouse_region_y)
            # For extrude we don't maintain a "current_adjusted" screen pos; use last adjusted or initial
            last_adjusted = getattr(self, "_current_mouse_effective", self.initial_mouse)
            adjusted = self.precision.on_move(raw, event.shift, last_adjusted)
            self._current_mouse_effective = adjusted

            translation_world = view3d_utils.mouse_delta_to_plane_delta(
                region, rv3d, 
                self.initial_mouse, 
                adjusted,
                self.original_faces_centroid,
                view_normal
            )

            if translation_world.length > 1e-8:
                self._last_move_world_dir = translation_world.normalized()

            screen_dx = adjusted[0] - self.initial_mouse[0]
            screen_dy = adjusted[1] - self.initial_mouse[1]
            screen_vec = mathutils.Vector((screen_dx, screen_dy))
            if screen_vec.length > 1e-8:
                self._last_move_screen_dir = screen_vec.normalized()
            
            # Convert world space translation to local space for vertex operations
            translation_local = obj.matrix_world.inverted().to_3x3() @ translation_world
            
            # Apply axis constraints to local translation
            constrained_translation = self.axis_constraints.apply_constraint(translation_local)
            constrained_translation_world = obj.matrix_world.to_3x3() @ constrained_translation
            
            # Use new spatial relationship utilities for consistent orientation behavior
            if self.top_verts:
                # Keep live stage orientation matched to the pivot-based preview.
                if constrained_translation_world.length > 1e-8:
                    self._last_move_world_dir = constrained_translation_world.normalized()
                if self._is_edge_extrusion_mode():
                    target_center_local = (
                        self.original_faces_centroid_local + constrained_translation
                    )
                    target_center_world = obj.matrix_world @ target_center_local
                    rotation_matrix = self._calculate_edge_mode_rotation(
                        context,
                        target_center_world,
                    )
                else:
                    rotation_matrix = math_utils.calculate_spatial_relationship_rotation(
                        self.original_faces_centroid_local,
                        constrained_translation,
                        self.pivot_point,
                        self.initial_direction_to_pivot,
                        obj.matrix_world,
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
                self._enforce_extrusion_winding(obj, extrusion_faces)
            
            # Update mesh
            bmesh.update_edit_mesh(obj.data)

            if self.drag_stamping_active:
                dx = event.mouse_region_x - self.drag_start_mouse[0]
                dy = event.mouse_region_y - self.drag_start_mouse[1]
                if (dx * dx + dy * dy) ** 0.5 > self.drag_pixel_threshold:
                    self.drag_stamp_started = True
                if self.drag_stamp_started:
                    self._maybe_stamp_on_drag(context, event, obj)

            viewport_drawing.update_hud_text([
                f"Stamp spacing (px): {self.max_edge_length_px:.1f}",
                "Wheel: adjust threshold",
                "LMB click: confirm once",
                "LMB drag: interval stamping",
            ])
            
        elif event.type == 'RET' and event.value == 'PRESS':
            # Confirm operation
            print("Super Extrude Modal: CONFIRMING operation")
            self._stop_overlays()
            self._confirm_current_extrude_state(obj)
            return {'FINISHED'}
            
        elif (event.type == 'RIGHTMOUSE' and event.value == 'PRESS') or (event.type == 'ESC' and event.value == 'PRESS'):
            # Cancel operation - use Blender's undo system to restore original state
            print("Super Extrude Modal: CANCELLING operation")
            self._stop_overlays()
            
            # Use Blender's undo system to restore the mesh to its state before the operation
            bpy.ops.ed.undo_push(message="Super Extrude Cancel")
            bpy.ops.ed.undo()
            
            return {'CANCELLED'}
        
        # Allow viewport navigation events to pass through
        elif event.type in {'MIDDLEMOUSE'} or \
             (event.type == 'MOUSEMOVE' and event.value == 'PRESS' and event.shift):
            # Pass through navigation events to allow viewport manipulation
            return {'PASS_THROUGH'}
        
        # For any other events, continue running modal
        return {'RUNNING_MODAL'}


def register():
    bpy.utils.register_class(MESH_OT_super_extrude_modal)


def unregister():
    bpy.utils.unregister_class(MESH_OT_super_extrude_modal)
