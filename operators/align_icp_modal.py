import bpy
import numpy as np
from bpy.types import Operator
from mathutils import Matrix

from ..utils.align_icp import (
    sample_object_vertices_world,
    build_kdtree,
    nearest_neighbors,
    kabsch_rigid_transform,
    apply_rigid_transform_to_object,
    procrustes_similarity_transform,
    apply_similarity_transform_to_object,
)


class SUPERTOOLS_OT_icp_align_modal(Operator):
    bl_idname = "super_tools.icp_align_modal"
    bl_label = "ICP Align (ESC to stop)"
    bl_description = "Iteratively align selected meshes to the active target using ICP until ESC"
    bl_options = {'REGISTER', 'UNDO'}

    max_points: bpy.props.IntProperty(
        name="Max Points",
        description="Max points sampled per object for ICP",
        default=2000,
        min=100,
        max=20000,
    )

    update_rate: bpy.props.FloatProperty(
        name="Update Rate (sec)",
        description="How often to perform an ICP step",
        default=0.05,
        min=0.005,
        max=1.0,
        subtype='TIME'
    )

    def invoke(self, context, event):
        sel = [o for o in context.selected_objects if o.type == 'MESH']
        if len(sel) < 2:
            self.report({'ERROR'}, "Select at least two mesh objects")
            return {'CANCELLED'}
        self.target = context.active_object
        if self.target not in sel:
            self.report({'ERROR'}, "Active object must be among the selection (target)")
            return {'CANCELLED'}
        self.sources = [o for o in sel if o != self.target]
        if not self.sources:
            self.report({'ERROR'}, "No source objects to align")
            return {'CANCELLED'}

        # Restrict target points to selected vertex group if provided
        vg_name = getattr(context.scene, "superalign_icp_target_group", "") or None
        if vg_name and (vg_name not in self.target.vertex_groups):
            self.report({'WARNING'}, f"Vertex group '{vg_name}' not found on target; using all vertices")
            vg_name = None

        # Pre-sample target points and build KDTree (optionally restricted by vertex group)
        self.vg_name = vg_name  # persist validated group name for consistent use in modal steps
        tgt_pts = sample_object_vertices_world(self.target, max_points=self.max_points, vgroup_name=self.vg_name)
        if tgt_pts.shape[0] == 0:
            self.report({'ERROR'}, "Target has no usable vertices for ICP (check vertex group selection)")
            return {'CANCELLED'}
        self.kd = build_kdtree(tgt_pts)
        self.iteration = 0
        # Cache allow-scale flag from scene at start (read from scene to allow live toggle if desired)
        self.allow_scale = bool(getattr(context.scene, "superalign_icp_allow_scale", False))

        # If a vertex group is specified, filter sources to those that also contain the group
        if vg_name:
            missing = [o.name for o in self.sources if vg_name not in o.vertex_groups]
            if missing:
                self.report({'WARNING'}, f"Skipping sources without group '{vg_name}': {', '.join(missing)}")
                self.sources = [o for o in self.sources if vg_name in o.vertex_groups]
            if not self.sources:
                self.report({'ERROR'}, f"No source objects have vertex group '{vg_name}'")
                return {'CANCELLED'}

        wm = context.window_manager
        self._timer = wm.event_timer_add(self.update_rate, window=context.window)
        wm.modal_handler_add(self)
        suffix = f" (group='{self.vg_name}')" if self.vg_name else ""
        self.report({'INFO'}, f"ICP running{suffix}... Press ESC or Right Mouse to stop.")
        # Initialize header status line; persist first VIEW_3D area to ensure consistent display
        self._area = self._find_view3d_area(context)
        if self._area:
            self._area.header_text_set("ICP: iter=0 | pts=-- | outliers=--")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            return self._finish(context, cancelled=True)

        if event.type == 'TIMER':
            # One ICP step per timer tick for each source object
            total_pts = 0
            total_outliers = 0
            for obj in self.sources:
                src_pts = sample_object_vertices_world(obj, max_points=self.max_points, vgroup_name=self.vg_name)
                if src_pts.shape[0] == 0:
                    continue
                matches, dists = nearest_neighbors(src_pts, self.kd)
                # Reject outliers (top 10% distances)
                if matches.shape[0] >= 10:
                    thr = np.quantile(dists, 0.9)
                    mask = dists <= thr
                    A = src_pts[mask]
                    B = matches[mask]
                    total_pts += int(A.shape[0])
                    total_outliers += int((~mask).sum())
                else:
                    A = src_pts
                    B = matches
                    total_pts += int(A.shape[0])
                if bool(getattr(context.scene, "superalign_icp_allow_scale", self.allow_scale)):
                    R, s, t = procrustes_similarity_transform(A, B)
                    apply_similarity_transform_to_object(obj, R, s, t)
                else:
                    R, t = kabsch_rigid_transform(A, B)
                    apply_rigid_transform_to_object(obj, R, t)

            self.iteration += 1
            # Update header status line
            area = getattr(self, "_area", None)
            if area:
                area.header_text_set(f"ICP: iter={self.iteration} | pts={total_pts} | outliers={total_outliers}")
                area.tag_redraw()
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    def _finish(self, context, cancelled=False):
        wm = context.window_manager
        if hasattr(self, '_timer') and self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        msg = f"ICP stopped after {self.iteration} iteration(s)."
        level = {'INFO'} if not cancelled else {'INFO'}
        self.report(level, msg)
        # Clear header status line
        area = getattr(self, "_area", None)
        if area:
            area.header_text_set(None)
            area.tag_redraw()
        return {'CANCELLED' if cancelled else 'FINISHED'}

    def _find_view3d_area(self, context):
        # Prefer first VIEW_3D in current screen
        win = getattr(context, 'window', None)
        scr = getattr(win, 'screen', None) if win else None
        if scr and getattr(scr, 'areas', None):
            for ar in scr.areas:
                if getattr(ar, 'type', '') == 'VIEW_3D':
                    return ar
        # Fallback to current area
        return getattr(context, 'area', None)


def register():
    bpy.utils.register_class(SUPERTOOLS_OT_icp_align_modal)


def unregister():
    bpy.utils.unregister_class(SUPERTOOLS_OT_icp_align_modal)
