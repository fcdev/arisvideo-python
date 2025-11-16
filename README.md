# ArisVideo Python Service

FastAPI microservice that powers ArisVideo’s Claude → Manim → FFmpeg generation pipeline. The mono-repo also contains the Next.js dashboard (`arisvideo-web`), so this README highlights how the backend fits into the broader product.

## Monorepo Overview

```
arisvideo/
├── arisvideo-python   # FastAPI service (this README)
├── arisvideo-web      # Next.js dashboard + API routes
├── AGENTS.md          # Ground rules for contributors
├── CLAUDE.md          # Architecture deep dive
└── MIGRATION_GUIDE.md # Rollout procedures
```

Build both apps locally when developing features that touch API + UI. The Next.js client forwards all calls through its `/api/*` route handlers, which in turn talk to this service via `PYTHON_SERVICE_URL` and sign requests with `PYTHON_API_KEY`.

## 🚀 Features

- 🎬 Generate educational animations from text prompts
- 🤖 Powered by Claude AI for intelligent script generation
- 🧮 Built with Manim for high-quality mathematical animations
- 🚀 FastAPI-based REST API
- 🎥 Multiple resolution support (480p to 1080p)
- 🔊 AI-generated narration with multiple voices and languages
- 🎯 Audio-video synchronization with timing analysis
- 🌍 **Smart language detection & voice matching**: Automatically detects the input language and picks an appropriate TTS voice
- 🗣️ **Multilingual TTS support**: 12 languages covered, each mapped to a curated voice profile
- 📱 Direct video URL access for easy embedding

## 📋 Prerequisites

- **Python 3.13+**
- **FFmpeg** (required for audio/video processing)
- **LaTeX distribution** (for mathematical formulas)
- **Anthropic API Key** (for Claude AI)
- **OpenAI API Key** (optional, for narration)

## 🛠️ Installation

### 1. Clone the repository
```bash
git clone <repository-url>
cd manimations
```

### 2. Install uv (Python package manager)
```bash
# Install uv (recommended by Manim)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
```

### 3. Install dependencies
```bash
uv sync
```

### 4. Install system dependencies

**macOS:**
```bash
brew install ffmpeg
brew install --cask mactex
```

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install ffmpeg texlive-full
```

**Windows:**
- Download FFmpeg from https://ffmpeg.org/download.html
- Install MiKTeX from https://miktex.org/

### 5. Set environment variables

Create a `.env` file from the template:
```bash
cp .env.example .env
# Edit .env with your API keys
```

Key variables:

| Name | Purpose |
| ---- | ------- |
| `PYTHON_API_KEY` | Shared secret with `arisvideo-web` (routed as `X-API-Key`) |
| `ANTHROPIC_API_KEY` | Required for Claude script + narration planning |
| `OPENAI_API_KEY` | Optional, enables TTS voices |
| `VIDEO_STORAGE_PATH` | Output directory for rendered mp4 files (defaults to `./media/videos`) |

Set them manually if you prefer:
```bash
export PYTHON_API_KEY="match-your-nextjs-env"
export ANTHROPIC_API_KEY="your-anthropic-api-key"
export OPENAI_API_KEY="your-openai-api-key"  # Optional, for narration
export VIDEO_STORAGE_PATH="$(pwd)/media/videos"
```

## 🚀 Running the API

### Start the server
```bash
# Development mode (with auto-reload)
uv run uvicorn app:app --host 0.0.0.0 --port 8000 --reload

# Production mode (multiple workers)
uv run uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
```

The API will be available at `http://localhost:8000`

Visit `http://localhost:8000/docs` for interactive API documentation.

### Working with the Next.js Frontend

1. Start this service (`uv run uvicorn app:app --reload`).
2. Start `arisvideo-web` (`npm run dev`) with `.env.local` that references the same `PYTHON_SERVICE_URL` and `PYTHON_API_KEY`.
3. Use the dashboard to log in, upload docs, and kick off `/api/videos/generate` – the Next.js route handlers will attach the shared key automatically.

### Smoke Tests

- `curl -H "X-API-Key: $PYTHON_API_KEY" http://localhost:8000/health`
- `curl -X POST http://localhost:8000/generate -H "X-API-Key: $PYTHON_API_KEY" -d '{...}'`

The generation request should log each pipeline step (Claude → Manim → FFmpeg) in the terminal.

## 📚 API Endpoints

### `GET /` - Root Information
Returns basic API information and available endpoints.

**Response:**
```json
{
  "message": "Manimations API - Educational Animation Generator",
  "endpoints": {
    "generate": "/generate - POST request with prompt",
    "health": "/health - Check API health"
  }
}
```

### `GET /health` - Health Check
Simple health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "service": "manimations-api"
}
```

### `POST /generate` - Generate Animation
Generate an educational animation video from a text prompt.

**Request Body:**
```json
{
  "prompt": "Explain the Pythagorean theorem with a visual proof",
  "resolution": "m",
  "include_audio": true,
  "voice": "alloy",
  "language": "en",
  "sync_method": "timing_analysis"
}
```

**Parameters:**
- `prompt` (string, required): Natural language description of the animation
- `resolution` (string, optional): Video quality
  - `"l"` - Low quality (480p)
  - `"m"` - Medium quality (720p, default)
  - `"h"` - High quality (1080p)
  - `"p"` - Production quality
  - `"k"` - 4K quality
- `include_audio` (boolean, optional): Whether to generate narration (default: true)
- `voice` (string, optional): TTS voice for narration
  - `"alloy"` (default), `"echo"`, `"fable"`, `"onyx"`, `"nova"`, `"shimmer"`
  - **Smart voice selection**: leaving `"alloy"` automatically picks a best-fit voice for the detected language
- `language` (string, optional): Language code (auto-detected if not specified)
  - Supported: `en`, `es`, `fr`, `de`, `it`, `pt`, `ru`, `ja`, `ko`, `zh`, `ar`, `hi`
  - **Voice mapping**:
    - 🇺🇸 English (en) → alloy (clear neutral)
    - 🇪🇸 Spanish (es) → nova (warm female tone)
    - 🇫🇷 French (fr) → shimmer (bright, crisp)
    - 🇩🇪 German (de) → onyx (authoritative male tone)
    - 🇮🇹 Italian (it) → nova (expressive female tone)
    - 🇵🇹 Portuguese (pt) → nova (expressive female tone)
    - 🇷🇺 Russian (ru) → echo (deep male tone)
    - 🇯🇵 Japanese (ja) → shimmer (light precise voice)
    - 🇰🇷 Korean (ko) → shimmer (light precise voice)
    - 🇨🇳 Chinese (zh) → nova (balanced female voice)
    - 🇸🇦 Arabic (ar) → fable (deep male tone)
    - 🇮🇳 Hindi (hi) → nova (balanced female voice)
- `sync_method` (string, optional): Audio synchronization method
  - `"timing_analysis"` (default): Analyze animation timing for precise sync
  - `"narration_first"`: Generate narration then match video
  - `"subtitle_overlay"`: Add subtitles instead of audio sync

**Response (Success):**
```json
{
  "video_id": "550e8400-e29b-41d4-a716-446655440000",
  "video_url": "/videos/550e8400-e29b-41d4-a716-446655440000.mp4",
  "status": "success",
  "message": "Animation generated successfully"
}
```

**Response (Error):**
```json
{
  "detail": "Failed to generate animation: [error details]"
}
```

### `GET /videos/{video_id}.mp4` - Serve Video
Access generated video files directly.

**Example:** `http://localhost:8000/videos/550e8400-e29b-41d4-a716-446655440000.mp4`

## 💡 Usage Examples

### Using curl
```bash
# Basic animation generation
curl -X POST "http://localhost:8000/generate" \
     -H "Content-Type: application/json" \
     -d '{
       "prompt": "Show how derivatives work in calculus",
       "resolution": "m"
     }'

# With audio narration
curl -X POST "http://localhost:8000/generate" \
     -H "Content-Type: application/json" \
     -d '{
       "prompt": "Explain the Pythagorean theorem",
       "resolution": "h",
       "include_audio": true,
       "voice": "nova",
       "language": "en"
     }'
```

### Using Python requests
```python
import requests
import time

def generate_animation(prompt, **kwargs):
    """Generate an educational animation."""
    url = "http://localhost:8000/generate"
    
    payload = {
        "prompt": prompt,
        "resolution": kwargs.get("resolution", "m"),
        "include_audio": kwargs.get("include_audio", True),
        "voice": kwargs.get("voice", "alloy"),
        "language": kwargs.get("language", "en"),
        "sync_method": kwargs.get("sync_method", "timing_analysis")
    }
    
    print(f"Generating animation for: {prompt}")
    response = requests.post(url, json=payload)
    
    if response.status_code == 200:
        result = response.json()
        video_url = f"http://localhost:8000{result['video_url']}"
        print(f"✅ Animation ready: {video_url}")
        return result
    else:
        print(f"❌ Error: {response.text}")
        return None

# Examples
animations = [
    {
        "prompt": "Explain the Pythagorean theorem with a visual proof",
        "resolution": "h",
        "voice": "nova"
    },
    {
        "prompt": "Show how photosynthesis works in plants",
        "include_audio": True,
        "language": "en"
    },
    {
        "prompt": "Demonstrate how bubble sort algorithm works",
        "resolution": "m",
        "sync_method": "timing_analysis"
    }
]

for animation in animations:
    result = generate_animation(**animation)
    if result:
        print(f"Video ID: {result['video_id']}")
    print("-" * 50)
```

### Using JavaScript/Node.js
```javascript
const axios = require('axios');

async function generateAnimation(prompt, options = {}) {
    try {
        const response = await axios.post('http://localhost:8000/generate', {
            prompt: prompt,
            resolution: options.resolution || 'm',
            include_audio: options.include_audio !== false,
            voice: options.voice || 'alloy',
            language: options.language || 'en',
            sync_method: options.sync_method || 'timing_analysis'
        });
        
        const result = response.data;
        const videoUrl = `http://localhost:8000${result.video_url}`;
        
        console.log(`✅ Animation ready: ${videoUrl}`);
        return result;
    } catch (error) {
        console.error('❌ Error:', error.response?.data || error.message);
        return null;
    }
}

// Example usage
generateAnimation("Explain how neural networks learn", {
    resolution: "h",
    voice: "nova",
    language: "en"
});
```

## 🎯 Example Prompts

### Mathematics
- "Explain the Pythagorean theorem with a visual proof"
- "Show how calculus derivatives work with geometric interpretation"
- "Demonstrate the concept of limits in calculus"
- "Visualize how Fourier transforms work"
- "Explain complex numbers and their geometric representation"

### Science
- "Show how photosynthesis works in plants"
- "Explain DNA replication process step by step"
- "Demonstrate how planetary orbits work according to Kepler's laws"
- "Show how electromagnetic waves propagate"
- "Visualize how cellular mitosis occurs"

### Computer Science
- "Visualize how sorting algorithms work (bubble sort, merge sort)"
- "Explain how binary search trees function"
- "Show how neural networks learn through backpropagation"
- "Demonstrate how hash tables resolve collisions"
- "Visualize graph traversal algorithms (DFS, BFS)"

### Physics
- "Show how pendulum motion demonstrates simple harmonic motion"
- "Explain wave interference patterns"
- "Demonstrate conservation of momentum in collisions"
- "Visualize electric field lines around charges"
- "Show how lenses focus light rays"

## 🏗️ Project Structure

```
manimations/
├── app.py                 # Main FastAPI application
├── main.py               # Entry point
├── pyproject.toml        # Project configuration and dependencies
├── uv.lock               # Dependency lock file
├── README.md             # This file
├── DEPLOY.md             # Ubuntu deployment guide
├── .env.example          # Environment variables template
├── .gitignore           # Git ignore rules
├── models/               # Pydantic data models
│   └── schemas.py
├── services/             # Core business logic
│   ├── script_generator.py
│   ├── audio_processor.py
│   └── video_processor.py
├── utils/                # Configuration and helpers
│   ├── config.py
│   └── helpers.py
├── generated_videos/     # Served video files (created automatically)
├── temp_scripts/        # Temporary generated scripts (created automatically)
└── temp_output/         # Temporary Manim output (created automatically)
```

## ⚠️ Error Handling

The API includes comprehensive error handling for:

- **Invalid prompts**: Empty or malformed requests
- **Script generation failures**: Claude AI service issues
- **Manim execution errors**: Script compilation or rendering problems
- **Audio generation errors**: TTS service failures
- **File system issues**: Disk space, permissions
- **Missing API keys**: Configuration problems
- **FFmpeg errors**: Audio/video processing failures

**Common Error Responses:**
```json
{
  "detail": "ANTHROPIC_API_KEY not set"
}
```
```json
{
  "detail": "Failed to generate animation: Manim execution failed"
}
```

## 🔧 Configuration

### Environment Variables
- `ANTHROPIC_API_KEY`: Required for Claude AI script generation
- `OPENAI_API_KEY`: Required for TTS narration (optional if `include_audio=false`)
- `LOG_LEVEL`: Logging level (default: INFO)

### Performance Tuning
- **Video generation time**: 30 seconds to 5 minutes depending on complexity
- **Concurrent requests**: Supported, but resource-intensive
- **Disk space**: Each video ~1-50MB depending on resolution and duration
- **Memory usage**: 200-500MB per active generation

## 🚨 Troubleshooting

### Common Issues

1. **FFmpeg not found**
   ```bash
   # macOS
   brew install ffmpeg
   
   # Ubuntu
   sudo apt install ffmpeg
   ```

2. **LaTeX compilation errors**
   ```bash
   # Install full LaTeX distribution
   # macOS: brew install --cask mactex
   # Ubuntu: sudo apt install texlive-full
   ```

3. **API key errors**
   ```bash
   export ANTHROPIC_API_KEY="your-key-here"
   export OPENAI_API_KEY="your-key-here"
   ```

4. **Port already in use**
   ```bash
   uv run uvicorn app:app --port 8001  # Use different port
   ```

5. **Memory issues with large animations**
   - Use lower resolution (`"l"` instead of `"h"`)
   - Disable audio generation (`"include_audio": false`)
   - Simplify the prompt

### Debugging
Enable debug logging:
```bash
export LOG_LEVEL=DEBUG
uv run python main.py
```

Check logs:
```bash
tail -f manimations.log
```

## 📈 Performance Notes

- **Generation Time**: 30s-5min based on complexity and resolution
- **Resolution Impact**: 4K takes ~4x longer than 720p
- **Audio Processing**: Adds 10-30s to generation time
- **Concurrent Limits**: Recommended max 3 simultaneous generations
- **Caching**: Generated videos are cached and served statically

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Add tests if applicable
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- [Manim](https://www.manim.community/) - Mathematical Animation Engine
- [Anthropic Claude](https://www.anthropic.com/) - AI script generation
- [OpenAI](https://openai.com/) - Text-to-speech narration
- [FastAPI](https://fastapi.tiangolo.com/) - Web framework
