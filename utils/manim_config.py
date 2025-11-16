#!/usr/bin/env python3
"""
Manim optimization configuration helpers.
"""

# Manim render quality presets
MANIM_QUALITY_SETTINGS = {
    'l': {  # Low quality (480p)
        'resolution': '480p15',
        'frame_rate': 15,
        'coordinates_scale': 0.8,
        'font_scale': 0.9
    },
    'm': {  # Medium quality (720p) - default
        'resolution': '720p30', 
        'frame_rate': 30,
        'coordinates_scale': 1.0,
        'font_scale': 1.0
    },
    'h': {  # High quality (1080p)
        'resolution': '1080p60',
        'frame_rate': 60,
        'coordinates_scale': 1.2,
        'font_scale': 1.1
    },
    'p': {  # Production quality
        'resolution': '1440p60',
        'frame_rate': 60,
        'coordinates_scale': 1.4,
        'font_scale': 1.2
    },
    'k': {  # 4K quality
        'resolution': '2160p60',
        'frame_rate': 60,
        'coordinates_scale': 1.6,
        'font_scale': 1.3
    }
}

# Geometry optimization parameters
MATH_OPTIMIZATION_CONFIG = {
    # Base geometry sizing (slightly larger for clarity)
    'max_triangle_side': 1.5,     # increased from 1.0
    'max_square_side': 1.4,       # increased from 1.0
    'max_circle_radius': 1.2,     # increased from 0.8
    'max_line_length': 2.0,       # increased from 1.5
    
    # Spacing control
    'min_spacing': 0.3,
    'optimal_spacing': 0.4,
    'safe_spacing': 0.5,
    
    # Layout regions
    'title_zone_y': 2.5,
    'left_zone_x_range': (-6.0, -1.0),
    'right_zone_x_range': (1.0, 6.0),
    'content_zone_y_range': (-2.5, 2.5),
    
    # Font sizes
    'title_font_size': 32,
    'text_font_size': 16,
    'math_font_size': 20,
    
    # Scaling adjustments
    'graphics_scale': 1.0,        # do not shrink demo graphics
    'safe_scale': 0.85,           
    'emergency_scale': 0.7
}

# Quality checks
QUALITY_THRESHOLDS = {
    'coordinate_limit': 1.5,
    'size_limit': 1.2,
    'spacing_minimum': 0.2,
    'quality_score_minimum': 70,
    'max_retry_attempts': 3
}

def get_quality_config(resolution: str) -> dict:
    """Return render settings for a quality key."""
    return MANIM_QUALITY_SETTINGS.get(resolution, MANIM_QUALITY_SETTINGS['m'])

def get_math_config() -> dict:
    """Return math optimization parameters."""
    return MATH_OPTIMIZATION_CONFIG

def get_quality_thresholds() -> dict:
    """Return quality validation thresholds."""
    return QUALITY_THRESHOLDS
