# yt-dlp-slides

A Python tool for creating presentation-style videos from already-downloaded yt-dlp content.

## Prerequisites

- Python 3.8+
- FFmpeg installed on your system
- `uv` package manager (recommended) or `pip`

This tool processes videos and slides that have been previously downloaded using yt-dlp with the following command:
```bash
yt-dlp --write-info-json --write-all-thumbnails [VIDEO_URL]
```

## Installation

### Using uv (recommended)

```bash
# Create virtual environment
uv venv

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
uv pip install -r requirements.txt
```

### Using pip

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
source .venv/bin/activate  # On macOS/Linux
# or
.venv\Scripts\activate     # On Windows

# Install dependencies
pip install -r requirements.txt
```

## How it works

This script processes a directory containing:
1. The speaker video file (e.g., `Open-Endedness, World Models, and the Automation of Innovation [39038746].mp4`)
2. The JSON metadata file (e.g., `Open-Endedness, World Models, and the Automation of Innovation [39038746].info.json`)
3. Slide images (e.g., `Open-Endedness, World Models, and the Automation of Innovation [39038746].001.png`)
4. Optional: Slide videos for animated slides (e.g., `Open-Endedness, World Models, and the Automation of Innovation - Slide 006 [39038746-006].mp4`)

The JSON file contains:
- `chapters[].start_time` and `chapters[].end_time`: When to display each slide
- `thumbnails[].id`: Slide identifier (e.g., "001", "002")
- `thumbnails[].url`: URL with file extension indicating the saved thumbnail format

The script generates a new video with:
- Slides displayed as fixed images (or videos for animated slides), timed to chapter durations
- Audio track from the original speaker video
- Picture-in-picture of the speaker video in the corner (configurable size and position)

## Usage

### Basic Usage

```bash
python yt_dlp_slides.py /path/to/downloaded/content/
```

Or with `uv`:
```bash
uv run python yt_dlp_slides.py /path/to/downloaded/content/
```

### Command-Line Options

```
Usage: yt_dlp_slides.py [OPTIONS] INPUT_DIR

Options:
  -o, --output TEXT          Output video filename (default: INPUT_NAME_slides.mp4)
  --pip-scale FLOAT          Picture-in-picture scale factor (0-1, default: 0.1)
  --pip-position TEXT        Position: top-right, top-left, bottom-right, bottom-left
  -v, --verbose              Enable verbose output for debugging
  --preset TEXT              Encoding preset: ultrafast, veryfast, faster, medium (default), slow
  --crf INTEGER              Quality setting (0-51, lower is better, default: 23)
  --help                     Show this message and exit
```

### Examples

**Basic usage with default settings:**
```bash
python yt_dlp_slides.py data/2025/OpenWorld-Tim/
```

**Custom output filename:**
```bash
python yt_dlp_slides.py data/2025/OpenWorld-Tim/ -o my_presentation.mp4
```

**Larger PiP in bottom-right corner:**
```bash
python yt_dlp_slides.py data/2025/OpenWorld-Tim/ \
    --pip-scale 0.2 \
    --pip-position bottom-right
```

**Fast encoding for quick testing (5-10x faster):**
```bash
python yt_dlp_slides.py data/2025/OpenWorld-Tim/ \
    --preset ultrafast \
    --crf 28
```

**High quality encoding (slower but better quality):**
```bash
python yt_dlp_slides.py data/2025/OpenWorld-Tim/ \
    --preset slow \
    --crf 18
```

**Verbose output for debugging:**
```bash
python yt_dlp_slides.py data/2025/OpenWorld-Tim/ -v
```

## Speed vs Quality Guide

The `--preset` option has the biggest impact on encoding speed:

| Preset      | Speed        | File Size | Use Case                    |
|-------------|--------------|-----------|------------------------------|
| `ultrafast` | **Fastest**  | Largest   | Quick testing/previews       |
| `veryfast`  | Very Fast    | Large     | Fast iteration               |
| `faster`    | Fast         | Medium    | Balanced speed               |
| `medium`    | **Default**  | Medium    | General use                  |
| `slow`      | Slow         | Small     | Final output, good quality   |
| `slower`    | Very Slow    | Smaller   | Best quality, patient users  |

The `--crf` option controls quality (lower = better):

| CRF Value | Quality      | File Size |
|-----------|--------------|-----------|
| 18        | Very High    | Large     |
| 23        | **Default**  | Medium    |
| 28        | Lower        | Smaller   |

**Recommended combinations:**
- **Quick test:** `--preset ultrafast --crf 28` (5-10x faster)
- **Preview:** `--preset veryfast --crf 23` (3-5x faster, decent quality)
- **Final output:** `--preset medium --crf 23` (default, balanced)
- **Best quality:** `--preset slow --crf 18` (slower, best quality)

## File Validation

The script will validate that all required files are present before processing:
- Main speaker video found
- Metadata JSON file found
- All slide files exist (images or videos)
- JSON structure is valid with chapters and thumbnails

If any issues are found, the script will report specific errors and exit.
