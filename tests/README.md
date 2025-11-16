# ArisVideo Python Testing Guide

This directory contains the test suite for the ArisVideo Python service. The tests are designed to be easy for both humans and AI agents to run and understand.

## Quick Start

```bash
# Run all unit tests (fast, mocked - recommended)
python run_tests.py

# Run integration tests with real APIs (slow, costs money)
INTEGRATION_TESTS=true python run_tests.py --integration

# Run with coverage report
python run_tests.py --coverage

# Run specific test file
python run_tests.py tests/test_generate_endpoint.py
```

## Test Types

### Unit Tests (Default)
- **Fast**: Run in seconds
- **No API calls**: All external dependencies are mocked
- **No cost**: Doesn't use Claude or OpenAI APIs
- **Recommended**: For development and CI/CD

```bash
python run_tests.py
```

### Integration Tests
- **Slow**: Take 30-120 seconds
- **Real API calls**: Uses actual Claude and OpenAI services
- **Costs money**: Each run uses API credits
- **Required**: Valid `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`

```bash
# Set environment variable and run
INTEGRATION_TESTS=true python run_tests.py --integration

# Or export first
export INTEGRATION_TESTS=true
python run_tests.py --integration
```

## Test Structure

```
tests/
├── __init__.py
├── conftest.py                 # Pytest fixtures and configuration
├── test_generate_endpoint.py   # Tests for /generate endpoint
├── test_database.py            # Database operations tests
├── test_video_generation.py    # Full generation flow tests
└── mocks/
    ├── __init__.py
    ├── mock_claude.py          # Mock Claude AI responses
    ├── mock_openai.py          # Mock OpenAI TTS
    └── mock_manim.py           # Mock Manim execution
```

## Test Files

### `test_generate_endpoint.py`
Tests the `/generate` endpoint:
- ✅ Request validation
- ✅ API key authentication
- ✅ Parameter validation
- ✅ Database record creation
- ✅ Unique video ID generation

### `test_database.py`
Tests database operations:
- ✅ Database connection
- ✅ Video record CRUD
- ✅ VideoStatus creation
- ✅ Status updates
- ✅ Unique constraints

### `test_video_generation.py`
Tests full video generation flow:
- ✅ Unit mode: Mocked end-to-end test
- ✅ Integration mode: Real API end-to-end test
- ✅ Different languages
- ✅ Different resolutions
- ✅ With/without audio

## Running Specific Tests

```bash
# Run only database tests
python run_tests.py -m database

# Run only endpoint tests
python run_tests.py tests/test_generate_endpoint.py

# Run only unit tests
python run_tests.py -m unit

# Run specific test function
python run_tests.py tests/test_generate_endpoint.py::test_generate_with_valid_prompt

# Verbose output
python run_tests.py -v

# Stop on first failure
python run_tests.py --failfast
```

## Prerequisites

### For Unit Tests
- Python 3.13+
- Dependencies installed: `uv sync`
- Database running (for database tests)

### For Integration Tests
All of the above, plus:
- Valid `ANTHROPIC_API_KEY` in `.env`
- Valid `OPENAI_API_KEY` in `.env`
- FFmpeg installed
- LaTeX installed (for mathematical formulas)
- Manim working

## Environment Setup

1. **Install dependencies**:
   ```bash
   cd arisvideo-python
   uv sync
   ```

2. **Set up environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env and add your API keys
   ```

3. **Start database** (if not running):
   ```bash
   # Make sure PostgreSQL is running and DATABASE_URL is correct
   ```

## Coverage Reports

Generate HTML coverage report:

```bash
python run_tests.py --coverage
```

View the report:
```bash
open htmlcov/index.html
```

## Continuous Integration

For CI/CD pipelines, use unit tests only:

```bash
# Fast, no external dependencies, no cost
python run_tests.py --coverage --failfast
```

Integration tests should run on a schedule (e.g., nightly) or manually:

```bash
# Only run when needed, costs money
INTEGRATION_TESTS=true python run_tests.py --integration
```

## Troubleshooting

### Database Connection Errors
```bash
# Make sure DATABASE_URL is set correctly
echo $DATABASE_URL

# Check database is running
psql $DATABASE_URL -c "SELECT 1;"
```

### Import Errors
```bash
# Make sure you're in the arisvideo-python directory
cd /path/to/arisvideo/arisvideo-python

# Install dependencies
uv sync
```

### Integration Test Failures
- Check API keys are valid
- Check you have API credits
- Check internet connection
- FFmpeg and LaTeX must be installed

## For AI Agents

### Testing After Code Changes

After modifying the Python service code, run:

```bash
cd arisvideo-python
python run_tests.py
```

This will verify:
1. ✅ The `/generate` endpoint still works
2. ✅ Database operations work correctly
3. ✅ All core functionality is intact

### Full Validation

To verify the service works end-to-end with real APIs:

```bash
cd arisvideo-python
INTEGRATION_TESTS=true python run_tests.py --integration
```

⚠️ **Warning**: This makes real API calls and costs money. Only use when necessary.

### Interpreting Results

**All tests passed** (exit code 0):
```
✅ All tests passed!
```
→ Code changes are safe, no regressions

**Some tests failed** (exit code 1):
```
❌ Some tests failed
```
→ Code changes broke something, review failures

**Import/setup errors**:
→ Check dependencies with `uv sync`

## Writing New Tests

1. Add test file in `tests/` directory
2. Import fixtures from `conftest.py`
3. Use `@pytest.mark.asyncio` for async tests
4. Use `@pytest.mark.unit` for unit tests
5. Use `@pytest.mark.integration` for integration tests

Example:
```python
import pytest

@pytest.mark.asyncio
@pytest.mark.unit
async def test_my_feature(client, api_key, test_db):
    response = await client.post(
        "/generate",
        json={"prompt": "test"},
        headers={"X-API-Key": api_key}
    )
    assert response.status_code == 200
```

## Test Markers

- `@pytest.mark.unit`: Fast tests with mocks
- `@pytest.mark.integration`: Slow tests with real APIs
- `@pytest.mark.slow`: Tests that take time
- `@pytest.mark.database`: Tests requiring database

## Useful Commands

```bash
# List all available tests
pytest --collect-only

# Run tests matching a pattern
pytest -k "generate"

# Show print statements
pytest -s

# Run last failed tests
pytest --lf

# Run tests in parallel (faster)
pytest -n auto
```

## Best Practices

1. ✅ Always run unit tests before committing
2. ✅ Run integration tests before releases
3. ✅ Keep unit tests fast (<5 seconds total)
4. ✅ Mock external dependencies in unit tests
5. ✅ Use descriptive test names
6. ✅ One assertion per test (when possible)
7. ✅ Clean up test data in fixtures

## Support

For issues or questions:
- Check test output for error messages
- Review this README
- Check pytest documentation: https://docs.pytest.org/
