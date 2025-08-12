"""
Axis constraint utilities for modal operators.
Provides consistent axis constraint functionality across Super Extrude and Super Orient operators.
"""

import mathutils


class AxisConstraintState:
    """Manages axis constraint state for modal operators"""
    
    def __init__(self):
        self.constraint_axis = None  # None, 'X', 'Y', 'Z'
        self.constraint_plane = None  # None, 'YZ', 'XZ', 'XY' (plane mode)
    
    def handle_constraint_event(self, event, operator_name=""):
        """
        Handle axis constraint keyboard events.
        
        Args:
            event: Blender event object
            operator_name: Name of the operator for debug output
            
        Returns:
            bool: True if event was handled, False otherwise
        """
        if event.type in {'X', 'Y', 'Z'} and event.value == 'PRESS':
            if event.alt:
                # Plane constraint (Alt + axis key)
                if event.type == 'X':
                    self.constraint_plane = 'YZ' if self.constraint_plane != 'YZ' else None
                elif event.type == 'Y':
                    self.constraint_plane = 'XZ' if self.constraint_plane != 'XZ' else None
                elif event.type == 'Z':
                    self.constraint_plane = 'XY' if self.constraint_plane != 'XY' else None
                self.constraint_axis = None  # Clear axis constraint when setting plane
                print(f"{operator_name}: Plane constraint set to {self.constraint_plane}")
            else:
                # Single axis constraint
                axis = event.type
                self.constraint_axis = axis if self.constraint_axis != axis else None
                self.constraint_plane = None  # Clear plane constraint when setting axis
                print(f"{operator_name}: Axis constraint set to {self.constraint_axis}")
            return True
        return False
    
    def apply_constraint(self, translation):
        """
        Apply axis constraints to translation vector.
        
        Args:
            translation: mathutils.Vector to constrain
            
        Returns:
            mathutils.Vector: Constrained translation vector
        """
        if self.constraint_axis:
            # Single axis constraint
            if self.constraint_axis == 'X':
                return mathutils.Vector((translation.x, 0, 0))
            elif self.constraint_axis == 'Y':
                return mathutils.Vector((0, translation.y, 0))
            elif self.constraint_axis == 'Z':
                return mathutils.Vector((0, 0, translation.z))
        elif self.constraint_plane:
            # Plane constraint (exclude one axis)
            if self.constraint_plane == 'YZ':  # Exclude X
                return mathutils.Vector((0, translation.y, translation.z))
            elif self.constraint_plane == 'XZ':  # Exclude Y
                return mathutils.Vector((translation.x, 0, translation.z))
            elif self.constraint_plane == 'XY':  # Exclude Z
                return mathutils.Vector((translation.x, translation.y, 0))
        
        # No constraint - return original translation
        return translation
    
    def clear_constraints(self):
        """Clear all active constraints"""
        self.constraint_axis = None
        self.constraint_plane = None
    
    def get_constraint_description(self):
        """Get human-readable description of current constraint"""
        if self.constraint_axis:
            return f"Axis: {self.constraint_axis}"
        elif self.constraint_plane:
            return f"Plane: {self.constraint_plane}"
        else:
            return "No constraint"


def create_constraint_state():
    """Factory function to create a new AxisConstraintState instance"""
    return AxisConstraintState()
