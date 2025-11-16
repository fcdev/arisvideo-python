#!/usr/bin/env python3
"""
ArisVideo Test Runner

Simple CLI for running tests. Designed to be easy for AI agents to use.

Usage:
    python run_tests.py                    # Run unit tests (fast, mocked)
    python run_tests.py --integration      # Run integration tests (slow, real APIs)
    python run_tests.py --coverage         # Run with coverage report
    python run_tests.py test_generate      # Run specific test file/pattern
    python run_tests.py --help             # Show help

Examples:
    # Quick unit tests (recommended for development)
    python run_tests.py

    # Full integration test with real APIs
    INTEGRATION_TESTS=true python run_tests.py --integration

    # Generate coverage report
    python run_tests.py --coverage

    # Run only database tests
    python run_tests.py -m database

    # Run specific test file
    python run_tests.py tests/test_generate_endpoint.py
"""

import sys
import os
import subprocess
import argparse


def run_pytest(args: list[str]) -> int:
    """
    Run pytest with the given arguments.

    Args:
        args: List of pytest arguments

    Returns:
        Exit code from pytest
    """
    cmd = ["uv", "run", "pytest"] + args
    print(f"Running: {' '.join(cmd)}")
    print("=" * 80)
    return subprocess.call(cmd)


def main():
    parser = argparse.ArgumentParser(
        description="ArisVideo Test Runner - Easy test execution for AI agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "test_path",
        nargs="?",
        default=None,
        help="Specific test file or pattern to run (optional)"
    )

    parser.add_argument(
        "--integration",
        action="store_true",
        help="Run integration tests with real APIs (requires API keys)"
    )

    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Generate coverage report"
    )

    parser.add_argument(
        "-m", "--marker",
        type=str,
        help="Run tests with specific marker (unit, integration, database, slow)"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )

    parser.add_argument(
        "--failfast",
        action="store_true",
        help="Stop on first failure"
    )

    args = parser.parse_args()

    # Build pytest arguments
    pytest_args = []

    # Verbose mode
    if args.verbose:
        pytest_args.append("-vv")

    # Fail fast
    if args.failfast:
        pytest_args.append("-x")

    # Coverage
    if args.coverage:
        pytest_args.extend([
            "--cov=.",
            "--cov-report=term-missing",
            "--cov-report=html"
        ])

    # Integration mode
    if args.integration:
        os.environ["INTEGRATION_TESTS"] = "true"
        pytest_args.extend(["-m", "integration"])
        print("🚀 Running INTEGRATION tests with real APIs")
        print("⚠️  This will make real API calls and may cost money!")
        print("=" * 80)
    else:
        # Default to unit tests
        pytest_args.extend(["-m", "unit or (not integration)"])
        print("🧪 Running UNIT tests with mocked dependencies (fast)")
        print("=" * 80)

    # Custom marker
    if args.marker:
        pytest_args.extend(["-m", args.marker])

    # Specific test path
    if args.test_path:
        pytest_args.append(args.test_path)

    # Run pytest
    exit_code = run_pytest(pytest_args)

    # Summary
    print("=" * 80)
    if exit_code == 0:
        print("✅ All tests passed!")
        if args.coverage:
            print("📊 Coverage report generated: htmlcov/index.html")
    else:
        print("❌ Some tests failed")
        print("💡 Tip: Run with --verbose for more details")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
