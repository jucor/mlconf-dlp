# mlconf-dlp

A Python wrapper around [yt-dlp](https://github.com/yt-dlp/yt-dlp) for downloading and processing ML conference videos from SlidesLive.

This tool extends yt-dlp by automatically merging conference slides with speaker video, creating presentation-style videos with picture-in-picture. It handles the complete workflow: downloading videos and slide thumbnails via yt-dlp, then composing them into a polished presentation video using FFmpeg.

**Note:** This could be implemented as a yt-dlp post-processor in the future, but is currently a standalone script for simplicity and flexibility.

## Prerequisites

- Python 3.8+
- FFmpeg installed on your system
- `uv` package manager (recommended) or `pip`

## Installation

```bash
# Clone the repository
git clone https://github.com/jucor/mlconf-dlp.git
cd mlconf-dlp

# Install dependencies using uv (recommended)
uv pip install -r requirements.txt

# OR using pip
# pip install -r requirements.txt

# Run the script
./mlconf-dlp.py "https://neurips.cc/virtual/2024/invited-talk/101133"
```

**Note:** With `uv pip install`, the virtual environment is automatically managed. With regular `pip`, you'll need to create and activate a venv first.

## How it works

This script wraps yt-dlp to download and then processes:
1. The speaker video file (e.g., `Conference Talk Title [ID].mp4`)
2. The JSON metadata file (e.g., `Conference Talk Title [ID].info.json`)
3. Slide images (e.g., `Conference Talk Title [ID].001.png`, `.002.png`, etc.)
4. Optional: Slide videos for animated slides (e.g., `Conference Talk Title - Slide 006 [ID-006].mp4`)

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

The tool accepts either a **conference video URL** (any conference that uses SlidesLive, e.g., NeurIPS, ICLR, ICML - downloads automatically) or a **local directory**:

**From a URL:**
```bash
python mlconf-dlp.py "https://neurips.cc/virtual/2024/invited-talk/101133"
```

**From a local directory:**
```bash
python mlconf-dlp.py /path/to/downloaded/content/
```

Or with `uv`:
```bash
uv run python mlconf-dlp.py "https://neurips.cc/virtual/2024/invited-talk/101133"
```

### Command-Line Options

```
Usage: mlconf-dlp.py [OPTIONS] INPUT

Arguments:
  INPUT                      Conference video URL (SlidesLive-based) or local directory

Options:
  -o, --output TEXT          Output video filename (default: INPUT_NAME_slides.mp4)
  --keep-temp                Keep temporary download folder (only for URLs)
  --temp-dir PATH            Use specific temporary directory (creates if doesn't exist, resumes if exists)
  --pip-scale FLOAT          Picture-in-picture scale factor (0-1, default: 0.1)
  --pip-position TEXT        Position: top-right, top-left, bottom-right, bottom-left (default: top-right)
  -v, --verbose              Enable verbose output for debugging
  --preset TEXT              Encoding preset: ultrafast (default), veryfast, medium, slow
  --crf INTEGER              Quality override (0-51, lower is better quality)
  --max-duration INTEGER     Maximum video duration in seconds (for debugging)
  --high-res-speaker         Download high-resolution speaker video (useful for larger PiP)
  --help                     Show this message and exit
```

### Examples

**Download from URL and create video:**
```bash
python mlconf-dlp.py "https://neurips.cc/virtual/2024/invited-talk/101133"
```

**Download and keep the temporary folder:**
```bash
python mlconf-dlp.py "https://neurips.cc/virtual/2024/invited-talk/101133" --keep-temp
```

**Use a specific temp directory (for resuming interrupted downloads):**
```bash
python mlconf-dlp.py "https://neurips.cc/virtual/2024/invited-talk/101133" --temp-dir my-download
```

**Resume from an existing temp directory:**
```bash
# If download was interrupted, resume using the same directory
python mlconf-dlp.py "https://neurips.cc/virtual/2024/invited-talk/101133" --temp-dir mlconf-dlp-abc123
```

**Quick test with max duration (first 60 seconds only):**
```bash
python mlconf-dlp.py "https://neurips.cc/virtual/2024/invited-talk/101133" --max-duration 60
```

**Basic usage with local directory (fastest, lower quality - default):**
```bash
python mlconf-dlp.py /path/to/conference-talk/
```

**Custom output filename:**
```bash
python mlconf-dlp.py /path/to/conference-talk/ -o my_presentation.mp4
```

**Larger PiP in bottom-right corner:**
```bash
python mlconf-dlp.py /path/to/conference-talk/ \
    --pip-scale 0.2 \
    --pip-position bottom-right
```

**Medium quality encoding (balanced speed and quality):**
```bash
python mlconf-dlp.py /path/to/conference-talk/ --preset medium
```

**High quality encoding (slower but best quality):**
```bash
python mlconf-dlp.py /path/to/conference-talk/ --preset slow
```

**Custom quality override:**
```bash
python mlconf-dlp.py /path/to/conference-talk/ --preset veryfast --crf 20
```

**Verbose output for debugging:**
```bash
python mlconf-dlp.py /path/to/conference-talk/ -v
```

## Speed vs Quality Guide

The `--preset` option controls both encoding speed and default quality:

| Preset      | Default CRF | Speed        | Quality      | Use Case                     |
|-------------|-------------|--------------|--------------|------------------------------|
| `ultrafast` | 28          | **Fastest**  | Lower        | **Default** - Quick testing  |
| `veryfast`  | 23          | Very Fast    | Good         | Fast iteration               |
| `medium`    | 23          | Medium       | Good         | Balanced speed and quality   |
| `slow`      | 18          | Slow         | Excellent    | Final output, best quality   |

**Notes:**
- Each preset automatically sets an appropriate CRF (quality) value
- Use `--crf` to override the default quality for any preset
- Lower CRF = better quality but larger files (0-51 range)
- `ultrafast` is the default for fastest processing

## File Validation

The script will validate that all required files are present before processing:
- Main speaker video found
- Metadata JSON file found
- All slide files exist (images or videos)
- JSON structure is valid with chapters and thumbnails

If any issues are found, the script will report specific errors and exit.
