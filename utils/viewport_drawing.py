import bpy
import gpu
import mathutils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
import math
import blf


class ProportionalCircleDrawer:
    """Handles drawing a red circle to visualize proportional editing falloff radius"""
    
    def __init__(self):
        self.draw_handler = None
        self.center_point = Vector((0, 0, 0))
        self.radius = 1.0
        self.segments = 64
        self.batch = None
        self.shader = None
        
        # Cross drawing for pivot point
        self.cross_point = Vector((0, 0, 0))
        self.cross_batch = None
        self.cross_shader = None
        self.show_cross = False
        
    def setup_drawing(self, center_point, radius):
        """Setup the circle drawing with given center and radius"""
        self.center_point = center_point.copy()
        self.radius = radius
        self._create_circle_batch()
        
    def _create_circle_batch(self):
        """Create GPU batch for drawing the circle as a true 3D circle on the view plane.
        This uses world-space radius and a basis aligned to the current view, so size stays consistent
        regardless of camera direction or object/world axes.
        """
        context = bpy.context
        region = context.region
        rv3d = context.space_data.region_3d

        if not region or not rv3d:
            return

        # View basis in world space
        # view_normal points from camera into the scene
        view_normal = rv3d.view_rotation @ Vector((0, 0, -1))
        view_right = (rv3d.view_rotation @ Vector((1, 0, 0))).normalized()
        view_up = (rv3d.view_rotation @ Vector((0, 1, 0))).normalized()

        # Generate circle vertices directly in world space
        c = self.center_point
        r = float(self.radius)
        vertices = []
        for i in range(self.segments):
            angle = 2.0 * math.pi * i / self.segments
            offset = (math.cos(angle) * view_right + math.sin(angle) * view_up) * r
            p = c + offset
            vertices.append((p.x, p.y, p.z))
        
        if not vertices:
            return
            
        # Create indices for line loop
        indices = []
        for i in range(len(vertices)):
            indices.append((i, (i + 1) % len(vertices)))
        
        # Create shader and batch
        self.shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        self.batch = batch_for_shader(
            self.shader, 'LINES', 
            {"pos": vertices}, 
            indices=indices
        )
    
    def _create_cross_batch(self):
        """Create GPU batch for drawing a small circle at pivot point in screen space"""
        # Get current context for screen space calculations
        context = bpy.context
        region = context.region
        rv3d = context.space_data.region_3d
        
        if not region or not rv3d:
            return
            
        # Project pivot point to screen space
        from bpy_extras.view3d_utils import location_3d_to_region_2d
        screen_center = location_3d_to_region_2d(region, rv3d, self.cross_point)
        
        if not screen_center:
            return
            
        # Create small circle in screen space (8 pixel radius)
        screen_radius = 8.0
        segments = 16
        
        # Generate circle vertices in screen space, then convert back to 3D
        vertices = []
        from bpy_extras.view3d_utils import region_2d_to_location_3d
        
        for i in range(segments):
            angle = 2.0 * math.pi * i / segments
            # Create circle in screen space
            screen_x = screen_center.x + screen_radius * math.cos(angle)
            screen_y = screen_center.y + screen_radius * math.sin(angle)
            
            # Convert back to 3D world space at the pivot point's depth
            world_pos = region_2d_to_location_3d(region, rv3d, (screen_x, screen_y), self.cross_point)
            if world_pos:
                vertices.append((world_pos.x, world_pos.y, world_pos.z))
        
        if not vertices:
            return
            
        # Create indices for line loop
        indices = []
        for i in range(len(vertices)):
            indices.append((i, (i + 1) % len(vertices)))
        
        # Create shader and batch
        self.cross_shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        self.cross_batch = batch_for_shader(
            self.cross_shader, 'LINES', 
            {"pos": vertices}, 
            indices=indices
        )
    
    def draw_circle(self):
        """Draw function called by Blender's draw handler"""
        # Recreate the batch every draw so orientation and size stay correct as the view changes
        self._create_circle_batch()
        if self.batch and self.shader:
            # Set line properties
            gpu.state.line_width_set(2.0)
            gpu.state.blend_set('ALPHA')
            
            # Set viewport size for polyline shader
            viewport = gpu.state.viewport_get()
            self.shader.uniform_float("viewportSize", (viewport[2], viewport[3]))
            self.shader.uniform_float("lineWidth", 2.0)
            
            # Set white color with 20% alpha
            self.shader.uniform_float("color", (1.0, 1.0, 1.0, 0.2))
            
            # Draw the circle
            self.batch.draw(self.shader)
            
            # Draw pivot circle if enabled
            if self.show_cross and self.cross_batch and self.cross_shader:
                # Set white color for pivot circle
                self.cross_shader.uniform_float("viewportSize", (viewport[2], viewport[3]))
                self.cross_shader.uniform_float("lineWidth", 2.0)
                self.cross_shader.uniform_float("color", (1.0, 1.0, 1.0, 1.0))
                
                # Draw the pivot circle
                self.cross_batch.draw(self.cross_shader)
            
            # Reset GPU state
            gpu.state.blend_set('NONE')
    
    def start_drawing(self):
        """Add draw handler to viewport"""
        if self.draw_handler is None:
            self.draw_handler = bpy.types.SpaceView3D.draw_handler_add(
                self.draw_circle, (), 'WINDOW', 'POST_VIEW'
            )
            # Force viewport update
            for area in bpy.context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    
    def stop_drawing(self):
        """Remove draw handler from viewport"""
        if self.draw_handler is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self.draw_handler, 'WINDOW')
            self.draw_handler = None
            # Force viewport update
            for area in bpy.context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    
    def update_circle(self, center_point, radius):
        """Update circle position and radius"""
        self.center_point = center_point.copy()
        self.radius = radius
        self._create_circle_batch()
        # Force viewport update
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
    
    def setup_cross(self, cross_point):
        """Setup the cross drawing at given point"""
        self.cross_point = cross_point.copy()
        self.show_cross = True
        self._create_cross_batch()
    
    def update_cross(self, cross_point):
        """Update cross position"""
        self.cross_point = cross_point.copy()
        self._create_cross_batch()
        # Force viewport update
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
    
    def hide_cross(self):
        """Hide the cross"""
        self.show_cross = False


# Global instance for the circle drawer
_circle_drawer = None


def get_circle_drawer():
    """Get or create the global circle drawer instance"""
    global _circle_drawer
    if _circle_drawer is None:
        _circle_drawer = ProportionalCircleDrawer()
    return _circle_drawer


def start_proportional_circle_drawing(center_point, radius):
    """Start drawing proportional circle at given center and radius"""
    drawer = get_circle_drawer()
    drawer.setup_drawing(center_point, radius)
    drawer.start_drawing()


def update_proportional_circle(center_point, radius):
    """Update the proportional circle position and radius"""
    drawer = get_circle_drawer()
    drawer.update_circle(center_point, radius)


def start_pivot_cross_drawing(cross_point):
    """Start drawing green cross at pivot point"""
    drawer = get_circle_drawer()
    drawer.setup_cross(cross_point)


def update_pivot_cross(cross_point):
    """Update the pivot cross position"""
    drawer = get_circle_drawer()
    drawer.update_cross(cross_point)


def stop_proportional_circle_drawing():
    """Stop drawing the proportional circle and cross"""
    drawer = get_circle_drawer()
    drawer.hide_cross()
    drawer.stop_drawing()


# ------------------------
# DPI-aware HUD Text Drawer
# ------------------------

class HUDTextDrawer:
    """Draws DPI-aware text HUD in the viewport (POST_PIXEL)."""

    def __init__(self):
        self.draw_handler = None
        self.lines = []
        self.font_id = 0  # default font

    def _dpi_ui_scale(self):
        prefs = bpy.context.preferences
        ui_scale = getattr(prefs.view, 'ui_scale', 1.0)
        dpi = getattr(prefs.system, 'dpi', 72)
        return ui_scale, dpi

    def _draw(self):
        # Basic setup
        gpu.state.blend_set('ALPHA')

        ui_scale, dpi = self._dpi_ui_scale()
        base_size = 12
        size_px = max(10, int(base_size * ui_scale))
        padding = int(12 * ui_scale)
        line_height = int(size_px * 1.4)

        # Position top-left with padding
        x = padding
        # Draw a small translucent backdrop for readability
        try:
            from gpu_extras.presets import draw_texture_2d
        except Exception:
            draw_texture_2d = None

        # Draw text lines
        blf.size(self.font_id, size_px, dpi)
        y = 0
        # Compute from top of region
        region = bpy.context.region
        if region:
            y = region.height - padding - size_px
        else:
            y = 200

        for line in self.lines:
            blf.position(self.font_id, x, y, 0)
            blf.color(self.font_id, 1.0, 1.0, 1.0, 0.9)
            blf.draw(self.font_id, line)
            y -= line_height

        gpu.state.blend_set('NONE')

    def start(self):
        if self.draw_handler is None:
            self.draw_handler = bpy.types.SpaceView3D.draw_handler_add(
                self._draw, (), 'WINDOW', 'POST_PIXEL'
            )
            for area in bpy.context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

    def stop(self):
        if self.draw_handler is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self.draw_handler, 'WINDOW')
            self.draw_handler = None
            for area in bpy.context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

    def set_lines(self, lines):
        self.lines = list(lines) if lines else []
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


_hud_drawer = None


def get_hud_drawer():
    global _hud_drawer
    if _hud_drawer is None:
        _hud_drawer = HUDTextDrawer()
    return _hud_drawer


def start_hud_drawing(initial_lines=None):
    drawer = get_hud_drawer()
    if initial_lines:
        drawer.set_lines(initial_lines)
    drawer.start()


def update_hud_text(lines):
    drawer = get_hud_drawer()
    drawer.set_lines(lines)


def stop_hud_drawing():
    drawer = get_hud_drawer()
    drawer.stop()
