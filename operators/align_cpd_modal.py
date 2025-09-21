import bpy
import numpy as np
from bpy.types import Operator

from ..utils.align_icp import (
    sample_object_vertices_world,
)
from ..utils.align_cpd import cpd_rigid_step


class SUPERTOOLS_OT_cpd_align_modal(Operator):
    bl_idname = "super_tools.cpd_align_modal"
    bl_label = "CPD Align (ESC to stop)"
    bl_description = "Iteratively align selected meshes to the active target using Coherent Point Drift until ESC"
    bl_options = {'REGISTER', 'UNDO'}

    max_points: bpy.props.IntProperty(
        name="Max Points",
        description="Max points sampled per object for CPD",
        default=1500,
        min=200,
        max=20000,
    )

    update_rate: bpy.props.FloatProperty(
        name="Update Rate (sec)",
        description="How often to perform a CPD step",
        default=0.08,
        min=0.01,
        max=1.0,
        subtype='TIME'
    )

    w: bpy.props.FloatProperty(
        name="Outlier Weight",
        description="CPD uniform outlier weight (0 = none)",
        default=0.0,
        min=0.0,
        max=0.5,
        subtype='FACTOR',
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

        # Vertex group restriction
        vg_name = getattr(context.scene, "superalign_icp_target_group", "") or None
        if vg_name and (vg_name not in self.target.vertex_groups):
            self.report({'WARNING'}, f"Vertex group '{vg_name}' not found on target; using all vertices")
            vg_name = None
        self.vg_name = vg_name
        if self.vg_name:
            missing = [o.name for o in self.sources if self.vg_name not in o.vertex_groups]
            if missing:
                self.report({'WARNING'}, f"Skipping sources without group '{self.vg_name}': {', '.join(missing)}")
                self.sources = [o for o in self.sources if self.vg_name in o.vertex_groups]
            if not self.sources:
                self.report({'ERROR'}, f"No source objects have vertex group '{self.vg_name}'")
                return {'CANCELLED'}

        # Sample target once (fixed across iterations)
        X = sample_object_vertices_world(self.target, max_points=self.max_points, vgroup_name=self.vg_name)
        if X.shape[0] == 0:
            self.report({'ERROR'}, "Target has no usable vertices for CPD (check vertex group selection)")
            return {'CANCELLED'}
        self.X = X.astype(np.float64, copy=False)

        # Per-source state (sigma2)
        self._sigma2 = {obj.name: None for obj in self.sources}
        self.iteration = 0
        self.allow_scale = bool(getattr(context.scene, "superalign_icp_allow_scale", False))

        wm = context.window_manager
        self._timer = wm.event_timer_add(self.update_rate, window=context.window)
        wm.modal_handler_add(self)

        # Post status into first VIEW_3D header
        self._area = self._find_view3d_area(context)
        if self._area:
            self._area.header_text_set("CPD: iter=0 | pts=-- | outliers=--")

        suffix = f" (group='{self.vg_name}')" if self.vg_name else ""
        self.report({'INFO'}, f"CPD running{suffix}... Press ESC or Right Mouse to stop.")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            return self._finish(context, cancelled=True)

        if event.type == 'TIMER':
            total_pts = 0
            total_outliers = 0
            for obj in self.sources:
                # Sample moving source from (optional) vertex group
                Y = sample_object_vertices_world(obj, max_points=self.max_points, vgroup_name=self.vg_name)
                if Y.shape[0] == 0:
                    continue
                sig = self._sigma2.get(obj.name, None)
                R, s, t, sigma2_new, Np, outliers = cpd_rigid_step(
                    Y.astype(np.float64, copy=False),
                    self.X,
                    sigma2=sig,
                    w=float(self.w),
                    allow_scale=bool(getattr(context.scene, "superalign_icp_allow_scale", self.allow_scale)),
                )
                # Apply similarity or rigid based on s
                if s != 1.0:
                    from ..utils.align_icp import apply_similarity_transform_to_object
                    apply_similarity_transform_to_object(obj, R, s, t)
                else:
                    from ..utils.align_icp import apply_rigid_transform_to_object
                    apply_rigid_transform_to_object(obj, R, t)
                self._sigma2[obj.name] = sigma2_new
                total_pts += int(Np)
                total_outliers += int(outliers)

            self.iteration += 1
            if self._area:
                self._area.header_text_set(f"CPD: iter={self.iteration} | pts={total_pts} | outliers={total_outliers}")
                self._area.tag_redraw()
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    def _finish(self, context, cancelled=False):
        wm = context.window_manager
        if hasattr(self, '_timer') and self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        if self._area:
            self._area.header_text_set(None)
            self._area.tag_redraw()
        msg = f"CPD stopped after {self.iteration} iteration(s)."
        self.report({'INFO'}, msg)
        return {'CANCELLED' if cancelled else 'FINISHED'}

    def _find_view3d_area(self, context):
        win = getattr(context, 'window', None)
        scr = getattr(win, 'screen', None) if win else None
        if scr and getattr(scr, 'areas', None):
            for ar in scr.areas:
                if getattr(ar, 'type', '') == 'VIEW_3D':
                    return ar
        return getattr(context, 'area', None)


def register():
    bpy.utils.register_class(SUPERTOOLS_OT_cpd_align_modal)


def unregister():
    bpy.utils.unregister_class(SUPERTOOLS_OT_cpd_align_modal)
