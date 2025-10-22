
# yt-dlp-slides

A Python tool for creating presentation-style videos from already-downloaded yt-dlp content.

## Prerequisites

This tool processes videos and slides that have been previously downloaded using yt-dlp with the following command:
```bash
yt-dlp --write-info-json --write-all-thumbnails [VIDEO_URL]
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
- Picture-in-picture of the speaker video in the top-right corner

## Usage

```bash
python yt_dlp_slides.py /path/to/downloaded/content/
```

The script will validate that all required files are present before processing. 


As a bonus, we could concatenate the slides in a PDF (again, not sure about embedded videos, and that PDF might be heavy because we're just collating images).