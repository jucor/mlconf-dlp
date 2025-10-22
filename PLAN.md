# Implementation Plan for yt-dlp-slides

## Overview
A Python tool that processes already-downloaded yt-dlp content to create a presentation-style video with slides, audio, and picture-in-picture speaker video.

## Project Structure
```
yt-dlp-slides/
├── yt_dlp_slides.py       # Main script with all modules
├── requirements.txt        # Dependencies
├── PLAN.md                # This implementation plan
├── data/                   # Example downloaded content
│   └── 2025/
└── README.md
```

## Dependencies
```python
# requirements.txt
click>=8.1.0           # Command-line interface
ffmpeg-python>=0.2.0   # FFmpeg Python bindings
```

## Implementation Steps

### Step 1: Command-Line Interface
Create a CLI using click that accepts:
- `input_dir` (required) - Directory containing yt-dlp downloads
- `--output` / `-o` - Output video filename (default: `{input_name}_slides.mp4`)
- `--pip-scale` - PiP scale factor (default: 0.25)
- `--pip-position` - PiP position (default: "top-right", choices: top-right, top-left, bottom-right, bottom-left)
- `--verbose` / `-v` - Verbose output for debugging

### Step 2: Validation Module
Create a `ContentValidator` class that:

1. **find_main_video(input_dir)** - Find video file matching pattern: `[title] [id].mp4`
   - Exclude files with "Slide" in the name
   - Return path to main speaker video

2. **find_info_json(input_dir)** - Find JSON file matching pattern: `[title] [id].info.json`
   - Return path to JSON metadata file

3. **validate_json_structure(json_path)** - Validate JSON has required fields:
   - `chapters` array with `start_time`, `end_time`, `title` for each chapter
   - `thumbnails` array with `id` and `url` for each thumbnail
   - Return parsed JSON data

4. **validate_slide_files(input_dir, json_data)** - For each thumbnail in JSON:
   - Extract file extension from `url` field
   - Check if slide file exists: `[title] [id].[thumbnail_id].[ext]`
   - Also check for video slides: `[title] - Slide [thumbnail_id] [id-thumbnail_id].mp4`
   - Return mapping of slide IDs to file paths

5. **validate_all(input_dir)** - Main validation entry point:
   - Run all validations in sequence
   - Return tuple: (video_path, json_data, slide_mapping)
   - Raise `ValidationError` with specific message for any missing files

### Step 3: Slide Mapping Module
Create a `SlideMapper` class that:

1. **build_slide_timeline(input_dir, json_data, slide_mapping)**
   - Create timeline structure: `[(start_time, end_time, slide_path, slide_type)]`
   - `slide_type` is either 'image' or 'video'
   - Match each chapter to its corresponding slide file
   - Handle cases where slide might be missing (use previous slide or error)

2. **find_slide_file(input_dir, video_id, slide_id, thumbnail_url)**
   - Priority order:
     1. Check for video slide: `*Slide {slide_id}*.mp4`
     2. Check for image: `[base_name].[slide_id].[ext]`
   - Return tuple: (path, type)

### Step 4: Video Generation Module
Create a `VideoGenerator` class that:

1. **create_slides_stream(timeline)** - Build ffmpeg filter for slide sequence:
   - For images: use `loop` filter with duration
   - For videos: trim to chapter duration
   - Concatenate all slides into single stream

2. **extract_audio(video_path)** - Extract audio from speaker video:
   - Preserve original quality/codec
   - Return audio stream reference

3. **create_pip_overlay(speaker_video, scale, position)** - Create PiP:
   - Scale speaker video by scale factor
   - Position according to chosen corner with padding

4. **generate_final_video(slides_stream, audio_stream, pip_stream, output_path)**
   - Build complex filter graph:
     1. Overlay PiP on slides
     2. Add audio track
     3. Ensure proper sync
   - Execute ffmpeg command
   - Show progress if verbose mode

### Step 5: Main Coordinator
```python
@click.command()
@click.argument('input_dir', type=click.Path(exists=True, dir_okay=True))
@click.option('--output', '-o', help='Output video filename')
@click.option('--pip-scale', default=0.25, help='PiP scale (0-1)')
@click.option('--pip-position', default='top-right',
              type=click.Choice(['top-right', 'top-left', 'bottom-right', 'bottom-left']))
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def main(input_dir, output, pip_scale, pip_position, verbose):
    """Process yt-dlp downloaded content into presentation video"""

    # Step 1: Validate all files present
    try:
        video_path, json_data, slide_files = validator.validate_all(input_dir)
    except ValidationError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Step 2: Build slide timeline
    timeline = mapper.build_slide_timeline(input_dir, json_data, slide_files)

    # Step 3: Generate video
    generator.process(
        timeline=timeline,
        speaker_video=video_path,
        output=output or generate_output_name(video_path),
        pip_scale=pip_scale,
        pip_position=pip_position
    )
```

## File Naming Patterns

Based on the example data in `/data/2025/OpenWorld-Tim/`:

```
# Main video (speaker):
[title] [video_id].mp4
Example: "Open-Endedness, World Models, and the Automation of Innovation [39038746].mp4"

# Info JSON:
[title] [video_id].info.json
Example: "Open-Endedness, World Models, and the Automation of Innovation [39038746].info.json"

# Slide images:
[title] [video_id].[slide_id].[extension]
Example: "Open-Endedness, World Models, and the Automation of Innovation [39038746].001.png"

# Slide videos (animated slides):
[title] - Slide [slide_id] [video_id-slide_id].mp4
Example: "Open-Endedness, World Models, and the Automation of Innovation - Slide 006 [39038746-006].mp4"
```

## Error Handling

Create custom `ValidationError` exception with specific error messages:
- "No speaker video found. Expected: [title] [id].mp4"
- "No info.json found. Expected: [title] [id].info.json"
- "JSON missing required field: chapters"
- "JSON missing required field: thumbnails"
- "Slide file not found: {expected_path} (from thumbnail {id})"
- "No slides found for chapter {n}: {title}"

## FFmpeg Pipeline Details

### Building the Complex Filter
```python
# Pseudo-code for building ffmpeg command
def build_ffmpeg_command(timeline, speaker_video, output):
    import ffmpeg

    # Collect all input streams
    inputs = []

    # Build slide sequence
    slide_streams = []
    for i, (start, end, slide_path, slide_type) in enumerate(timeline):
        duration = end - start

        if slide_type == 'image':
            # Create looped image for duration
            stream = (
                ffmpeg.input(slide_path, loop=1, t=duration)
                .filter('scale', 'trunc(iw/2)*2', 'trunc(ih/2)*2')  # Ensure even dimensions
            )
        else:  # video
            # Trim video to duration
            stream = (
                ffmpeg.input(slide_path)
                .filter('trim', start=0, end=duration)
                .filter('setpts', 'PTS-STARTPTS')
            )

        slide_streams.append(stream)

    # Concatenate all slides
    slides = ffmpeg.concat(*slide_streams, v=1, a=0)

    # Create PiP from speaker video
    speaker = ffmpeg.input(speaker_video)
    pip = speaker.video.filter('scale', f'iw*{pip_scale}:ih*{pip_scale}')

    # Position PiP based on pip_position
    positions = {
        'top-right': {'x': 'W-w-10', 'y': '10'},
        'top-left': {'x': '10', 'y': '10'},
        'bottom-right': {'x': 'W-w-10', 'y': 'H-h-10'},
        'bottom-left': {'x': '10', 'y': 'H-h-10'}
    }

    # Overlay PiP on slides
    video = ffmpeg.overlay(slides, pip, **positions[pip_position])

    # Use audio from speaker video
    audio = speaker.audio

    # Output
    ffmpeg.output(video, audio, output, codec='copy').run()
```

## Testing & Edge Cases

1. **Missing chapters** - Error out (chapters are required for timing)
2. **Missing thumbnails for some chapters** - Try to use previous slide or error with specific message
3. **Mixed slide formats** - Support PNG, JPG, WEBP for images
4. **Very short chapters** (< 1 second) - Set minimum duration to avoid ffmpeg issues
5. **Missing slide videos** - Fall back to static image if available
6. **Audio sync** - Ensure total duration matches original
7. **Different video codecs** - Let ffmpeg handle codec detection
8. **Empty input directory** - Clear error message
9. **Multiple video files** - Provide guidance on which one to use

## Code Style & Comments

- Use clear variable names that describe the content
- Add docstrings to all classes and major functions
- Include inline comments for complex ffmpeg operations
- Log operations in verbose mode to help debugging
- Use type hints where helpful for clarity

## Example Usage

```bash
# Basic usage
python yt_dlp_slides.py ./data/2025/OpenWorld-Tim/

# With options
python yt_dlp_slides.py ./data/2025/OpenWorld-Tim/ \
    --output presentation.mp4 \
    --pip-scale 0.3 \
    --pip-position bottom-right \
    --verbose
```

## Future Enhancements (Not in initial implementation)
- PDF generation from slides
- Custom transitions between slides
- Title cards from chapter names
- Multiple speaker video positions
- Custom slide timing overrides