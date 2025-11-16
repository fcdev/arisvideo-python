#!/usr/bin/env python3
"""
Manim video quality optimizer.
Keeps rendered math graphics crisp and avoids overlap or alignment issues.
"""

import re
import ast
import numpy as np
from typing import Dict, List, Any, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

class ManimOptimizer:
    """Improves generated Manim scripts for consistent math visuals"""
    
    def __init__(self):
        # Define safe coordinate zones
        self.safe_bounds = {
            'title_zone': {'y_min': 2.5, 'y_max': 4.0},
            'left_zone': {'x_min': -6.0, 'x_max': -1.0, 'y_min': -2.5, 'y_max': 2.5},
            'right_zone': {'x_min': 1.0, 'x_max': 6.0, 'y_min': -2.5, 'y_max': 2.5},
            'buffer_zone': {'x_min': -1.0, 'x_max': 1.0}
        }
        
        # Recommended geometry sizing (slightly larger than default Manim)
        self.optimal_sizes = {
            'triangle_max_side': 1.8,     # allows larger example triangles
            'square_max_side': 1.6,
            'circle_max_radius': 1.3,
            'line_max_length': 2.2,
            'text_font_size': 16,
            'title_font_size': 32,
            'min_spacing': 0.3,
            'optimal_spacing': 0.4
        }
    
    def optimize_script(self, script: str) -> str:
        """
        Apply all optimization passes to a Manim script.
        """
        logger.info("Starting Manim script optimization...")
        
        # 1. Clamp extreme coordinates
        script = self._fix_coordinate_bounds(script)
        
        # 2. Normalize geometry sizes
        script = self._optimize_geometry_sizes(script)
        
        # 3. Enforce spacing controls
        script = self._enhance_spacing_control(script)
        
        # 4. Add precise positioning
        script = self._add_precise_positioning(script)
        
        # 5. Improve math rendering
        script = self._optimize_math_rendering(script)
        
        # 6. Add boundary validation
        script = self._add_boundary_validation(script)
        
        logger.info("Manim script optimization completed")
        return script
    
    def _fix_coordinate_bounds(self, script: str) -> str:
        """Clamp coordinates and sizes that exceed safe bounds"""
        
        # Relaxed coordinate fixes so shapes stay visible yet within frame
        coordinate_patterns = {
            # Constrain offsets for the right-hand side showcase area
            r'(\d+(?:\.\d+)?)\s*\*\s*RIGHT': lambda m: f"{min(1.8, float(m.group(1)))}*RIGHT" if float(m.group(1)) > 1.8 else m.group(0),
            r'(\d+(?:\.\d+)?)\s*\*\s*UP': lambda m: f"{min(2.0, float(m.group(1)))}*UP" if float(m.group(1)) > 2.0 else m.group(0),
            r'(\d+(?:\.\d+)?)\s*\*\s*DOWN': lambda m: f"{min(2.0, float(m.group(1)))}*DOWN" if float(m.group(1)) > 2.0 else m.group(0),
            r'(\d+(?:\.\d+)?)\s*\*\s*LEFT': lambda m: f"{min(1.8, float(m.group(1)))}*LEFT" if float(m.group(1)) > 1.8 else m.group(0),
            
            # Limit geometry size parameters
            r'side_length\s*=\s*(\d+(?:\.\d+)?)': lambda m: f"side_length={min(1.6, float(m.group(1)))}" if float(m.group(1)) > 1.6 else m.group(0),
            r'radius\s*=\s*(\d+(?:\.\d+)?)': lambda m: f"radius={min(1.3, float(m.group(1)))}" if float(m.group(1)) > 1.3 else m.group(0),
        }
        
        for pattern, replacement in coordinate_patterns.items():
            script = re.sub(pattern, replacement, script)
        
        return script
    
    def _optimize_geometry_sizes(self, script: str) -> str:
        """Normalize geometry size arguments for clearer visuals"""
        
        # Triangle sanity checks
        triangle_pattern = r'Polygon\s*\(\s*ORIGIN\s*,\s*([^,]+)\s*,\s*([^)]+)\)'
        def optimize_triangle(match):
            point1 = match.group(1).strip()
            point2 = match.group(2).strip()
            
            # Keep demo triangles compact
            if '*RIGHT' in point1 and '*UP' in point2:
                return f'Polygon(ORIGIN, 1.0*RIGHT, 1.0*RIGHT + 1.2*UP)'
            return match.group(0)
        
        script = re.sub(triangle_pattern, optimize_triangle, script)
        
        # Use friendlier default sizes for squares
        script = re.sub(
            r'Square\s*\(\s*side_length\s*=\s*\d+(?:\.\d+)?\s*\)',
            'Square(side_length=1.4)',
            script
        )
        
        # And for circles
        script = re.sub(
            r'Circle\s*\(\s*radius\s*=\s*\d+(?:\.\d+)?\s*\)',
            'Circle(radius=1.1)',
            script
        )
        
        return script
    
    def _enhance_spacing_control(self, script: str) -> str:
        """Force healthy spacing so shapes do not overlap"""
        
        # Inject sensible spacing defaults
        spacing_patterns = {
            r'\.arrange\s*\(\s*DOWN\s*\)': '.arrange(DOWN, buff=0.4)',
            r'\.arrange\s*\(\s*RIGHT\s*\)': '.arrange(RIGHT, buff=0.4)',
            r'\.arrange\s*\(\s*UP\s*\)': '.arrange(UP, buff=0.4)',
            r'\.arrange\s*\(\s*LEFT\s*\)': '.arrange(LEFT, buff=0.4)',
            r'\.next_to\s*\([^,]+,\s*[^,]+\s*\)': lambda m: m.group(0).replace(')', ', buff=0.3)'),
        }
        
        for pattern, replacement in spacing_patterns.items():
            if callable(replacement):
                script = re.sub(pattern, replacement, script)
            else:
                script = re.sub(pattern, replacement, script)
        
        return script
    
    def _add_precise_positioning(self, script: str) -> str:
        """Group and position generated graphics consistently"""
        
        # Track whether we have geometry to reposition
        positioning_fixes = []
        
        # If we detect shapes, ensure they are arranged on the right side
        if re.search(r'(Polygon|Square|Circle|Rectangle)\s*\([^)]*\)', script):
            if 'move_to(RIGHT*3)' not in script:
                # Inject grouping logic inside construct
                construct_pattern = r'(def construct\(self\):.*?)(self\.play)'
                def add_positioning(match):
                    construct_content = match.group(1)
                    play_start = match.group(2)
                    
                    # Add grouping/positioning code
                    positioning_code = '''
        
        # Automatic grouping + positioning for generated objects
        all_graphics = []
        for obj_name in dir():
            obj = locals().get(obj_name)
            if hasattr(obj, 'get_center') and obj_name not in ['title', 'text1', 'text2', 'text3', 'text4', 'text5']:
                all_graphics.append(obj)
        
        if all_graphics:
            graphics_group = VGroup(*all_graphics)
            graphics_group.arrange(DOWN, buff=0.4)
            graphics_group.move_to(RIGHT*3)
            graphics_group.scale(1.0)  # keep proportions without shrinking
        
        '''
                    return construct_content + positioning_code + play_start
                
                script = re.sub(construct_pattern, add_positioning, script, flags=re.DOTALL)
        
        return script
    
    def _optimize_math_rendering(self, script: str) -> str:
        """Standardize math rendering for clarity"""
        
        # Ensure math objects use the correct nodes
        math_optimizations = {
            # Avoid non-Latin glyphs that MathTex cannot render
            r'MathTex\s*\(\s*["\']([^"\']*[\u4e00-\u9fff][^"\']*)["\']': lambda m: f'Text("{m.group(1)}", font_size=20)',
            
            # Provide default font size
            r'MathTex\s*\(\s*([^)]+)\s*\)(?!\s*,\s*font_size)': r'MathTex(\1, font_size=24)',
        }
        
        for pattern, replacement in math_optimizations.items():
            if callable(replacement):
                script = re.sub(pattern, replacement, script)
            else:
                script = re.sub(pattern, replacement, script)
        
        return script
    
    def _add_boundary_validation(self, script: str) -> str:
        """Inject boundary validation so elements stay on screen"""
        
        # Append validation helper inside construct
        validation_code = '''
        
        # Boundary validation and auto-adjustment
        def validate_and_adjust_positions(scene_objects):
            for obj in scene_objects:
                if hasattr(obj, 'get_center'):
                    center = obj.get_center()
                    # Clamp to safe view frame
                    if center[0] > 5.5:  # right bound
                        obj.shift(LEFT * (center[0] - 5.0))
                    elif center[0] < -5.5:  # left bound
                        obj.shift(RIGHT * (-5.0 - center[0]))
                    
                    if center[1] > 3.5:  # upper bound
                        obj.shift(DOWN * (center[1] - 3.0))
                    elif center[1] < -3.5:  # lower bound
                        obj.shift(UP * (-3.0 - center[1]))
        
        # Run validation before the first animation
        all_scene_objects = [obj for obj in locals().values() if hasattr(obj, 'get_center')]
        validate_and_adjust_positions(all_scene_objects)
        '''
        
        # Insert validation before the first self.play
        script = re.sub(
            r'(\s+)(self\.play)',
            r'\1' + validation_code + r'\n\1\2',
            script,
            count=1
        )
        
        return script
    
    def generate_enhanced_system_prompt(self) -> str:
        """Return a stricter system prompt for Claude to follow"""
        
        return f"""
        
=== ENHANCED MANIM QUALITY CONTROL ===

CRITICAL MATHEMATICAL ACCURACY RULES:

1. PRECISE COORDINATE CONTROL:
   - Triangle vertices: NEVER exceed 1.0 unit in any direction
   - Square side_length: MAXIMUM 1.0 units
   - Circle radius: MAXIMUM 0.8 units
   - ALL graphics must fit within RIGHT zone: (1 < x < 6, -2.5 < y < 2.5)

2. ANTI-OVERLAP SYSTEM:
   - MANDATORY: Use VGroup().arrange(DOWN, buff=0.4) for vertical stacking
   - MANDATORY: Use VGroup().arrange(RIGHT, buff=0.4) for horizontal alignment
   - NEVER place objects at same coordinates without spacing
   - Use .next_to() with buff=0.3 minimum for adjacent elements

3. MATHEMATICAL PRECISION:
   - For right triangles: Polygon(ORIGIN, 1.0*RIGHT, 1.0*RIGHT + 1.2*UP)
   - For squares on triangle sides: match the exact side lengths
   - For Pythagorean theorem: a=1.0, b=1.2, c=√(1.0²+1.2²)=1.56
   - Use numpy for precise calculations: import numpy as np

4. POSITIONING ACCURACY:
   - ALWAYS use .move_to(RIGHT*3) for graphics group
   - ALWAYS use .scale(0.7) after positioning
   - NEVER use ORIGIN for final positioning
   - Check bounds: graphics.get_center() should be around (3, 0)

5. ENHANCED SPACING FORMULA:
   ```python
   # Correct spacing pattern
   shape1 = Circle(radius=0.6)
   shape2 = Square(side_length=0.8) 
   shape3 = Polygon(ORIGIN, 0.8*RIGHT, 0.8*RIGHT + 1.0*UP)
   
   graphics = VGroup(shape1, shape2, shape3)
   graphics.arrange(DOWN, buff=0.4)  # Prevent overlap
   graphics.move_to(RIGHT*3)         # Right zone
   graphics.scale(0.7)               # Safe scaling
   ```

6. QUALITY VALIDATION:
   - Before animations: verify no overlaps
   - Check all coordinates are within bounds
   - Ensure mathematical relationships are accurate
   - Test visual clarity and readability

RETURN ONLY mathematically precise, visually clear Python code.
        """

def enhance_script_generation_prompt(original_prompt: str) -> str:
    """Append the enhanced quality rules to an LLM prompt"""
    
    optimizer = ManimOptimizer()
    enhanced_section = optimizer.generate_enhanced_system_prompt()
    
    # Append the quality block to the original instructions
    enhanced_prompt = original_prompt + enhanced_section
    
    return enhanced_prompt

def validate_manim_quality(script: str) -> Dict[str, Any]:
    """Lint a Manim script for layout violations"""
    
    issues = []
    
    # Coordinate checks
    large_coords = re.findall(r'(\d+(?:\.\d+)?)\s*\*\s*(?:RIGHT|UP|DOWN|LEFT)', script)
    for coord in large_coords:
        if float(coord) > 1.5:
            issues.append(f"Coordinate too large: {coord} (suggest ≤ 1.0)")
    
    # Spacing checks
    if '.arrange(' in script and 'buff=' not in script:
        issues.append("Missing spacing (buff) configuration; objects may overlap")
    
    # Positioning checks
    if ('Polygon(' in script or 'Square(' in script) and 'move_to(RIGHT*3)' not in script:
        issues.append("Graphics not positioned in the right-side showcase zone")
    
    # Size checks
    side_lengths = re.findall(r'side_length\s*=\s*(\d+(?:\.\d+)?)', script)
    for size in side_lengths:
        if float(size) > 1.2:
            issues.append(f"Shape size too large: {size} (suggest ≤ 1.0)")
    
    return {
        'has_issues': len(issues) > 0,
        'issues': issues,
        'score': max(0, 100 - len(issues) * 20)  # simple quality score
    }
