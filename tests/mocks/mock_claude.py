"""
Mock Anthropic Claude AI client for testing.

This module provides mock responses for Claude AI script generation
without making actual API calls.
"""

SAMPLE_MANIM_SCRIPT = """from manim import *

class PythagoreanTheorem(Scene):
    def construct(self):
        # Title
        title = Text("Pythagorean Theorem", font_size=48)
        self.play(Write(title))
        self.wait(1)
        self.play(FadeOut(title))

        # Create a right triangle
        triangle = Polygon(
            [-2, -1, 0],
            [2, -1, 0],
            [-2, 2, 0],
            color=BLUE
        )

        # Labels for sides
        a_label = MathTex("a", color=YELLOW).next_to(triangle, LEFT)
        b_label = MathTex("b", color=YELLOW).next_to(triangle, DOWN)
        c_label = MathTex("c", color=YELLOW).next_to(triangle, UR)

        # Show triangle and labels
        self.play(Create(triangle))
        self.play(
            Write(a_label),
            Write(b_label),
            Write(c_label)
        )
        self.wait(1)

        # Show the formula
        formula = MathTex("a^2 + b^2 = c^2", font_size=60)
        formula.to_edge(UP)
        self.play(Write(formula))
        self.wait(2)

        # Fade out
        self.play(
            FadeOut(triangle),
            FadeOut(a_label),
            FadeOut(b_label),
            FadeOut(c_label),
            FadeOut(formula)
        )
"""

SAMPLE_SCRIPT_WITH_ERROR = """from manim import *

class BrokenScene(Scene):
    def construct(self):
        # This will cause a NameError
        text = UndefinedObject("This will fail")
        self.play(Write(text))
"""

REFINED_SCRIPT = """from manim import *

class FixedScene(Scene):
    def construct(self):
        # Fixed version
        text = Text("This works!")
        self.play(Write(text))
        self.wait(1)
"""


def get_mock_manim_script(prompt: str, iteration: int = 0) -> str:
    """
    Get a mock Manim script based on the prompt.

    Args:
        prompt: The user's prompt
        iteration: Refinement iteration (0 = first attempt, 1+ = refined)

    Returns:
        A valid Manim script as a string
    """
    if iteration == 0:
        # First attempt - return sample script
        return SAMPLE_MANIM_SCRIPT
    else:
        # Refinement - return improved script
        return REFINED_SCRIPT


def get_mock_error_script() -> str:
    """Get a script that will intentionally fail (for testing error handling)."""
    return SAMPLE_SCRIPT_WITH_ERROR


def create_mock_claude_response(script: str):
    """
    Create a mock Claude API response.

    Args:
        script: The Manim script to return

    Returns:
        Mock response object matching Claude API format
    """
    class MockContent:
        def __init__(self, text):
            self.text = text
            self.type = "text"

    class MockMessage:
        def __init__(self, script):
            self.content = [MockContent(script)]
            self.role = "assistant"
            self.model = "claude-sonnet-4-20250514"
            self.stop_reason = "end_turn"

    return MockMessage(script)
