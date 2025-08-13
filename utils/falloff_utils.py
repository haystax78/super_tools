"""
Unified falloff curve utilities for proportional editing.

This module provides consistent falloff calculations across all operators,
ensuring we have a single source of truth for falloff curve implementations.
"""

import numpy as np
import math


def calculate_falloff_weight_scalar(normalized_distance, falloff_type):
    """
    Calculate falloff weight for a single normalized distance value.
    
    Args:
        normalized_distance: Distance normalized to 0.0-1.0 range
        falloff_type: Falloff type string ('SMOOTH', 'SPHERE', 'ROOT', etc.)
        
    Returns:
        float: Weight value from 0.0 to 1.0
    """
    t = max(0.0, min(1.0, normalized_distance))  # Clamp to [0,1]
    
    if falloff_type == 'SMOOTH':
        # Smooth hermite interpolation: 1 - smoothstep(t)
        return 1.0 - (3.0 * t * t - 2.0 * t * t * t)
    
    elif falloff_type == 'SPHERE':
        # Spherical falloff: cosine-based quarter circle
        if t >= 1.0:
            return 0.0
        return math.cos(t * math.pi * 0.5)
    
    elif falloff_type == 'ROOT':
        # Root falloff: square root curve
        return max(0.0, (1.0 - t) ** 0.5)
    
    elif falloff_type == 'INVERSE_SQUARE':
        # Normalized inverse square: ensures w(0)=1 and w(1)=0
        if t >= 1.0:
            return 0.0
        # Remapped to reach exactly zero at t=1
        a = 4.0
        base = 1.0 / (1.0 + a * t * t)
        return (((1.0 + a) * base) - 1.0) / a
    
    elif falloff_type == 'SHARP':
        # Sharp falloff: cubic curve for characteristic cliff-like drop-off
        return (1.0 - t) ** 3
    
    elif falloff_type == 'LINEAR':
        # Linear falloff: straight line from 1.0 to 0.0
        return max(0.0, 1.0 - t)
    
    elif falloff_type == 'CONSTANT':
        # Constant falloff: full influence within radius
        return 1.0 if t < 1.0 else 0.0
    
    elif falloff_type == 'RANDOM':
        # Random falloff: linear base curve with random variation subtracted (matching Blender)
        # Use distance value as seed for consistent per-vertex randomness
        import random
        random.seed(int(normalized_distance * 10000) % 2147483647)  # Use distance as seed
        linear_weight = max(0.0, 1.0 - normalized_distance)
        random_factor = random.random()  # 0.0 to 1.0
        return max(0.0, linear_weight - (random_factor * linear_weight * 0.5))  # Subtract up to 50% randomly
    
    else:
        # Default to smooth
        return 1.0 - (3.0 * t * t - 2.0 * t * t * t)


def calculate_falloff_weights_vectorized(distances, radius, falloff_type):
    """
    Calculate falloff weights for an array of distances using NumPy vectorization.
    
    Args:
        distances: NumPy array of distance values
        radius: Maximum radius for falloff
        falloff_type: Falloff type string
        
    Returns:
        NumPy array: Weight values from 0.0 to 1.0
    """
    if distances.size == 0:
        return np.array([], dtype=np.float32)
    
    # Normalize distances to [0,1] range
    t = np.clip(distances / max(radius, 1e-12), 0.0, 1.0).astype(np.float32)
    
    if falloff_type == 'SMOOTH':
        # Smooth hermite: 1 - smoothstep(t)
        return 1.0 - (t * t * (3.0 - 2.0 * t))
    
    elif falloff_type == 'SPHERE':
        # Spherical: sqrt(1 - t^2)
        return np.sqrt(np.clip(1.0 - t * t, 0.0, 1.0))
    
    elif falloff_type == 'ROOT':
        # Root: sqrt(1 - t)
        return np.sqrt(np.clip(1.0 - t, 0.0, 1.0))
    
    elif falloff_type == 'INVERSE_SQUARE':
        # Normalized inverse square: ensures w(0)=1 and w(1)=0
        a = 4.0
        base = 1.0 / (1.0 + a * (t * t))
        return (((1.0 + a) * base) - 1.0) / a
    
    elif falloff_type == 'SHARP':
        # Sharp falloff: cubic curve for cliff-like drop-off
        return (1.0 - t) ** 3
    
    elif falloff_type == 'LINEAR':
        # Linear: 1 - t
        return np.clip(1.0 - t, 0.0, 1.0)
    
    elif falloff_type == 'CONSTANT':
        # Constant: 1 inside radius, 0 at/after radius
        return (t < 1.0).astype(np.float32)
    
    elif falloff_type == 'RANDOM':
        # Random falloff: linear base curve with random variation subtracted (matching Blender)
        linear_weights = np.clip(1.0 - t, 0.0, 1.0)
        # Use distance values as seeds for consistent per-vertex randomness
        seeds = (t * 10000).astype(np.int32) % 2147483647
        # Generate random factors using vectorized approach
        random_factors = np.array([np.random.RandomState(seed).random() for seed in seeds], dtype=np.float32)
        # Subtract random variation from linear base (up to 50% of linear weight)
        return np.maximum(0.0, linear_weights - (random_factors * linear_weights * 0.5))
    
    else:
        # Default to smooth
        return 1.0 - (t * t * (3.0 - 2.0 * t))


def get_available_falloff_types():
    """
    Get list of all available falloff types.
    
    Returns:
        list: Available falloff type strings
    """
    return [
        'SMOOTH',
        'SPHERE', 
        'ROOT',
        'INVERSE_SQUARE',
        'SHARP',
        'LINEAR',
        'CONSTANT',
        'RANDOM'
    ]


def get_falloff_description(falloff_type):
    """
    Get human-readable description of a falloff type.
    
    Args:
        falloff_type: Falloff type string
        
    Returns:
        str: Description of the falloff curve
    """
    descriptions = {
        'SMOOTH': 'Smooth hermite curve with gradual transitions',
        'SPHERE': 'Spherical falloff using cosine curve',
        'ROOT': 'Square root curve for gentle falloff',
        'INVERSE_SQUARE': 'Inverse square relationship with sharp center',
        'SHARP': 'Cubic curve with cliff-like drop-off at edge',
        'LINEAR': 'Linear falloff from center to edge',
        'CONSTANT': 'Constant influence within radius',
        'RANDOM': 'Random weights for each vertex'
    }
    return descriptions.get(falloff_type, 'Unknown falloff type')
