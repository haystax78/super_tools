import bpy
import bmesh
import mathutils
import blf
import heapq
import time
from mathutils import Vector
from mathutils.kdtree import KDTree
from math import radians
import numpy as np

from ..utils import math_utils, performance_utils, viewport_drawing, axis_constraints, falloff_utils, view3d_utils, input_utils


class VIEW3D_MT_super_tools_proportional(bpy.types.Menu):
    bl_label = "Super Tools Proportional Settings"
    bl_idname = "VIEW3D_MT_super_tools_proportional"

    def draw(self, context):
        layout = self.layout
        ts = context.scene.tool_settings
        layout.prop(ts, "use_proportional_edit", text="Enable Proportional Editing")
        layout.prop(ts, "proportional_edit_falloff", text="Falloff")
        layout.prop(ts, "use_proportional_connected", text="Connected Only")
        layout.prop(ts, "proportional_size", text="Radius")


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

    def update_hud(self, context):
        if context.area is not None:
            context.area.tag_redraw()

    def _remove_cursor_help_handler(self):
        """Remove cursor-help draw handler if present."""
        handler = getattr(self, '_cursor_help_draw_handler', None)
        if handler is not None:
            bpy.types.SpaceView3D.draw_handler_remove(handler, 'WINDOW')
            self._cursor_help_draw_handler = None

    def _get_cursor_help_slots(self):
        """Return cursor-help lines for Super Orient."""
        hud_visible = bool(getattr(self, '_hud_help_visible', False))
        hud_status = 'Hide' if hud_visible else 'Show'
        slots = [
            {
                'id': 'active_mode',
                'text': 'Mode: Super Orient',
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
                'id': 'constraints',
                'text': 'X/Y/Z: Axis Constraint',
                'color': (0.2, 0.8, 1.0),
            },
            {
                'id': 'precision',
                'text': 'Shift: Precision / Twist Wheel',
                'color': (0.7, 0.7, 0.7),
            },
        ])

        if self.use_proportional:
            slots.extend([
                {
                    'id': 'proportional',
                    'text': 'O: Proportional  Shift+O: Proportional Menu',
                    'color': (0.8, 0.8, 0.3),
                },
                {
                    'id': 'radius',
                    'text': 'Wheel/[ ]: Radius  1-8: Falloff  C: Connected',
                    'color': (0.85, 0.85, 0.85),
                },
            ])
        else:
            slots.append({
                'id': 'proportional_off',
                'text': 'O: Enable Proportional',
                'color': (0.8, 0.8, 0.3),
            })

        return slots

    def _draw_cursor_help(self):
        """Draw cursor-help text near mouse position."""
        mouse_pos = getattr(self, '_mouse_pos', None)
        if mouse_pos is None:
            return

        mx = float(mouse_pos.x)
        my = float(mouse_pos.y)
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
        self._ensure_connected_only_falloff_map(self.proportional_size)
        
        # Sync with Blender's global proportional editing distance setting
        context.scene.tool_settings.proportional_distance = new_size
        
        # Store current mouse position before reset
        current_mouse_before_reset = self.current_mouse_pos.copy()
        
        # FIRST: Reset to original state (vertices and mouse cursor)
        self.reset_to_original_state(context)
        
        # Restore the mouse position that was current before the reset
        self.current_mouse_pos = current_mouse_before_reset
        
        # THEN: Recalculate proportional vertices with new size FROM ORIGINAL POSITIONS (vectorized)
        obj = context.active_object
        self.proportional_verts = self._compute_proportional_vertices_np(
            self.original_selection_centroid_local, self.proportional_size, self.proportional_falloff, self.use_connected_only
        )
        
        # Check if falloff encompasses entire mesh by looking for vertices with zero weight
        total_mesh_verts = len(self.bm.verts)
        affected_verts = len(self.proportional_verts)
        
        if affected_verts < total_mesh_verts:
            # There are still unaffected vertices - calculate new pivot point normally
            self.pivot_point = self._calculate_proportional_pivot_point(
                obj,
                self.proportional_size,
            )
            self.last_valid_pivot_point = self.pivot_point.copy()  # Update last valid pivot
        else:
            # Falloff encompasses entire mesh - use frozen last valid pivot point
            if self.last_valid_pivot_point:
                self.pivot_point = self.last_valid_pivot_point.copy()
            else:
                # Fallback - calculate pivot anyway but warn
                self.pivot_point = self._calculate_proportional_pivot_point(
                    obj,
                    self.proportional_size,
                )
        
        # Update original positions cache for new vertex set
        self.original_vert_positions = {}
        for vert in self.proportional_verts.keys():
            self.original_vert_positions[vert] = vert.co.copy()
        
        # Update the initial spatial relationship since pivot point may have changed
        self.initial_direction_to_pivot = (self.pivot_point - self.original_faces_centroid).normalized()
        pivot_point_local = obj.matrix_world.inverted() @ self.pivot_point
        dir_local = (pivot_point_local - self.original_faces_centroid_local)
        self.initial_direction_to_pivot_local = dir_local.normalized() if dir_local.length > 0 else dir_local
        
        # Update circle and cross visualization
        # Center the falloff circle at the SELECTION BORDER centroid (unselected verts adjacent to selected)
        border_center = math_utils.calculate_border_vertices_centroid(self.selected_faces, self.bm, obj.matrix_world)
        viewport_drawing.update_proportional_circle(border_center, self.proportional_size)
        viewport_drawing.update_pivot_cross(self.pivot_point)
        
        # IMPORTANT: Reapply current mouse transformation after reset
        # This ensures the selection maintains its current position/rotation even after falloff changes
        self.apply_mouse_transformation(context)
        # Update HUD
        self.update_hud(context)

    def _build_spatial_caches(self, obj):
        """Build KDTree (world-space), coords arrays (local+world), and adjacency for connected-only fast masking.
        Also builds a KDTree of seed (selected) vertices in world space for border-based falloff.
        """
        self.bm.verts.ensure_lookup_table()
        verts = self.bm.verts
        n = len(verts)
        mw = obj.matrix_world
        # Local and world space coordinates arrays (N,3)
        self._coords_np = np.empty((n, 3), dtype=np.float32)
        self._coords_world_np = np.empty((n, 3), dtype=np.float32)
        for i, v in enumerate(verts):
            co = v.co
            self._coords_np[i, 0] = co.x
            self._coords_np[i, 1] = co.y
            self._coords_np[i, 2] = co.z
            cow = mw @ co
            self._coords_world_np[i, 0] = cow.x
            self._coords_world_np[i, 1] = cow.y
            self._coords_world_np[i, 2] = cow.z
        # KDTree on world space (so radius respects object scale)
        kd_all = KDTree(n)
        for i, v in enumerate(verts):
            cow = mw @ v.co
            kd_all.insert(cow, i)
        kd_all.balance()
        self._kd = kd_all
        # Selection seed indices
        self._seed_indices = {v.index for f in self.selected_faces for v in f.verts}
        # Adjacency (only if needed later)
        self._adjacency = None
        # Map index->bmesh vert for quick backref
        self._index_to_vert = {v.index: v for v in verts}
        # Precompute world matrix for transforms
        self._mw = mw
        # Build seed (selected) world coords and KDTree for border distance
        seed_list = sorted(list(self._seed_indices))
        if seed_list:
            self._seed_world_np = self._coords_world_np[seed_list]
            kd_seeds = KDTree(len(seed_list))
            for i, idx in enumerate(seed_list):
                kd_seeds.insert(tuple(self._seed_world_np[i]), idx)
            kd_seeds.balance()
            self._kd_seeds = kd_seeds
            self._seed_index_list = seed_list
            # Precompute seed centroid and max seed distance (world space) for expanded single-query path
            self._seed_centroid_world = self._seed_world_np.mean(axis=0)
            diff = self._seed_world_np - self._seed_centroid_world[None, :]
            self._max_seed_dist = float(np.sqrt(np.maximum((diff * diff).sum(axis=1), 0.0)).max()) if self._seed_world_np.shape[0] > 0 else 0.0
        else:
            self._seed_world_np = np.empty((0, 3), dtype=np.float32)
            self._kd_seeds = None
            self._seed_index_list = []
            self._seed_centroid_world = np.array([0.0, 0.0, 0.0], dtype=np.float32)
            self._max_seed_dist = 0.0

    def _ensure_adjacency(self):
        if self._adjacency is not None:
            return
        verts = self.bm.verts
        n = len(verts)
        adj = [[] for _ in range(n)]
        for edge in self.bm.edges:
            idx0 = int(edge.verts[0].index)
            idx1 = int(edge.verts[1].index)
            co0 = self._coords_world_np[idx0]
            co1 = self._coords_world_np[idx1]
            edge_len = float(np.linalg.norm(co1 - co0))
            adj[idx0].append((idx1, edge_len))
            adj[idx1].append((idx0, edge_len))
        self._adjacency = adj
        # Also compute connected components once (for fast connected-only masking)
        self._component_id = [-1] * n
        comp = 0
        for i in range(n):
            if self._component_id[i] != -1:
                continue
            # BFS
            q = [i]
            self._component_id[i] = comp
            qi = 0
            while qi < len(q):
                u = q[qi]
                qi += 1
                for nb, _edge_len in self._adjacency[u]:
                    if self._component_id[nb] == -1:
                        self._component_id[nb] = comp
                        q.append(nb)
            comp += 1

    def _rebuild_connected_only_mask(self, radius):
        """Build connected-only topological falloff cache for given radius."""
        self._connected_mask_radius = float(radius)
        self._connected_mask_indices = np.empty((0,), dtype=np.int32)
        self._connected_mask_topo_dist = np.empty((0,), dtype=np.float32)

        if not self._seed_index_list or radius <= 0.0:
            return

        self._ensure_adjacency()
        n = len(self.bm.verts)
        max_radius = float(radius)

        # Multi-source Dijkstra in world-space edge lengths.
        dist = np.full((n,), np.inf, dtype=np.float64)
        heap = []
        for seed_idx in self._seed_index_list:
            seed = int(seed_idx)
            if seed < 0 or seed >= n:
                continue
            dist[seed] = 0.0
            heapq.heappush(heap, (0.0, seed))

        while heap:
            cur_dist, vert_idx = heapq.heappop(heap)
            if cur_dist > max_radius:
                break
            if cur_dist > dist[vert_idx]:
                continue

            for nb_idx, edge_len in self._adjacency[vert_idx]:
                next_dist = cur_dist + edge_len
                if next_dist > max_radius:
                    continue
                if next_dist >= dist[nb_idx]:
                    continue
                dist[nb_idx] = next_dist
                heapq.heappush(heap, (next_dist, nb_idx))

        idxs = np.where(dist <= max_radius)[0]
        self._connected_mask_indices = idxs.astype(np.int32, copy=False)
        self._connected_mask_topo_dist = dist[idxs].astype(np.float32, copy=False)

    def _ensure_connected_only_falloff_map(self, radius):
        """Rebuild topological falloff map only when radius changes."""
        if (
            getattr(self, '_connected_mask_indices', None) is None
            or getattr(self, '_connected_mask_topo_dist', None) is None
            or getattr(self, '_connected_mask_radius', None) is None
            or abs(self._connected_mask_radius - float(radius)) > 1e-9
        ):
            self._rebuild_connected_only_mask(radius)

    def _calculate_proportional_pivot_point(self, obj, radius):
        """Return proportional pivot point for current proportional mode."""
        if not self.use_connected_only:
            return math_utils.calculate_proportional_border_vertices_centroid(
                self.selected_faces,
                self.bm,
                obj.matrix_world,
                radius,
            )
        return self._calculate_topological_boundary_pivot_point(obj, radius)

    def _calculate_topological_boundary_pivot_point(self, obj, radius):
        """Centroid from topological falloff boundary for connected-only mode."""
        self._ensure_connected_only_falloff_map(radius)
        idxs = self._connected_mask_indices
        if idxs is None or idxs.size == 0:
            return math_utils.calculate_proportional_border_vertices_centroid(
                self.selected_faces,
                self.bm,
                obj.matrix_world,
                radius,
            )

        self._ensure_adjacency()
        n = len(self.bm.verts)
        in_topo = np.zeros((n,), dtype=bool)
        in_topo[idxs] = True

        outer_boundary = []
        inner_boundary = []
        for idx in range(n):
            neighbors = self._adjacency[idx]
            if in_topo[idx]:
                if any(not in_topo[nb_idx] for nb_idx, _edge_len in neighbors):
                    inner_boundary.append(idx)
                continue
            if any(in_topo[nb_idx] for nb_idx, _edge_len in neighbors):
                outer_boundary.append(idx)

        boundary_indices = outer_boundary or inner_boundary
        if not boundary_indices:
            return math_utils.calculate_proportional_border_vertices_centroid(
                self.selected_faces,
                self.bm,
                obj.matrix_world,
                radius,
            )

        boundary_world = self._coords_world_np[np.array(boundary_indices, dtype=np.int32)]
        centroid = boundary_world.mean(axis=0)
        return Vector((float(centroid[0]), float(centroid[1]), float(centroid[2])))

    def _falloff_weights_np(self, dist, radius, falloff):
        """Compute weights for normalized distances via NumPy. Uses unified falloff utilities."""
        return falloff_utils.calculate_falloff_weights_vectorized(dist, radius, falloff)

    def _compute_proportional_vertices_np(self, origin_local, radius, falloff, connected_only):
        """Vectorized proportional set/weights. Returns {BMVert: weight}.
        Falloff distance is measured from the selection border (nearest selected vertex), not the centroid.
        """
        include_seeds_always = True
        # Candidate set: union of ranges around each seed so radius grows from
        # border outward. In connected-only mode, this can be cached.
        cand_set = set()
        topo_dist = None
        if connected_only:
            self._ensure_connected_only_falloff_map(radius)
            idxs = self._connected_mask_indices
            if idxs is None:
                idxs = np.empty((0,), dtype=np.int32)
            topo_dist = self._connected_mask_topo_dist
            if topo_dist is None:
                topo_dist = np.empty((0,), dtype=np.float32)
        else:
            idxs = None

        if idxs is not None:
            cand_set = set(idxs.tolist())

        if self._kd_seeds is not None and self._seed_index_list:
            # Choose strategy based on seed count
            many_seeds = len(self._seed_index_list) > 128
            # Ensure adjacency/components ready for connected-only filtering
            if connected_only and (getattr(self, '_component_id', None) is None):
                self._ensure_adjacency()
            if connected_only:
                pass
            elif many_seeds:
                # Single expanded query around seed centroid covers all border neighborhoods
                expanded = radius + max(self._max_seed_dist, 0.0)
                for _co, idx, _d in self._kd.find_range(tuple(self._seed_centroid_world), expanded):
                    if connected_only and self._component_id[int(idx)] != self._component_id[int(self._seed_index_list[0])]:
                        # Keep only same component as seeds (assuming all seeds are in same component)
                        continue
                    cand_set.add(int(idx))
            else:
                # Union of per-seed ranges
                for i, seed_idx in enumerate(self._seed_index_list):
                    seed_co = self._seed_world_np[i]
                    for _co, idx, _d in self._kd.find_range(tuple(seed_co), radius):
                        if connected_only:
                            if self._component_id[int(idx)] != self._component_id[int(seed_idx)]:
                                continue
                        cand_set.add(int(idx))
        else:
            # Fallback: use centroid-based range (should be rare)
            origin_world = self._mw @ origin_local
            for _co, idx, _d in self._kd.find_range(origin_world, radius):
                cand_set.add(int(idx))
        # Nothing found; still include seeds if requested
        if not cand_set and not include_seeds_always:
            return {}
        if idxs is None:
            idxs = (
                np.fromiter(cand_set, dtype=np.int32)
                if cand_set
                else np.empty((0,), dtype=np.int32)
            )
        # Distances: connected-only uses cached topological distance.
        # Non-connected mode uses nearest seed world-space distance.
        if connected_only:
            dist = topo_dist.astype(np.float32, copy=False)
        elif idxs.size and self._seed_world_np.shape[0] > 0:
            pts = self._coords_world_np[idxs]  # (k,3)
            seeds = self._seed_world_np       # (s,3)
            k = pts.shape[0]
            s = seeds.shape[0]
            dist2_min = np.empty((k,), dtype=np.float32)
            # Precompute seed norms once
            seed_norm2 = np.sum(seeds * seeds, axis=1, dtype=np.float32)  # (s,)
            batch = 4096
            for start in range(0, k, batch):
                end = min(start + batch, k)
                p = pts[start:end]  # (b,3)
                p_norm2 = np.sum(p * p, axis=1, dtype=np.float32)  # (b,)
                # d^2 = ||p||^2 + ||s||^2 - 2 p·s
                dot = p @ seeds.T  # (b,s)
                d2 = (p_norm2[:, None] + seed_norm2[None, :]) - 2.0 * dot
                # Clamp small negatives due to FP
                d2 = np.clip(d2, 0.0, None, dtype=np.float32)
                dist2_min[start:end] = d2.min(axis=1)
            dist = np.sqrt(dist2_min, dtype=np.float32)
        else:
            dist = np.empty((0,), dtype=np.float32)

        # Compute weights
        w = self._falloff_weights_np(dist, radius, falloff) if idxs.size else np.empty((0,), dtype=np.float32)
        # Build dict BMVert->weight (exclude zeros for cleanliness)
        out = {}
        for i, weight in zip(idxs.tolist(), w.tolist()):
            if weight <= 0.0:
                continue
            v = self._index_to_vert.get(int(i))
            if v is not None:
                out[v] = weight
        # Force include selected verts with full weight 1.0
        if include_seeds_always:
            for si in self._seed_indices:
                v = self._index_to_vert.get(int(si))
                if v is not None:
                    out[v] = 1.0
        return out

    def _reset_and_reapply_after_toggle_off(self, context):
        """Reset vertices to their original positions, switch to non-proportional originals map, and reapply current mouse transform."""
        # Store and restore mouse pos similar to adjust_proportional_falloff
        current_mouse_before_reset = self.current_mouse_pos.copy()
        # Reset using current original_vert_positions (which contain proportional originals)
        self.reset_to_original_state(context)
        # IMPORTANT: After reset, recompute the non-proportional pivot BEFORE applying transform
        obj = context.active_object
        self.pivot_point = math_utils.calculate_border_vertices_centroid(
            self.selected_faces, self.bm, obj.matrix_world
        )
        # Update initial direction to pivot to keep spatial relationship consistent (world and local)
        self.initial_direction_to_pivot = (self.pivot_point - self.original_faces_centroid).normalized()
        pivot_point_local = obj.matrix_world.inverted() @ self.pivot_point
        dir_local = (pivot_point_local - self.original_faces_centroid_local)
        self.initial_direction_to_pivot_local = dir_local.normalized() if dir_local.length > 0 else dir_local
        # Switch original map to selected verts initial positions for non-proportional mode
        self.original_vert_positions = {v: co.copy() for v, co in self.initial_selected_vert_positions.items()}
        # Restore mouse and reapply
        self.current_mouse_pos = current_mouse_before_reset
        self.apply_mouse_transformation(context)

    def _queue_proportional_radius_update(self, new_size):
        """Queue a proportional radius update and coalesce rapid wheel steps."""
        self._queued_proportional_size = float(max(0.01, new_size))
        self._radius_update_pending = True
        self._radius_update_queued_at = time.perf_counter()

    def _get_effective_proportional_size(self):
        """Return most recent proportional size, including queued updates."""
        if getattr(self, '_radius_update_pending', False):
            pending = getattr(self, '_queued_proportional_size', None)
            if pending is not None:
                return float(pending)
        return float(self.proportional_size)

    def _flush_queued_proportional_radius_update(self, context, force=False):
        """Apply queued radius update once input settles or when forced."""
        if not getattr(self, '_radius_update_pending', False):
            return False
        if not force:
            queued_at = getattr(self, '_radius_update_queued_at', 0.0)
            debounce = getattr(self, '_radius_debounce_seconds', 0.05)
            if (time.perf_counter() - queued_at) < debounce:
                return False

        pending_size = getattr(self, '_queued_proportional_size', None)
        self._radius_update_pending = False
        if pending_size is None:
            return False
        if abs(float(pending_size) - float(self.proportional_size)) <= 1e-9:
            return False

        self.adjust_proportional_falloff(context, float(pending_size))
        return True

    def _cleanup_modal_resources(self, context):
        """Clean up timer resources used by the modal operator."""
        timer = getattr(self, '_radius_update_timer', None)
        if timer is not None:
            context.window_manager.event_timer_remove(timer)
            self._radius_update_timer = None
        self._remove_cursor_help_handler()

    def apply_mouse_transformation(self, context):
        """
        Apply the current mouse transformation (translation and rotation) to the selection.
        This is used both during mouse movement and after falloff radius changes.
        """
        obj = context.active_object
        region = context.region
        rv3d = context.space_data.region_3d
        
        if not region or not rv3d:
            return
            
        view_normal = rv3d.view_rotation @ mathutils.Vector((0, 0, -1))
        
        # Use original selection centroid in world space as the plane for translation
        selection_centroid_world = self.original_faces_centroid
        
        # Calculate translation from mouse movement (in world space)
        translation_world = view3d_utils.mouse_delta_to_plane_delta(
            region, rv3d, self.initial_mouse, 
            (self.current_mouse_pos.x, self.current_mouse_pos.y), 
            selection_centroid_world, view_normal
        )
        
        # Convert world space translation to local space for vertex operations
        translation = obj.matrix_world.inverted().to_3x3() @ translation_world
        
        # Apply axis constraints to translation
        constrained_translation = self.axis_constraints.apply_constraint(translation)
        
        # Calculate rotation matrix using the new utility function
        rotation_matrix = math_utils.calculate_spatial_relationship_rotation(
            self.original_faces_centroid_local, constrained_translation, 
            self.pivot_point, self.initial_direction_to_pivot, obj.matrix_world
        )

        # Compose optional twist around the axis defined by direction to pivot (WORLD space)
        # rotation_matrix from calculate_spatial_relationship_rotation is in WORLD space,
        # so build the twist in WORLD space as well to avoid mixing spaces.
        if getattr(self, 'twist_angle', 0.0) != 0.0:
            axis_world = getattr(self, 'initial_direction_to_pivot', None)
            if axis_world is not None and axis_world.length > 0.0:
                axis_world = axis_world.normalized()
                twist_world = mathutils.Matrix.Rotation(self.twist_angle, 3, axis_world)
                rotation_matrix = twist_world @ rotation_matrix
        
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
        self._mouse_pos = Vector((event.mouse_region_x, event.mouse_region_y))
        self._hud_help_visible = False
        
        # Check if proportional editing is enabled
        tool_settings = context.scene.tool_settings
        self.use_proportional = tool_settings.use_proportional_edit
        self.proportional_size = tool_settings.proportional_size
        self.proportional_falloff = tool_settings.proportional_edit_falloff
        self.use_connected_only = tool_settings.use_proportional_connected
        
        print(f"Super Orient: Proportional editing settings - Connected Only: {self.use_connected_only}")
        print(f"Super Orient: Will use {'topology-based' if self.use_connected_only else 'radial'} falloff distance")
        
        # Build spatial caches for fast proportional queries
        self._build_spatial_caches(obj)
        self._connected_mask_radius = None
        self._connected_mask_indices = None
        self._connected_mask_topo_dist = None
        self._ensure_connected_only_falloff_map(self.proportional_size)

        # Calculate pivot point based on proportional editing settings
        if self.use_proportional:
            # Use proportional border vertices (outside falloff radius) as pivot
            self.pivot_point = self._calculate_proportional_pivot_point(
                obj,
                self.proportional_size,
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
        # Master cache of initial positions for selected verts
        self.initial_selected_vert_positions = {v: v.co.copy() for v in self.selected_verts}
        
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
        # Precision mode state using reusable helper
        self.precision = input_utils.PrecisionMouseState(scale=0.3)
        self.precision.reset((event.mouse_region_x, event.mouse_region_y))
        
        # Axis constraint state
        self.axis_constraints = axis_constraints.create_constraint_state()

        # Debounced radius update state to avoid expensive recompute per wheel event.
        self._queued_proportional_size = None
        self._radius_update_pending = False
        self._radius_update_queued_at = 0.0
        self._radius_debounce_seconds = 0.05
        self._radius_update_timer = context.window_manager.event_timer_add(
            0.02,
            window=context.window,
        )

        # Twist state (in radians); positive twists around pivot-direction axis
        self.twist_angle = 0.0
        self._twist_step = radians(2.0)
        
        # Cache original selection state for transformation calculations
        # Store both local and world space versions for consistent coordinate handling
        self.original_faces_centroid_local = math_utils.calculate_faces_centroid(self.selected_faces, mathutils.Matrix.Identity(4))
        self.original_faces_centroid = obj.matrix_world @ self.original_faces_centroid_local
        
        # Store the initial spatial relationship between selection and pivot (world and local)
        self.initial_direction_to_pivot = (self.pivot_point - self.original_faces_centroid).normalized()
        pivot_point_local = obj.matrix_world.inverted() @ self.pivot_point
        dir_local = (pivot_point_local - self.original_faces_centroid_local)
        self.initial_direction_to_pivot_local = dir_local.normalized() if dir_local.length > 0 else dir_local
        print(f"Super Orient: Initial direction from selection to pivot: {self.initial_direction_to_pivot}")
        
        # Initialize performance cache for proportional falloff calculations
        self.falloff_cache = performance_utils.ProportionalFalloffCache()
        
        if self.use_proportional:
            # Get proportional vertices and their weights using vectorized path
            print(f"DEBUG ORIENT: Vectorized falloff init from: {self.original_selection_centroid_local}")
            self.proportional_verts = self._compute_proportional_vertices_np(
                self.original_selection_centroid_local, self.proportional_size, self.proportional_falloff, self.use_connected_only
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
            # Center the circle at the SELECTION BORDER centroid (unselected verts adjacent to selected)
            border_center = math_utils.calculate_border_vertices_centroid(self.selected_faces, self.bm, obj.matrix_world)
            viewport_drawing.start_proportional_circle_drawing(border_center, self.proportional_size)
            viewport_drawing.start_pivot_cross_drawing(self.pivot_point)
        # HUD disabled for now
        self.update_hud(context)

        self._cursor_help_draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_cursor_help,
            (),
            'WINDOW',
            'POST_PIXEL',
        )

        # Cache last seen tool settings to detect external changes (e.g., menu)
        ts = context.scene.tool_settings
        self._ts_use_proportional = bool(ts.use_proportional_edit)
        self._ts_size = float(ts.proportional_size)
        self._ts_falloff = ts.proportional_edit_falloff
        self._ts_connected = bool(ts.use_proportional_connected)
        
        # Add modal handler
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _sync_tool_settings_and_apply(self, context):
        """Detect and apply changes made via the Tool Settings (e.g., quick menu)."""
        ts = context.scene.tool_settings
        changed = False

        # Proportional enable/disable via menu
        if bool(ts.use_proportional_edit) != self._ts_use_proportional:
            changed = True
            if ts.use_proportional_edit and not self.use_proportional:
                # Enable proportional: start overlays then adjust
                self.use_proportional = True
                self.proportional_size = ts.proportional_size
                self.proportional_falloff = ts.proportional_edit_falloff
                self.use_connected_only = ts.use_proportional_connected
                # Center the circle at the SELECTION BORDER centroid (unselected verts adjacent to selected)
                border_center = math_utils.calculate_border_vertices_centroid(self.selected_faces, self.bm, context.edit_object.matrix_world)
                viewport_drawing.start_proportional_circle_drawing(border_center, self.proportional_size)
                viewport_drawing.start_pivot_cross_drawing(self.pivot_point)
                self.adjust_proportional_falloff(context, self.proportional_size)
            elif not ts.use_proportional_edit and self.use_proportional:
                # Disable proportional: stop overlays then reset/reapply
                self.use_proportional = False
                viewport_drawing.stop_proportional_circle_drawing()
                self._reset_and_reapply_after_toggle_off(context)

        # Radius changed via menu while proportional is on
        if self.use_proportional and abs(float(ts.proportional_size) - self._ts_size) > 1e-9:
            changed = True
            self.adjust_proportional_falloff(context, float(ts.proportional_size))

        # Falloff type changed via menu while proportional is on
        if self.use_proportional and ts.proportional_edit_falloff != self._ts_falloff:
            changed = True
            self.proportional_falloff = ts.proportional_edit_falloff
            self.adjust_proportional_falloff(context, self.proportional_size)

        # Connected only changed via menu while proportional is on
        if self.use_proportional and bool(ts.use_proportional_connected) != self._ts_connected:
            changed = True
            self.use_connected_only = bool(ts.use_proportional_connected)
            self.adjust_proportional_falloff(context, self.proportional_size)

        if changed:
            # Update cache and HUD/overlays
            self._ts_use_proportional = bool(ts.use_proportional_edit)
            self._ts_size = float(ts.proportional_size)
            self._ts_falloff = ts.proportional_edit_falloff
            self._ts_connected = bool(ts.use_proportional_connected)
            self.update_hud(context)


    def modal(self, context, event):
        obj = context.edit_object

        event_timer = getattr(event, 'timer', None)
        if (
            event.type == 'TIMER'
            and getattr(self, '_radius_update_timer', None) is not None
            and (event_timer is None or event_timer == self._radius_update_timer)
        ):
            self._flush_queued_proportional_radius_update(context)
            return {'RUNNING_MODAL'}

        # Pass through raw modifier key events to allow viewport navigation combos
        if event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT', 'LEFT_CTRL', 'RIGHT_CTRL', 'LEFT_ALT', 'RIGHT_ALT'}:
            return {'PASS_THROUGH'}
        
        # Sync any changes made via the Shift+O menu (tool settings) into the modal state
        self._sync_tool_settings_and_apply(context)

        if event.type == 'H' and event.value == 'PRESS':
            self._hud_help_visible = not getattr(self, '_hud_help_visible', False)
            status = "ON" if self._hud_help_visible else "OFF"
            self.report({'INFO'}, f"HUD Help: {status}")
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        
        # Handle axis constraint toggles
        if self.axis_constraints.handle_constraint_event(event, "Super Orient"):
            self.update_hud(context)
            return {'RUNNING_MODAL'}

        elif event.type == 'C' and event.value == 'PRESS' and self.use_proportional:
            # Toggle connected-only while modal is running.
            ts = context.scene.tool_settings
            self.use_connected_only = not self.use_connected_only
            ts.use_proportional_connected = self.use_connected_only
            self.adjust_proportional_falloff(context, self.proportional_size)
            self._ts_connected = bool(ts.use_proportional_connected)
            self.update_hud(context)
            return {'RUNNING_MODAL'}

        elif event.type in {"ONE","TWO","THREE","FOUR","FIVE","SIX","SEVEN","EIGHT"} and event.value == 'PRESS' and self.use_proportional:
            # Map number keys to falloff types
            falloffs = [
                'SMOOTH',        # 1
                'SPHERE',        # 2
                'ROOT',          # 3
                'INVERSE_SQUARE',# 4
                'SHARP',         # 5
                'LINEAR',        # 6
                'CONSTANT',      # 7
                'RANDOM',        # 8
            ]
            idx_map = {'ONE':0,'TWO':1,'THREE':2,'FOUR':3,'FIVE':4,'SIX':5,'SEVEN':6,'EIGHT':7}
            ts = context.scene.tool_settings
            new_falloff = falloffs[idx_map[event.type]]
            ts.proportional_edit_falloff = new_falloff
            self.proportional_falloff = new_falloff
            print(f"Super Orient: Falloff set to {new_falloff}")
            # Recompute proportional set with new falloff and refresh overlays via adjust
            self.adjust_proportional_falloff(context, self.proportional_size)
            return {'RUNNING_MODAL'}
        
        # Twist controls (take precedence when Shift is held)
        elif event.shift and event.type == 'WHEELUPMOUSE':
            self.twist_angle += self._twist_step
            self.apply_mouse_transformation(context)
            return {'RUNNING_MODAL'}

        elif event.shift and event.type == 'WHEELDOWNMOUSE':
            self.twist_angle -= self._twist_step
            self.apply_mouse_transformation(context)
            return {'RUNNING_MODAL'}

        elif event.shift and event.type == 'LEFT_BRACKET' and event.value == 'PRESS':
            self.twist_angle -= self._twist_step
            self.apply_mouse_transformation(context)
            return {'RUNNING_MODAL'}

        elif event.shift and event.type == 'RIGHT_BRACKET' and event.value == 'PRESS':
            self.twist_angle += self._twist_step
            self.apply_mouse_transformation(context)
            return {'RUNNING_MODAL'}

        elif event.type == 'WHEELUPMOUSE' and self.use_proportional:
            # Increase proportional size
            base_size = self._get_effective_proportional_size()
            new_size = base_size * 1.1
            self._queue_proportional_radius_update(new_size)
            return {'RUNNING_MODAL'}
            
        elif event.type == 'WHEELDOWNMOUSE' and self.use_proportional:
            # Decrease proportional size (minimum 0.01)
            base_size = self._get_effective_proportional_size()
            new_size = max(0.01, base_size * 0.9)
            self._queue_proportional_radius_update(new_size)
            
            return {'RUNNING_MODAL'}
            
        elif event.type == 'LEFT_BRACKET' and event.value == 'PRESS' and self.use_proportional:
            # Decrease proportional size (alternative to mouse wheel)
            base_size = self._get_effective_proportional_size()
            new_size = max(0.01, base_size * 0.9)
            self._queue_proportional_radius_update(new_size)
            
            return {'RUNNING_MODAL'}
            
        elif event.type == 'RIGHT_BRACKET' and event.value == 'PRESS' and self.use_proportional:
            # Increase proportional size (alternative to mouse wheel)
            base_size = self._get_effective_proportional_size()
            new_size = base_size * 1.1
            self._queue_proportional_radius_update(new_size)
            
            return {'RUNNING_MODAL'}
        
        elif event.type == 'O' and event.shift:
            # Quick proportional settings menu
            bpy.ops.wm.call_menu(name=VIEW3D_MT_super_tools_proportional.bl_idname)
            return {'RUNNING_MODAL'}
        
        elif event.type == 'O' and event.value == 'PRESS':
            # Toggle proportional editing during modal
            ts = context.scene.tool_settings
            self.use_proportional = not self.use_proportional
            ts.use_proportional_edit = self.use_proportional
            if self.use_proportional:
                # Initialize proportional state and overlays; rebuild proportional verts via adjust
                self.proportional_size = ts.proportional_size
                self.proportional_falloff = ts.proportional_edit_falloff
                self.use_connected_only = ts.use_proportional_connected
                # Center the circle at the SELECTION BORDER centroid (unselected verts adjacent to selected)
                border_center = math_utils.calculate_border_vertices_centroid(self.selected_faces, self.bm, obj.matrix_world)
                viewport_drawing.start_proportional_circle_drawing(border_center, self.proportional_size)
                viewport_drawing.start_pivot_cross_drawing(self.pivot_point)
                # Rebuild proportional vertices and update pivot/circle/HUD consistently
                self.adjust_proportional_falloff(context, self.proportional_size)
            else:
                # Turn off proportional, stop overlays
                viewport_drawing.stop_proportional_circle_drawing()
                # Proper reset like falloff change: reset first, then recompute pivot and reapply without proportional weights
                self._reset_and_reapply_after_toggle_off(context)
            self.update_hud(context)
            return {'RUNNING_MODAL'}

            
        elif event.type == 'MOUSEMOVE':
            self._flush_queued_proportional_radius_update(context)
            # Update current mouse position with precision handling
            self._mouse_pos = Vector((event.mouse_region_x, event.mouse_region_y))
            raw = (event.mouse_region_x, event.mouse_region_y)
            adjusted = self.precision.on_move(
                raw,
                shift=event.shift,
                current_adjusted_xy=(self.current_mouse_pos.x, self.current_mouse_pos.y),
            )
            self.current_mouse_pos = Vector(adjusted)
            
            # Apply the mouse transformation using the shared function
            self.apply_mouse_transformation(context)
            
            # Update mesh
            bmesh.update_edit_mesh(obj.data)
            
        elif (event.type == 'LEFTMOUSE' and event.value == 'PRESS') or (event.type == 'RET' and event.value == 'PRESS'):
            # Confirm operation
            self._flush_queued_proportional_radius_update(context, force=True)
            print("Super Orient Modal: CONFIRMING operation")
            
            # Stop overlays
            if self.use_proportional:
                viewport_drawing.stop_proportional_circle_drawing()
            self._cleanup_modal_resources(context)
            
            # Recalculate all face normals for final result
            bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces)
            
            # Keep selection as is (selected faces remain selected)
            bmesh.update_edit_mesh(obj.data)
            return {'FINISHED'}
            
        elif (event.type == 'RIGHTMOUSE' and event.value == 'PRESS') or (event.type == 'ESC' and event.value == 'PRESS'):
            # Cancel operation - restore original positions
            print("Super Orient Modal: CANCELLING operation")
            
            # Stop overlays
            if self.use_proportional:
                viewport_drawing.stop_proportional_circle_drawing()
            self._cleanup_modal_resources(context)
            
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
    bpy.utils.register_class(VIEW3D_MT_super_tools_proportional)
    bpy.utils.register_class(MESH_OT_super_orient_modal)


def unregister():
    bpy.utils.unregister_class(MESH_OT_super_orient_modal)
    bpy.utils.unregister_class(VIEW3D_MT_super_tools_proportional)


if __name__ == "__main__":
    register()
