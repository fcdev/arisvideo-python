"""
Script generation service using Claude AI for Manim animations.
"""

import os
import re
import tempfile
import importlib.util
from typing import List, Dict, Any, Optional
import anthropic
from anthropic.types import MessageParam, TextBlock
from fastapi import HTTPException
import logging
from .manim_optimizer import ManimOptimizer, enhance_script_generation_prompt, validate_manim_quality

logger = logging.getLogger(__name__)


def get_anthropic_client():
    """Initialize Anthropic client."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=api_key)


def extract_python_code(text: str) -> str:
    """
    Extract Python code from markdown code blocks or plain text.
    Removes ```python and ``` markers if present.
    """
    # Remove markdown code block markers
    # Match ```python or ``` at start and ``` at end
    code_block_pattern = r'^```(?:python)?\s*\n?(.*?)\n?```$'
    match = re.search(code_block_pattern, text, re.DOTALL)
    
    if match:
        return match.group(1).strip()
    
    # If no code block markers, return the text as-is
    return text.strip()


def extract_text_from_content(content) -> str:
    """
    Safely extract text from Anthropic content blocks.
    """
    if isinstance(content, TextBlock):
        return content.text
    else:
        return str(content)


async def generate_and_refine_manim_script(
    client: anthropic.Anthropic, 
    prompt: str, 
    max_attempts: int = 5,
    target_duration: float = 45.0,
    language: str = "en",
    file_context: Optional[str] = None
) -> str:
    """
    Generate a Manim script and refine it if it fails to execute.
    """
    conversation_history: List[MessageParam] = []
    analyzed_content = None  # cache structured analysis of uploaded materials
    
    for attempt in range(max_attempts):
        logger.info(f"Attempt {attempt + 1}/{max_attempts} to generate/refine script")
        
        try:
            # Generate or refine the script
            if attempt == 0:
                # First attempt: generate new script
                script, analyzed_content = await generate_manim_script(client, prompt, conversation_history, target_duration, language, file_context)
            else:
                # Subsequent attempts: refine based on error
                script = await refine_manim_script(client, prompt, conversation_history, language)
            
            # Test the script
            test_result = await test_manim_script(script)
            
            if test_result["success"]:
                # When uploads are provided, make sure the script covers their concepts
                if file_context and analyzed_content:
                    key_concepts = analyzed_content.get('key_concepts', [])
                    coverage = verify_content_coverage(script, file_context, key_concepts)
                    
                    # Only force a regen when coverage is low and we still have attempts left
                    if coverage < 0.4 and attempt < max_attempts - 2:
                        logger.info(f"Coverage too low ({coverage:.2f}); regenerating to incorporate uploaded content")
                        conversation_history.append({
                            "role": "assistant",
                            "content": script
                        })
                        conversation_history.append({
                            "role": "user",
                            "content": f"The animation doesn't include enough content from the uploaded materials. Please regenerate focusing more on the uploaded content, especially these concepts: {', '.join(key_concepts)}. Make sure to create visual animations for these key points."
                        })
                        continue
                
                logger.info(f"Script successfully generated on attempt {attempt + 1}")
                return script
            else:
                # If it's a geometry framing issue on the last attempts, try auto-fix
                if attempt >= max_attempts - 2 and "geometry framing" in test_result['error'].lower():
                    logger.info(f"Attempting automatic coordinate fix on attempt {attempt + 1}")
                    auto_fixed_script = auto_fix_large_coordinates(script)
                    if auto_fixed_script != script:
                        auto_test_result = await test_manim_script(auto_fixed_script)
                        if auto_test_result["success"]:
                            logger.info(f"Auto-fix successful on attempt {attempt + 1}")
                            return auto_fixed_script
                
                # Add error to conversation history for refinement
                conversation_history.append({
                    "role": "assistant",
                    "content": script
                })
                conversation_history.append({
                    "role": "user", 
                    "content": f"The script failed with error: {test_result['error']}. Please fix this issue and provide a corrected version."
                })
                
                logger.warning(f"Script failed on attempt {attempt + 1}: {test_result['error']}")
                
        except Exception as e:
            error_message = str(e)
            logger.error(f"Error on attempt {attempt + 1}: {error_message}")
            
            # Handle different types of errors with specific strategies
            if "overloaded" in error_message.lower() or "529" in error_message:
                # API overload - wait before retry
                import asyncio
                wait_time = min(2 ** attempt, 10)  # Exponential backoff, max 10 seconds
                logger.info(f"API overloaded, waiting {wait_time} seconds before retry...")
                await asyncio.sleep(wait_time)
                
                # For overload errors, preserve conversation history and try again
                continue
                
            elif "Bad Request" in error_message and "messages" in error_message:
                # Message validation error - reset conversation history
                logger.warning("Message validation error, resetting conversation history")
                conversation_history = []
                continue
                
            elif "Failed to refine script" in error_message:
                # Refinement failed - try with fresh conversation history
                logger.warning("Script refinement failed, clearing conversation history for fresh start")
                conversation_history = []
                continue
            
            # If this is the last attempt, raise the error
            if attempt == max_attempts - 1:
                raise Exception(f"Failed to generate working script after {max_attempts} attempts: {error_message}")
    
    raise Exception(f"Failed to generate working script after {max_attempts} attempts")


async def generate_manim_script(
    client: anthropic.Anthropic, 
    prompt: str, 
    conversation_history: Optional[List[MessageParam]] = None,
    target_duration: float = 45.0,
    language: str = "en",
    file_context: Optional[str] = None
) -> tuple[str, Optional[Dict[str, Any]]]:
    """
    Use Claude to generate a Manim script based on the user's prompt.
    
    Returns:
        Tuple of (generated_script, analyzed_content)
    """
    # Language mapping for clear instructions
    language_names = {
        'en': 'English', 'es': 'Spanish', 'fr': 'French', 'de': 'German',
        'it': 'Italian', 'pt': 'Portuguese', 'ru': 'Russian', 'ja': 'Japanese',
        'ko': 'Korean', 'zh': 'Chinese', 'ar': 'Arabic', 'hi': 'Hindi'
    }
    language_name = language_names.get(language, 'English')
    
    system_prompt = f"""You are an expert in creating educational animations using the Manim library. 
    Generate a complete, runnable Python script using Manim that creates an educational animation based on the user's prompt.

    UPLOADED CONTENT HANDLING (when provided):
    - If the user has uploaded files, the content will be provided after their prompt
    - You MUST base your animation on the KEY CONCEPTS from the uploaded materials
    - Extract and visualize important formulas, data, or diagrams from the files
    - Follow the structure and flow of the uploaded content
    - The user's prompt indicates HOW to present the uploaded content
    - Create animations that explain or demonstrate the uploaded material
    - Prioritize content from uploaded files over general knowledge

    LANGUAGE REQUIREMENT: Generate ALL text content (titles, explanations, labels) in {language_name} language.
    Make sure all Text() and MathTex() objects use {language_name} language appropriate to the content.

    TARGET DURATION: {target_duration:.0f} seconds - Design the animation to match this duration exactly.

    Requirements:
    1. Import necessary modules from manim
    2. Create a Scene class with a descriptive name
    3. Implement the construct() method with the animation logic
    4. Use appropriate Manim objects (Text, MathTex, shapes, etc.)
    5. Include smooth animations and transitions
    6. Add explanatory text and visual elements
    7. Make it educational and engaging
    8. Ensure the script is complete and runnable
    9. Handle common Manim errors (missing imports, syntax errors, etc.)

    CRITICAL VIDEO LAYOUT Guidelines (MUST FOLLOW):
    
    === SCREEN LAYOUT STRUCTURE ===
    The video screen is divided into specific zones:
    - Title Zone: Top area (y > 2.5) - for main title only
    - Content Zone: Middle area (-2.5 < y < 2.5) - split into left and right sections
      * Left Section: (-6 < x < -1) - for narration text, left-aligned
      * Right Section: (1 < x < 6) - for graphics/animations, centered
    - Buffer zones: x = [-1, 1] - keep clear to avoid overlap
    
    === POSITIONING RULES ===
    1. TITLE positioning:
       - title = Text("Your Title").scale(0.8)
       - title.to_edge(UP, buff=0.5)  # Fixed at top
    
    2. NARRATION TEXT positioning:
       - Use Text() objects, NOT MathTex() for explanatory text
       - FONT SIZE: Use .scale(0.5) or font_size=16-18 for all explanatory text (half of normal size)
       - Position: text.to_corner(UL, buff=0.8).shift(DOWN*0.5)
       - Multiple text blocks: stack vertically with .shift(DOWN*0.6) between them
       - Keep text in left zone: x-coordinate should be around -4 to -1.5
       - Left-align text: text.align_to(LEFT*4, LEFT)
       - Text should be compact and readable in left zone
    
    3. GRAPHICS positioning:
       - All visual elements (shapes, diagrams) go in RIGHT section
       - Center graphics horizontally: graphics.move_to(RIGHT*3)
       - Vertical centering: graphics.move_to(RIGHT*3 + UP*0)
       - Keep graphics compact: use .scale(0.6) to .scale(0.8)
       - PREVENT OVERLAPPING: Use proper spacing with buff=0.2-0.4 between elements
       - PREVENT MISALIGNMENT: Use .arrange() or .next_to() for proper positioning
       - Group related elements: VGroup(elements).arrange(DOWN, buff=0.3)
    
    === LAYOUT EXAMPLE STRUCTURE ===
    ```python
    def construct(self):
        # Title - fixed at top
        title = Text("Topic Title").scale(0.8)
        title.to_edge(UP, buff=0.5)
        
        # Narration text - left side, stacked vertically, SMALLER FONT
        text1 = Text("First explanation point", font_size=16)
        text1.to_corner(UL, buff=0.8).shift(DOWN*0.5)
        
        text2 = Text("Second explanation point", font_size=16)  
        text2.next_to(text1, DOWN, aligned_edge=LEFT, buff=0.3)
        
        text3 = Text("Third explanation point", font_size=16)
        text3.next_to(text2, DOWN, aligned_edge=LEFT, buff=0.3)
        
        # Graphics - right side, centered, NO OVERLAPPING
        shape1 = Circle(radius=1.0)        # expanded from 0.5 for clarity
        shape2 = Square(side_length=1.3)   # expanded from 0.8 for clarity
        shape3 = Triangle().scale(1.0)     # expanded from 0.6 for clarity
        
        # Arrange graphics properly to avoid overlapping
        graphics = VGroup(shape1, shape2, shape3)
        graphics.arrange(DOWN, buff=0.3)  # Stack vertically with spacing
        graphics.move_to(RIGHT*3)  # Position in right zone
        graphics.scale(0.9)        # scale less aggressively than the 0.7 default
        
        # Animation sequence
        self.play(Write(title))
        self.play(Write(text1))
        self.play(Create(graphics))
        self.wait(2)
        self.play(Write(text2))
        # ... more animations
    ```

    IMPORTANT Manim Guidelines:
    - DON'T use get_angle() on Polygon objects (doesn't exist)
    - Use numpy for angle calculations: import numpy as np
    - For right triangles, calculate angles with np.arctan2()
    - Use get_vertices() to access polygon points
    - Use rotate() with calculated angles, not get_angle()
    - Test positioning with get_center(), get_corner(), etc.
    - CRITICAL: axes.c2p() only accepts coordinates as parameters, NOT buff or other kwargs
      WRONG: axes.c2p(1, 0, buff=0.3)
      CORRECT: axes.c2p(1, 0)
    
    TEXT AND LANGUAGE Guidelines:
    - Use Text() for non-English text, NOT MathTex() 
    - MathTex() only supports basic Latin characters and math symbols
    - For Chinese/Japanese/Korean: use Text("[non-Latin text]") not MathTex("[non-Latin text]")
    - For math with non-English: combine Text() and MathTex() separately
    - Example: VGroup(MathTex("x = 1"), Text(" or "), MathTex("x = -3"))
    
    MANIM OBJECT Guidelines:
    - Use Polygon() to create triangles, NOT RightTriangle()
    - Use Square(), Circle(), Rectangle() for basic shapes
    - Use Line() and DashedLine() for lines
    - Example right triangle: Polygon(ORIGIN, 1.5*RIGHT, 1.5*RIGHT + 2*UP)
    - Use VMobject and VGroup for grouping objects
    
    MANIM RIEMANN RECTANGLES Guidelines (CRITICAL):
    - CORRECT usage: axes.get_riemann_rectangles(curve, x_range=[a, b], dx=step)
    - DO NOT pass 'opacity' parameter directly to get_riemann_rectangles()
    - Set opacity AFTER creation: rectangles.set_fill(opacity=0.6)
    - Example correct usage:
      rectangles = axes.get_riemann_rectangles(curve, x_range=[1, 3], dx=0.5, color=GREEN)
      rectangles.set_fill(opacity=0.6)  # Set opacity separately
    - Available parameters: curve, x_range, dx, color (NOT opacity)
    
    GEOMETRY SIZING Guidelines (CRITICAL):
    - Geometry can be LARGER for better visibility in RIGHT section
    - Triangle sides should be 1.5-2.0 units max (increased from 1-1.5)
    - Use .scale(0.8) to .scale(1.0) for better visibility (increased scaling)
    - ALL graphics must fit within RIGHT section: (1 < x < 6, -2.5 < y < 2.5)
    - Position graphics: graphics.move_to(RIGHT*3) then fine-tune with small shifts
    
    DURATION-SPECIFIC PACING for {target_duration:.0f} seconds:
    - Plan timing to reach exactly {target_duration:.0f} seconds total
    - Use animation durations of 4-6 seconds each
    - Add self.wait(3-4) between major sections
    - Use run_time=5 or higher for complex animations
    - Include longer pauses: self.wait(3) after each concept
    - Add substantial wait at the end: self.wait(4)
    - For mathematical concepts: use self.wait(5) for processing time
    - Break content into {max(3, int(target_duration/15))} main sections with pauses

    Return ONLY the Python code, no additional text or explanations."""
    
    # Strengthen the system prompt with quality controls
    system_prompt = enhance_script_generation_prompt(system_prompt)
    
    # Prepare user message with optional file context
    local_analyzed_content = None
    if file_context:
        # Analyze uploaded context before building the user message
        logger.info("📋 Analyzing uploaded reference material...")
        local_analyzed_content = await analyze_uploaded_content(client, file_context, prompt, language)
        
        if local_analyzed_content:
            # Build a richer user message based on the analysis
            concepts_str = ', '.join(local_analyzed_content.get('key_concepts', []))
            formulas_str = ', '.join(local_analyzed_content.get('formulas', []))
            suggestions_str = ', '.join(local_analyzed_content.get('animation_suggestions', []))
            
            # Log the structured analysis for debugging
            logger.info("=" * 120)
            logger.info("📋 Upload analysis results")
            logger.info(f"   ✨ Content type: {local_analyzed_content.get('content_type', 'Unknown')}")
            logger.info(f"   🔑 Key concepts: {concepts_str}")
            logger.info(f"   🎯 Educational focus: {local_analyzed_content.get('educational_focus', 'N/A')}")
            logger.info(f"   📐 Formulas: {formulas_str}")
            logger.info(f"   🎬 Animation suggestions: {suggestions_str}")
            logger.info("-" * 120)
            logger.info("📄 Uploaded content preview")
            logger.info(f"{file_context[:500]}...")
            if len(file_context) > 500:
                logger.info(f"... (total {len(file_context)} chars)")
            logger.info("=" * 120)
            
            user_message = f"""Create an educational animation based on the following uploaded material:

User's Request: {prompt}

Material Analysis:
- Type: {local_analyzed_content.get('content_type', 'Unknown')}
- Key Concepts: {concepts_str}
- Educational Focus: {local_analyzed_content.get('educational_focus', 'General explanation')}
{f'- Formulas Found: {formulas_str}' if formulas_str else ''}
{f'- Animation Suggestions: {suggestions_str}' if suggestions_str else ''}

Full Uploaded Content:
{file_context}

CRITICAL: Base your animation on the KEY CONCEPTS and STRUCTURE from the uploaded material. The user's request indicates how to present this content. Focus on making the uploaded content visual and engaging."""
            
            # Log the final prompt sent to Claude
            logger.info("-" * 120)
            logger.info("🚀 Final prompt sent to Claude")
            logger.info("-" * 120)
            logger.info(user_message)
            logger.info("=" * 120)
        else:
            # Fall back to simpler messaging if analysis fails
            user_message = f"""Create an educational animation about: {prompt}

Uploaded Content Context:
{file_context}

IMPORTANT: Use the uploaded content as the primary source for your animation."""
            
            logger.info("=" * 120)
            logger.info("⚠️ Upload analysis failed, falling back to raw context")
            logger.info("-" * 120)
            logger.info("📄 Uploaded content")
            logger.info(f"{file_context[:500]}...")
            if len(file_context) > 500:
                logger.info(f"... (total {len(file_context)} chars)")
            logger.info("-" * 120)
            logger.info("🚀 Final prompt sent to Claude")
            logger.info("-" * 120)
            logger.info(user_message)
            logger.info("=" * 120)
    else:
        user_message = f"Create an educational animation about: {prompt}"
        logger.info("=" * 120)
        logger.info("📝 No uploads provided; using user prompt only")
        logger.info("-" * 120)
        logger.info("👤 User input")
        logger.info(f"{prompt}")
        logger.info("-" * 120)
        logger.info("🚀 Final prompt sent to Claude")
        logger.info("-" * 120)
        logger.info(user_message)
        logger.info("=" * 120)
    
    messages: List[MessageParam] = [{"role": "user", "content": user_message}]
    
    if conversation_history:
        messages = conversation_history + messages
    
    try:
        # Validate messages before API call
        if not messages or len(messages) == 0:
            raise Exception("No messages provided for script generation")
        
        logger.info(f"Generating script with {len(messages)} messages")
        
        # Log the full Claude API payload for debugging
        logger.info("🤖 Claude API call details")
        logger.info("=" * 120)
        logger.info("📋 System prompt")
        logger.info(system_prompt)
        logger.info("=" * 120)
        logger.info("💬 Messages")
        for i, msg in enumerate(messages):
            logger.info(f"Message {i+1} ({msg['role']}):")
            logger.info(msg['content'])
            if i < len(messages) - 1:
                logger.info("-" * 60)
        logger.info("=" * 120)
        
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4000,
            system=system_prompt,
            messages=messages
        )
        
        # Handle different response formats and extract Python code
        content = message.content[0]
        raw_response = extract_text_from_content(content)
        
        # Extract Python code from the response
        python_code = extract_python_code(raw_response)
        
        # Run the generated script through quality optimizations
        optimizer = ManimOptimizer()
        optimized_code = optimizer.optimize_script(python_code)
        
        # Validate the optimized code quality
        quality_report = validate_manim_quality(optimized_code)
        logger.info(f"Code quality score: {quality_report['score']}/100")
        if quality_report['has_issues']:
            logger.warning(f"Quality issues detected: {quality_report['issues']}")
        
        return optimized_code, local_analyzed_content
        
    except anthropic.BadRequestError as e:
        logger.error(f"Bad request error in generate_manim_script: {str(e)}")
        raise Exception(f"Failed to generate script with Claude (Bad Request): {str(e)}")
    except anthropic.APIError as e:
        if "overloaded" in str(e).lower() or "529" in str(e):
            logger.warning(f"Claude API overloaded during script generation: {str(e)}")
            raise Exception(f"Claude API temporarily overloaded: {str(e)}")
        else:
            logger.error(f"Claude API error in generate_manim_script: {str(e)}")
            raise Exception(f"Failed to generate script with Claude (API Error): {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in generate_manim_script: {str(e)}")
        raise Exception(f"Failed to generate script with Claude: {str(e)}")


async def refine_manim_script(
    client: anthropic.Anthropic, 
    prompt: str, 
    conversation_history: List[MessageParam],
    language: str = "en"
) -> str:
    """
    Refine a Manim script based on previous errors.
    """
    # Validate conversation_history before API call
    if not conversation_history or len(conversation_history) == 0:
        logger.warning("Empty conversation history, creating minimal message for refinement")
        conversation_history = [
            {"role": "user", "content": f"Please create a Manim script for: {prompt}"}
        ]
    
    # Ensure the last message is from user (required for refinement context)
    if conversation_history[-1]["role"] != "user":
        logger.info("Adding user context to conversation history")
        conversation_history.append({
            "role": "user", 
            "content": "Please fix any issues in the previous script and provide a corrected version."
        })
    
    # Language mapping
    language_names = {
        'en': 'English', 'es': 'Spanish', 'fr': 'French', 'de': 'German',
        'it': 'Italian', 'pt': 'Portuguese', 'ru': 'Russian', 'ja': 'Japanese',
        'ko': 'Korean', 'zh': 'Chinese', 'ar': 'Arabic', 'hi': 'Hindi'
    }
    language_name = language_names.get(language, 'English')
    
    system_prompt = f"""You are an expert in debugging and fixing Manim scripts. 
    Analyze the error message and provide a corrected version of the script.
    
    LANGUAGE REQUIREMENT: Ensure ALL text content (titles, explanations, labels) remains in {language_name} language.
    Do not change the language of existing text when fixing errors.
    
    Common fixes:
    - Add missing imports
    - Fix syntax errors
    - Correct class names and method calls
    - Ensure proper Manim object usage
    - Fix indentation issues
    - TypeError: can't multiply sequence by non-int - Fix by converting tuples to numpy arrays
      Example: triangle.get_vertices()[2] + 0.75*(np.cos(...), np.sin(...), 0) 
      Fix to: triangle.get_vertices()[2] + 0.75*np.array([np.cos(...), np.sin(...), 0])
    
    CRITICAL VIDEO LAYOUT FIXES (MUST IMPLEMENT):
    
    === SCREEN LAYOUT STRUCTURE ===
    Fix the layout to use these specific zones:
    - Title Zone: y > 2.5 (top area) - title.to_edge(UP, buff=0.5)
    - Left Text Zone: -6 < x < -1 (left side) - for narration text
    - Right Graphics Zone: 1 < x < 6 (right side) - for all visual elements
    - Buffer Zone: -1 < x < 1 (middle) - keep clear
    
    === POSITIONING FIXES ===
    1. TITLE fixes:
       - title.to_edge(UP, buff=0.5)  # Always at top
    
    2. TEXT positioning fixes:
       - Move ALL explanatory text to LEFT side
       - CRITICAL: Use font_size=16-18 or .scale(0.5) for ALL explanatory text
       - text.to_corner(UL, buff=0.8).shift(DOWN*0.5)
       - Stack multiple texts: text2.next_to(text1, DOWN, aligned_edge=LEFT, buff=0.3)
       - Keep text x-coordinates between -6 and -1
       - Text must be smaller and more compact
    
    3. GRAPHICS positioning fixes:
       - Move ALL visual elements (shapes, diagrams) to RIGHT side
       - graphics.move_to(RIGHT*3)  # Center in right zone
       - Keep graphics within: 1 < x < 6, -2.5 < y < 2.5
       - Scale down if needed: .scale(0.6) to .scale(0.8)
       - CRITICAL: Use .arrange(DOWN, buff=0.3) or .next_to() to prevent overlapping
       - CRITICAL: Use VGroup() to group related shapes and position them together
       - Ensure proper spacing between all graphic elements
    
    GEOMETRY SIZING FIXES (CRITICAL):
    - ALL coordinates MUST be ≤1.5 units for graphics in right zone
    - 4*RIGHT → 1*RIGHT, 5*UP → 1.2*UP, 6*DOWN → 1.2*DOWN
    - 3*RIGHT → 1*RIGHT, 4*UP → 1.2*UP, 8*UP → 1.5*UP
    - Use side_length ≤1.5: side_length=4 → side_length=1.2
    - Position graphics: graphics.move_to(RIGHT*3) then fine-tune
    - Always add .scale(0.7) to ensure graphics fit in right zone
    
    MANDATORY layout fixes:
    - Separate text and graphics into left/right zones
    - No overlapping between text and graphics
    - All text left-aligned in left zone
    - All graphics centered in right zone
    
    Return ONLY the corrected Python code, no additional text or explanations."""
    
    try:
        # Log the message count for debugging
        logger.info(f"Calling Claude API with {len(conversation_history)} messages")
        
        # Validate messages contain content
        for i, msg in enumerate(conversation_history):
            if not msg.get("content") or not msg.get("content").strip():
                logger.warning(f"Message {i} has empty content, skipping")
                conversation_history = [msg for msg in conversation_history if msg.get("content", "").strip()]
        
        # Final validation
        if not conversation_history:
            raise Exception("No valid messages found after validation")
        
        # Log full payload for the refine phase
        logger.info("🔄 Claude API call details - REFINE phase")
        logger.info("=" * 120)
        logger.info("📋 【System Prompt】")
        logger.info(system_prompt)
        logger.info("=" * 120)
        logger.info("💬 【Messages (Conversation History)】")
        for i, msg in enumerate(conversation_history):
            logger.info(f"Message {i+1} ({msg['role']}):")
            logger.info(msg['content'])
            if i < len(conversation_history) - 1:
                logger.info("-" * 60)
        logger.info("=" * 120)
        
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4000,
            system=system_prompt,
            messages=conversation_history
        )
        
        # Handle different response formats and extract Python code
        content = message.content[0]
        raw_response = extract_text_from_content(content)
        
        # Extract Python code from the response
        python_code = extract_python_code(raw_response)
        return python_code
        
    except anthropic.BadRequestError as e:
        logger.error(f"Bad request error: {str(e)}")
        logger.error(f"Conversation history: {conversation_history}")
        raise Exception(f"Failed to refine script with Claude (Bad Request): {str(e)}")
    except anthropic.APIError as e:
        if "overloaded" in str(e).lower() or "529" in str(e):
            logger.warning(f"Claude API overloaded: {str(e)}")
            raise Exception(f"Claude API temporarily overloaded: {str(e)}")
        else:
            logger.error(f"Claude API error: {str(e)}")
            raise Exception(f"Failed to refine script with Claude (API Error): {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in refine_manim_script: {str(e)}")
        raise Exception(f"Failed to refine script with Claude: {str(e)}")


async def fix_manim_script_from_error(
    client: anthropic.Anthropic,
    script: str,
    error_message: str,
    language: str = "en"
) -> str:
    """
    Fix a Manim script based on a specific error message.
    """
    # Language mapping
    language_names = {
        'en': 'English', 'es': 'Spanish', 'fr': 'French', 'de': 'German',
        'it': 'Italian', 'pt': 'Portuguese', 'ru': 'Russian', 'ja': 'Japanese',
        'ko': 'Korean', 'zh': 'Chinese', 'ar': 'Arabic', 'hi': 'Hindi'
    }
    language_name = language_names.get(language, 'English')
    
    system_prompt = f"""You are an expert Manim developer. Fix the provided script based on the error message.

    LANGUAGE REQUIREMENT: Keep ALL text content in {language_name} language when fixing the script.

    Common Manim issues to fix:
    - `get_angle()` doesn't exist on Polygon - calculate angle manually or remove
    - Use proper Manim methods and attributes
    - Ensure all imports are correct
    - Fix deprecated method calls
    - Handle positioning and rotation correctly
    - get_riemann_rectangles() unexpected keyword argument 'opacity': 
      NEVER pass opacity to get_riemann_rectangles(), use set_fill(opacity=value) after creation
    - CORRECT: rectangles = axes.get_riemann_rectangles(curve, x_range=[a,b], dx=step, color=GREEN)
              rectangles.set_fill(opacity=0.6)  # Set opacity separately
    - axes.c2p() unexpected keyword argument 'buff':
      NEVER pass buff or any keyword arguments to c2p(), only coordinates
      WRONG: axes.c2p(1, 0, buff=0.3)
      CORRECT: axes.c2p(1, 0)
    
    LaTeX/Text issues to fix:
    - LaTeX compilation errors: Use Text() for non-English characters instead of MathTex()
    - For Chinese/Japanese/Korean text: Text("[non-Latin text]") not MathTex("[non-Latin text]")
    - For mixed math and text: VGroup(MathTex("x = 1"), Text(" or "), MathTex("x = -3"))
    - MathTex() only supports basic Latin characters and math symbols
    - Escape special characters properly in LaTeX
    
    Manim Object errors to fix:
    - RightTriangle is not defined: Use Polygon(ORIGIN, 1*RIGHT, 1.2*UP)
    - NameError for shapes: Use correct Manim objects (Square, Circle, Rectangle, Line)
    - Missing imports: Make sure all Manim objects are available from "from manim import *"
    - Use .set_fill() and .set_stroke() for styling shapes
    - TypeError with get_vertices(): triangle.get_vertices()[2] returns a tuple, not numpy array
      Fix: Use np.array(triangle.get_vertices()[2]) or triangle.get_vertices()[2] + np.array([x, y, z])
    
    CRITICAL VIDEO LAYOUT FIXES (MUST IMPLEMENT):
    
    === LAYOUT ERROR FIXES ===
    1. TITLE positioning:
       - title.to_edge(UP, buff=0.5)  # Fixed at top
    
    2. TEXT positioning (LEFT zone):
       - Move ALL explanatory text to LEFT side: -6 < x < -1
       - CRITICAL: Use font_size=16-18 or .scale(0.5) for ALL explanatory text
       - text.to_corner(UL, buff=0.8).shift(DOWN*0.5)
       - Stack texts: text2.next_to(text1, DOWN, aligned_edge=LEFT, buff=0.3)
       - Make text compact and smaller
    
    3. GRAPHICS positioning (RIGHT zone):
       - Move ALL visual elements to RIGHT side: 1 < x < 6
       - graphics.move_to(RIGHT*3)  # Center in right zone
       - Keep graphics within bounds: -2.5 < y < 2.5
       - CRITICAL: Use VGroup().arrange(DOWN, buff=0.3) to prevent overlapping
       - CRITICAL: Use .next_to() with proper buff values for spacing
       - Ensure no graphic elements overlap or misalign
    
    Geometry Positioning errors to fix (CRITICAL):
    - Objects out of frame: IMMEDIATELY replace ALL coordinates >1.5 with ≤1.2
    - Large coordinates: 4*RIGHT → 1*RIGHT, 8*UP → 1.2*UP, 3*RIGHT → 1*RIGHT
    - Position graphics in RIGHT zone: graphics.move_to(RIGHT*3)
    - Large side_length: side_length=4 → side_length=1.2, side_length=6 → side_length=1.2
    - ALWAYS add .scale(0.7) to ensure graphics fit in right zone
    - Separate text (left) and graphics (right) to avoid overlap
    - Example fix: Polygon(ORIGIN, 4*RIGHT, 8*UP) → Polygon(ORIGIN, 1*RIGHT, 1.2*UP).move_to(RIGHT*3).scale(0.7)

    Return ONLY the fixed Python code, no explanations."""
    
    try:
        fix_message = f"Fix this Manim script:\n\n{script}\n\nError message:\n{error_message}"
        
        # Log full payload for the fix phase
        logger.info("🛠️ Claude API call details - FIX phase")
        logger.info("=" * 120)
        logger.info("📋 System prompt")
        logger.info(system_prompt)
        logger.info("=" * 120)
        logger.info("💬 Fix message")
        logger.info(fix_message)
        logger.info("=" * 120)
        
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4000,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": fix_message
                }
            ]
        )
        
        content = message.content[0]
        raw_response = extract_text_from_content(content)
        python_code = extract_python_code(raw_response)
        return python_code
        
    except Exception as e:
        raise Exception(f"Failed to fix script: {str(e)}")


def auto_fix_riemann_rectangles_opacity(script: str) -> str:
    """
    Automatically fix incorrect `opacity` arguments passed to get_riemann_rectangles.
    """
    import re
    
    # Look for every get_riemann_rectangles call that incorrectly passes opacity
    pattern = r'(.*?axes\.get_riemann_rectangles\([^)]*?),\s*opacity\s*=\s*([\d.]+)([^)]*?\))'
    
    def fix_opacity(match):
        # Extract the call fragments
        before_opacity = match.group(1)  # get_riemann_rectangles(curve, x_range=[...], 
        opacity_value = match.group(2)   # numeric opacity value
        after_opacity = match.group(3)   # )
        
        # Rebuild the call without the opacity argument
        fixed_call = before_opacity + after_opacity
        # Then set the fill opacity separately
        return f"{fixed_call}\n        rectangles.set_fill(opacity={opacity_value})"
    
    # Apply the fix across the script
    fixed_script = re.sub(pattern, fix_opacity, script, flags=re.MULTILINE | re.DOTALL)
    
    # If we changed any calls, align the rectangles variable naming
    if fixed_script != script:
        # Ensure `rectangles` matches the assigned variable name
        fixed_script = re.sub(
            r'(\w+)\s*=\s*(axes\.get_riemann_rectangles\([^)]+\))\n\s+rectangles\.set_fill',
            r'\1 = \2\n        \1.set_fill',
            fixed_script
        )
    
    return fixed_script


def auto_fix_large_coordinates(script: str) -> str:
    """
    Automatically fix large coordinates and layout issues in Manim scripts.
    """
    import re
    
    # First, fix get_riemann_rectangles opacity parameter error
    script = auto_fix_riemann_rectangles_opacity(script)
    
    # Fix c2p() method with unexpected keyword arguments
    # Pattern: axes.c2p(x, y, buff=value) -> axes.c2p(x, y)
    # This fixes the common error: TypeError: CoordinateSystem.c2p() got an unexpected keyword argument 'buff'
    script = re.sub(
        r'(\.c2p\([^,)]+,\s*[^,)]+),\s*buff\s*=\s*[\d.]+\)',
        r'\1)',
        script
    )
    
    # Also fix any other keyword arguments passed to c2p()
    script = re.sub(
        r'(\.c2p\([^)]+)),\s*\w+\s*=\s*[^)]+\)',
        r'\1)',
        script
    )
    
    # Fix TypeError with get_vertices() - convert tuple multiplication to numpy array
    script = re.sub(
        r'(\.get_vertices\(\)\[\d+\])\s*\+\s*([\d.]+)\s*\*\s*\(([^)]+)\)',
        r'\1 + \2 * np.array([\3])',
        script
    )
    
    # Replace large coordinates with smaller ones suitable for right zone
    coordinate_fixes = {
        r'(\d+)\*RIGHT': lambda m: f"{min(1, int(m.group(1)))}*RIGHT" if int(m.group(1)) > 1.5 else m.group(0),
        r'(\d+)\*UP': lambda m: f"{min(1.2, int(m.group(1)))}*UP" if int(m.group(1)) > 1.5 else m.group(0),
        r'(\d+)\*DOWN': lambda m: f"{min(1.2, int(m.group(1)))}*DOWN" if int(m.group(1)) > 1.5 else m.group(0),
        r'(\d+)\*LEFT': lambda m: f"{min(1, int(m.group(1)))}*LEFT" if int(m.group(1)) > 1.5 else m.group(0),
        r'side_length\s*=\s*(\d+(?:\.\d+)?)': lambda m: f"side_length={min(1.2, float(m.group(1)))}" if float(m.group(1)) > 1.5 else m.group(0)
    }
    
    fixed_script = script
    for pattern, replacement in coordinate_fixes.items():
        fixed_script = re.sub(pattern, replacement, fixed_script)
    
    # Fix layout positioning - move graphics to right zone
    if ('Polygon(' in fixed_script or 'Square(' in fixed_script or 'Circle(' in fixed_script):
        # Add move_to(RIGHT*3) to geometry objects for right zone positioning
        if '.move_to(RIGHT*3)' not in fixed_script:
            # Find geometry objects and add right zone positioning
            geometry_patterns = [
                r'((?:Polygon|Square|Rectangle|Circle)\([^)]+\))',
                r'(VGroup\([^)]+\))'  # For grouped geometry
            ]
            
            for pattern in geometry_patterns:
                if re.search(pattern, fixed_script):
                    fixed_script = re.sub(
                        pattern,
                        r'\1.move_to(RIGHT*3).scale(0.7)',
                        fixed_script,
                        count=1
                    )
                    break
    
    # Add basic layout structure if missing
    if 'title.to_edge(UP' not in fixed_script and 'Text(' in fixed_script:
        # Try to identify title and fix its positioning
        fixed_script = re.sub(
            r'(title\s*=\s*Text\([^)]+\))',
            r'\1\n        title.to_edge(UP, buff=0.5)',
            fixed_script
        )
    
    # Fix text positioning to left zone if not already positioned
    if 'to_corner(UL' not in fixed_script and 'Text(' in fixed_script and 'title' not in fixed_script.lower():
        # Add left zone positioning for explanatory text with smaller font
        fixed_script = re.sub(
            r'(\w+\s*=\s*Text\()([^)]+)(\))(?!\s*\.\s*to_edge)',
            r'\1\2, font_size=20\3.to_corner(UL, buff=0.8).shift(DOWN*0.5)',
            fixed_script,
            count=1
        )
    
    # Fix font sizes for existing text objects
    if 'font_size=' not in fixed_script and 'Text(' in fixed_script:
        # Add font_size to Text objects that don't have it
        fixed_script = re.sub(
            r'Text\(([^)]+)\)(?!.*font_size)',
            r'Text(\1, font_size=18)',
            fixed_script
        )
    
    # Fix graphics overlapping issues
    if ('Polygon(' in fixed_script or 'Square(' in fixed_script or 'Circle(' in fixed_script):
        # Add arrange() method if VGroup exists but no arrange
        if 'VGroup(' in fixed_script and '.arrange(' not in fixed_script:
            fixed_script = re.sub(
                r'(VGroup\([^)]+\))(\s*\.move_to\(RIGHT\*3\))',
                r'\1.arrange(DOWN, buff=0.3)\2',
                fixed_script
            )
    
    return fixed_script


async def test_manim_script(script: str) -> Dict[str, Any]:
    """
    Test a Manim script by attempting to import and validate it.
    """
    try:
        # Create a temporary file for testing
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script)
            temp_script_path = f.name
        
        # Test 1: Syntax check
        try:
            compile(script, '<string>', 'exec')
        except SyntaxError as e:
            return {
                "success": False,
                "error": f"Syntax error: {str(e)}"
            }
        
        # Test 2: Import check (basic)
        try:
            # Create a temporary module to test imports
            import sys
            import importlib.util
            
            spec = importlib.util.spec_from_file_location("temp_module", temp_script_path)
            if spec is None:
                return {
                    "success": False,
                    "error": "Failed to create module spec"
                }
            
            module = importlib.util.module_from_spec(spec)
            
            # Try to import the module (this will catch import errors)
            if spec.loader is None:
                return {
                    "success": False,
                    "error": "Module loader is None"
                }
            
            spec.loader.exec_module(module)
            
            # Check if it has a Scene class
            scene_classes = [cls for cls in module.__dict__.values() 
                           if isinstance(cls, type) and hasattr(cls, 'construct')]
            
            if not scene_classes:
                return {
                    "success": False,
                    "error": "No Scene class with construct method found"
                }
            
            # Check for layout and positioning issues
            script_content = script.lower()
            potential_issues = []
            
            # Check for large coordinates (stricter limits for new layout)
            import re
            large_coords = re.findall(r'(\d+(?:\.\d+)?)\s*\*\s*(?:right|up|down|left)', script_content)
            large_side_lengths = re.findall(r'side_length\s*=\s*(\d+(?:\.\d+)?)', script_content)
            
            for coord in large_coords:
                if float(coord) > 1.5:
                    potential_issues.append(f"Large coordinate found: {coord} (must be ≤1.2 for right zone)")
            
            for side_length in large_side_lengths:
                if float(side_length) > 1.5:
                    potential_issues.append(f"Large side_length found: {side_length} (must be ≤1.2)")
            
            # Check for proper layout structure
            has_title = 'title.to_edge(up' in script_content
            has_left_text = 'to_corner(ul' in script_content or 'left' in script_content
            has_right_graphics = 'move_to(right*3)' in script_content or 'right*3' in script_content
            has_geometry = any(geom in script_content for geom in ['polygon', 'square', 'rectangle', 'circle'])
            
            if not has_title and 'title' in script_content:
                potential_issues.append("Title not positioned at top (must use title.to_edge(UP, buff=0.5))")
            
            if has_geometry and not has_right_graphics:
                potential_issues.append("Graphics not positioned in right zone (must use .move_to(RIGHT*3))")
            
            if 'text' in script_content and not has_left_text and 'title' not in script_content:
                potential_issues.append("Text not positioned in left zone (must use .to_corner(UL, buff=0.8))")
            
            # Check for overlapping elements (basic check)
            if has_geometry and 'move_to(origin)' in script_content:
                potential_issues.append("Graphics positioned at center - must move to right zone")
            
            if potential_issues:
                return {
                    "success": False,
                    "error": f"Layout issues: {'; '.join(potential_issues)}. CRITICAL: Use proper layout zones - title at top, text in left zone (-6<x<-1), graphics in right zone (1<x<6)."
                }
            
            return {"success": True, "error": None}
            
        except ImportError as e:
            return {
                "success": False,
                "error": f"Import error: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Validation error: {str(e)}"
            }
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_script_path)
            except:
                pass
                
    except Exception as e:
        return {
            "success": False,
            "error": f"Test error: {str(e)}"
        }


def classify_manim_error(error_message: str) -> str:
    """Classify Manim errors for better refinement."""
    error_lower = error_message.lower()
    
    if "latex error" in error_lower or "tex" in error_lower or "compilation" in error_lower:
        return "latex_error"
    elif "righttriangle" in error_lower or "name" in error_lower and ("not defined" in error_lower or "is not defined" in error_lower):
        return "manim_object_error"
    elif "import" in error_lower or "module" in error_lower:
        return "import_error"
    elif "syntax" in error_lower:
        return "syntax_error"
    elif "attribute" in error_lower:
        return "attribute_error"
    elif "name" in error_lower:
        return "name_error"
    else:
        return "general_error"


async def detect_language(client: anthropic.Anthropic, prompt: str) -> str:
    """
    Detect the language of the user's prompt using Claude.
    """
    system_prompt = """Detect the language of the user's prompt and return the appropriate language code.

    Return one of these language codes based on the input:
    - en (English)
    - es (Spanish) 
    - fr (French)
    - de (German)
    - it (Italian)
    - pt (Portuguese)
    - ru (Russian)
    - ja (Japanese)
    - ko (Korean)
    - zh (Chinese)
    - ar (Arabic)
    - hi (Hindi)
    
    Return ONLY the language code, nothing else."""
    
    try:
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=50,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": f"Detect language: {prompt}"
                }
            ]
        )
        
        content = message.content[0]
        language_code = extract_text_from_content(content).strip().lower()
        return language_code if language_code in ['en', 'es', 'fr', 'de', 'it', 'pt', 'ru', 'ja', 'ko', 'zh', 'ar', 'hi'] else 'en'
        
    except Exception as e:
        logger.warning(f"Language detection failed: {str(e)}, defaulting to English")
        return 'en'


async def estimate_narration_duration(client: anthropic.Anthropic, prompt: str) -> float:
    """
    Estimate how long the narration will be based on the prompt complexity.
    """
    try:
        system_prompt = """Estimate the duration of educational narration for the given prompt.

        Consider:
        - Topic complexity (simple: 30-45s, moderate: 45-60s, complex: 60-90s)
        - Amount of explanation needed
        - Step-by-step breakdown requirements
        - Mathematical concepts (need more time)
        
        Return ONLY a number representing seconds (e.g., 45 or 60)."""
        
        messages = [
            {
                "role": "user",
                "content": f"Estimate narration duration for: {prompt}"
            }
        ]
        
        logger.info(f"Estimating duration for prompt: {prompt[:50]}...")
        
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=50,
            system=system_prompt,
            messages=messages
        )
        
        content = message.content[0]
        duration_text = extract_text_from_content(content).strip()
        
        try:
            estimated_duration = float(duration_text)
            # Clamp to reasonable range
            return max(30.0, min(90.0, estimated_duration))
        except ValueError:
            logger.warning(f"Could not parse duration from Claude response: {duration_text}")
            # Fallback based on prompt length
            word_count = len(prompt.split())
            return min(45.0 + word_count * 2, 75.0)
        
    except anthropic.APIError as e:
        if "overloaded" in str(e).lower() or "529" in str(e):
            logger.warning(f"Duration estimation failed due to API overload: {str(e)}")
        else:
            logger.warning(f"Duration estimation failed due to API error: {str(e)}")
        # Fallback based on prompt length
        word_count = len(prompt.split())
        return min(45.0 + word_count * 2, 75.0)
    except Exception as e:
        logger.warning(f"Duration estimation failed: {str(e)}")
        # Fallback based on prompt length
        word_count = len(prompt.split())
        return min(45.0 + word_count * 2, 75.0)


def detect_mathematical_content(text: str) -> Dict[str, Any]:
    """
    Detect math-related patterns in text, even when OCR output is noisy.
    
    Args:
        text: OCR-extracted text
        
    Returns:
        Structured info about detected mathematical elements
    """
    math_patterns = {
        'integral': [r'∫', r'\[.*?x', r'J.*?x', r'integral', r'\u79ef\u5206'],
        'derivative': [r'∂', r'derivative', r'\u5bfc\u6570', r'd/dx'],
        'equation': [r'=', r'solve', r'\u89e3', r'\u65b9\u7a0b'],
        'function': [r'f\(', r'g\(', r'\u51fd\u6570', r'function'],
        'exponent': [r'\^', r'power', r'\u5e42', r'\u6307\u6570'],
        'polynomial': [r'x\^', r'polynomial', r'\u591a\u9879\u5f0f']
    }
    
    detected_types = []
    confidence_score = 0
    
    for math_type, patterns in math_patterns.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                detected_types.append(math_type)
                confidence_score += 1
                break
    
    # Handle common OCR mistakes for integral symbols
    if any(pattern in text.lower() for pattern in ['[ve', '] x', 'j x', '∫']):
        detected_types.append('integral')
        confidence_score += 2
    
    # Detect standalone variable hints (x, y, z, n, t)
    if re.search(r'\b[xyznt]\b', text):
        confidence_score += 1
        
    # Detect dx/dy style differential notation
    if re.search(r'd[xyz]', text):
        detected_types.append('differential')
        confidence_score += 1
    
    return {
        'detected_types': detected_types,
        'confidence_score': confidence_score,
        'is_mathematical': confidence_score > 0
    }


async def analyze_uploaded_content(
    client: anthropic.Anthropic,
    file_context: str,
    user_prompt: str,
    language: str = 'en'
) -> Optional[Dict[str, Any]]:
    """
    Analyze uploaded material and extract structured metadata.
    
    Args:
        client: Anthropic client
        file_context: Text content from uploaded files
        user_prompt: Original user request
        language: Language code for the material
        
    Returns:
        Dict containing content type, concepts, formulas, etc.
    """
    language_names = {
        'en': 'English', 'es': 'Spanish', 'fr': 'French', 'de': 'German',
        'it': 'Italian', 'pt': 'Portuguese', 'ru': 'Russian', 'ja': 'Japanese',
        'ko': 'Korean', 'zh': 'Chinese', 'ar': 'Arabic', 'hi': 'Hindi'
    }
    language_name = language_names.get(language, 'English')
    
    system_prompt = f"""Analyze the uploaded content and extract key information for video animation generation.

Your task is to understand the uploaded material and identify:
1. content_type: Type of material (textbook/slides/data/article/research/manual/etc.)
2. key_concepts: List of main concepts, topics, or subjects (max 5 items)
3. formulas: Mathematical formulas, equations, or scientific notations found
4. data_points: Important data, statistics, or numerical information
5. visual_elements: Descriptions of any charts, diagrams, or visual content mentioned
6. structure: The logical organization of the content (chapters/sections/steps)
7. educational_focus: What should be the main teaching points
8. animation_suggestions: Specific suggestions for what to visualize

Respond in {language_name} when analyzing content in that language.

Return ONLY valid JSON format with these fields. If any field doesn't apply, use empty array [] or null.

Example:
{{
    "content_type": "mathematical textbook",
    "key_concepts": ["quadratic equations", "factoring", "graphing"],
    "formulas": ["ax² + bx + c = 0", "x = (-b ± √(b²-4ac)) / 2a"],
    "data_points": [],
    "visual_elements": ["parabola graphs", "coefficient examples"],
    "structure": ["introduction", "solving methods", "examples", "practice"],
    "educational_focus": "step-by-step solving process",
    "animation_suggestions": ["show parabola transformation", "demonstrate factoring steps"]
}}"""
    
    # Run math-content heuristics first
    math_detection = detect_mathematical_content(file_context)
    logger.info("=" * 80)
    logger.info("🔍 Math detection results")
    logger.info(f"   📊 Raw detection: {math_detection}")
    logger.info(f"   🎯 Contains math content: {'yes' if math_detection['is_mathematical'] else 'no'}")
    logger.info(f"   📋 Detected types: {', '.join(math_detection['detected_types'])}")
    logger.info(f"   💯 Confidence score: {math_detection['confidence_score']}")
    logger.info("=" * 80)
    
    # If OCR output is tiny but math is detected, add context hints
    enhanced_context = file_context
    if math_detection['is_mathematical'] and len(file_context.strip()) < 20:
        if 'integral' in math_detection['detected_types']:
            enhanced_context += "\n\n[AI detected integral notation; likely ∫x^n dx style problem]"
            logger.info("🔧 Context boost: added integral hint")
        if 'exponent' in math_detection['detected_types']:
            enhanced_context += "\n\n[AI detected exponential expression]"
            logger.info("🔧 Context boost: added exponential hint")
    
    try:
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2000,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": f"User request: {user_prompt}\n\nUploaded content to analyze:\n{enhanced_context[:8000]}"  # Limit content length
                }
            ]
        )
        
        content = message.content[0]
        analysis_text = extract_text_from_content(content)
        
        import json
        try:
            analysis_result = json.loads(analysis_text)
            logger.info(f"✅ Content analysis complete: type={analysis_result.get('content_type', 'unknown')}, key concepts={len(analysis_result.get('key_concepts', []))}")
            return analysis_result
            
        except json.JSONDecodeError as e:
            logger.warning(f"Content analysis JSON parse failed: {str(e)}; returning fallback data")
            return {
                "content_type": "text_content",
                "key_concepts": ["uploaded content"],
                "formulas": [],
                "data_points": [],
                "visual_elements": [],
                "structure": ["uploaded material"],
                "educational_focus": "explain uploaded content",
                "animation_suggestions": ["visualize key points"]
            }
        
    except Exception as e:
        logger.warning(f"Content analysis failed: {str(e)}; returning None")
        return None


def verify_content_coverage(script: str, file_context: str, key_concepts: List[str]) -> float:
    """
    Verify whether the generated script reflects key concepts from the uploads.
    
    Args:
        script: Generated Manim script
        file_context: Raw uploaded content
        key_concepts: List of extracted key concepts
        
    Returns:
        Coverage ratio between 0 and 1
    """
    if not file_context or not key_concepts:
        return 1.0  # nothing to validate against
    
    script_lower = script.lower()
    covered_concepts = 0
    
    for concept in key_concepts:
        # Simple substring check (case-insensitive)
        if concept.lower() in script_lower:
            covered_concepts += 1
    
    coverage = covered_concepts / len(key_concepts) if key_concepts else 1.0
    
    if coverage < 0.5:
        logger.warning(f"⚠️ Coverage is low: {coverage:.2f}; consider regenerating")
    else:
        logger.info(f"✅ Content coverage: {coverage:.2f}")
    
    return coverage
