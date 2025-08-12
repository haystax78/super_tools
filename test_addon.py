import bpy
import sys
import os

# Add the super_tools directory to the path
addon_path = os.path.dirname(os.path.abspath(__file__))
if addon_path not in sys.path:
    sys.path.append(addon_path)


def test_addon_registration():
    """Test that the addon can be registered and unregistered"""
    try:
        # Register the addon
        bpy.ops.preferences.addon_enable(module="super_tools")
        print("Addon registered successfully")
        
        # Check if the operator is available
        if hasattr(bpy.ops.mesh, "super_extrude_modal"):
            print("Operator is available")
        else:
            print("ERROR: Operator not found")
            
        # Unregister the addon
        bpy.ops.preferences.addon_disable(module="super_tools")
        print("Addon unregistered successfully")
        
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def run_tests():
    """Run all tests"""
    print("Running Super Extrude addon tests...")
    
    success = test_addon_registration()
    
    if success:
        print("All tests passed!")
    else:
        print("Some tests failed!")
    
    return success


if __name__ == "__main__":
    run_tests()
