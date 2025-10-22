#!/usr/bin/env python3
"""
yt-dlp-slides: A tool for creating presentation-style videos from yt-dlp content.

This script processes already-downloaded yt-dlp content to create a presentation video
with slides, audio, and picture-in-picture speaker video.
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import click
import ffmpeg


class ValidationError(Exception):
    """Custom exception for validation errors."""

    pass


class ContentValidator:
    """Validates that all required files are present in the input directory."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def _log(self, message: str):
        """Log message if verbose mode is enabled."""
        if self.verbose:
            click.echo(f"[Validator] {message}")

    def find_main_video(self, input_dir: Path) -> Path:
        """
        Find the main speaker video file.

        Pattern: [title] [id].mp4
        Excludes files with "Slide" in the name.

        Args:
            input_dir: Directory containing downloaded content

        Returns:
            Path to the main video file

        Raises:
            ValidationError: If no video found or multiple videos found
        """
        self._log(f"Looking for main video in {input_dir}")

        video_files = []
        for file in input_dir.glob("*.mp4"):
            # Exclude slide videos (contain "Slide" in the name)
            if "Slide" not in file.name and " - Slide " not in file.name:
                video_files.append(file)

        if len(video_files) == 0:
            raise ValidationError("No speaker video found. Expected: [title] [id].mp4")
        elif len(video_files) > 1:
            raise ValidationError(
                f"Multiple video files found: {[f.name for f in video_files]}. "
                "Please ensure only one main speaker video is present."
            )

        self._log(f"Found main video: {video_files[0].name}")
        return video_files[0]

    def find_info_json(self, input_dir: Path) -> Path:
        """
        Find the info.json metadata file.

        Pattern: [title] [id].info.json
        Excludes files with "Slide" or "playlist" in the name.

        Args:
            input_dir: Directory containing downloaded content

        Returns:
            Path to the info.json file

        Raises:
            ValidationError: If no JSON found or multiple found
        """
        self._log(f"Looking for info.json in {input_dir}")

        json_files = []
        for file in input_dir.glob("*.info.json"):
            # Exclude slide and playlist JSON files
            if "Slide" not in file.name and "playlist" not in file.name:
                json_files.append(file)

        if len(json_files) == 0:
            raise ValidationError("No info.json found. Expected: [title] [id].info.json")
        elif len(json_files) > 1:
            raise ValidationError(
                f"Multiple info.json files found: {[f.name for f in json_files]}. "
                "Please ensure only one main info.json is present."
            )

        self._log(f"Found info.json: {json_files[0].name}")
        return json_files[0]

    def validate_json_structure(self, json_path: Path) -> dict:
        """
        Validate that the JSON file has required structure.

        Required fields:
        - chapters: array with start_time, end_time, title
        - thumbnails: array with id, url

        Args:
            json_path: Path to the info.json file

        Returns:
            Parsed JSON data

        Raises:
            ValidationError: If JSON is malformed or missing required fields
        """
        self._log(f"Validating JSON structure: {json_path.name}")

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON file: {e}")

        # Check for required fields
        if "chapters" not in data or not isinstance(data["chapters"], list):
            raise ValidationError("JSON missing required field: chapters")

        if "thumbnails" not in data or not isinstance(data["thumbnails"], list):
            raise ValidationError("JSON missing required field: thumbnails")

        # Validate chapters structure
        for i, chapter in enumerate(data["chapters"]):
            if "start_time" not in chapter:
                raise ValidationError(f"Chapter {i} missing start_time")
            if "end_time" not in chapter:
                raise ValidationError(f"Chapter {i} missing end_time")

        # Validate thumbnails structure
        for i, thumbnail in enumerate(data["thumbnails"]):
            if "id" not in thumbnail:
                raise ValidationError(f"Thumbnail {i} missing id")
            if "url" not in thumbnail:
                raise ValidationError(f"Thumbnail {i} missing url")

        self._log(
            f"JSON valid: {len(data['chapters'])} chapters, {len(data['thumbnails'])} thumbnails"
        )
        return data

    def validate_slide_files(
        self, input_dir: Path, json_data: dict, video_name: str
    ) -> Dict[str, Tuple[Path, str]]:
        """
        Validate that slide files exist for each thumbnail.

        Checks for:
        1. Video slides: [title] - Slide [id] [video_id-id].mp4
        2. Image slides: [title] [video_id].[id].[ext]

        Args:
            input_dir: Directory containing downloaded content
            json_data: Parsed JSON metadata
            video_name: Name of the main video file (without extension)

        Returns:
            Dictionary mapping slide IDs to (path, type) tuples

        Raises:
            ValidationError: If required slide files are missing
        """
        self._log("Validating slide files")

        slide_mapping = {}
        thumbnails = json_data["thumbnails"]

        for thumbnail in thumbnails:
            slide_id = thumbnail["id"]
            url = thumbnail["url"]

            # Extract extension from URL
            url_path = Path(url)
            ext = url_path.suffix.lstrip(".")

            # Check for video slide first (priority)
            video_pattern = f"*Slide {slide_id}*.mp4"
            video_slides = list(input_dir.glob(video_pattern))

            if video_slides:
                slide_mapping[slide_id] = (video_slides[0], "video")
                self._log(f"Found video slide: {video_slides[0].name}")
                continue

            # Check for image slide
            image_path = input_dir / f"{video_name}.{slide_id}.{ext}"
            if image_path.exists():
                slide_mapping[slide_id] = (image_path, "image")
                self._log(f"Found image slide: {image_path.name}")
            else:
                # Try other common image extensions
                found = False
                for alt_ext in ["png", "jpg", "jpeg", "webp"]:
                    alt_path = input_dir / f"{video_name}.{slide_id}.{alt_ext}"
                    if alt_path.exists():
                        slide_mapping[slide_id] = (alt_path, "image")
                        self._log(f"Found image slide: {alt_path.name}")
                        found = True
                        break

                if not found:
                    raise ValidationError(
                        f"Slide file not found for thumbnail {slide_id}. "
                        f"Expected: {video_name}.{slide_id}.{ext}"
                    )

        self._log(f"Found {len(slide_mapping)} slide files")
        return slide_mapping

    def validate_all(self, input_dir: str) -> Tuple[Path, dict, Dict[str, Tuple[Path, str]]]:
        """
        Main validation entry point.

        Runs all validations in sequence.

        Args:
            input_dir: Path to directory containing downloaded content

        Returns:
            Tuple of (video_path, json_data, slide_mapping)

        Raises:
            ValidationError: If any validation fails
        """
        input_path = Path(input_dir).resolve()

        if not input_path.exists():
            raise ValidationError(f"Input directory does not exist: {input_dir}")

        if not input_path.is_dir():
            raise ValidationError(f"Input path is not a directory: {input_dir}")

        # Find main video
        video_path = self.find_main_video(input_path)
        video_name = video_path.stem  # Name without extension

        # Find and validate JSON
        json_path = self.find_info_json(input_path)
        json_data = self.validate_json_structure(json_path)

        # Validate slide files
        slide_mapping = self.validate_slide_files(input_path, json_data, video_name)

        return video_path, json_data, slide_mapping


class SlideMapper:
    """Maps chapters to slide files and builds timeline."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def _log(self, message: str):
        """Log message if verbose mode is enabled."""
        if self.verbose:
            click.echo(f"[Mapper] {message}")

    def build_slide_timeline(
        self, json_data: dict, slide_mapping: Dict[str, Tuple[Path, str]]
    ) -> List[Tuple[float, float, Path, str]]:
        """
        Build timeline mapping chapters to slide files.

        Creates a timeline structure: [(start_time, end_time, slide_path, slide_type)]

        Args:
            json_data: Parsed JSON metadata
            slide_mapping: Dictionary mapping slide IDs to (path, type) tuples

        Returns:
            List of timeline entries

        Raises:
            ValidationError: If chapters cannot be mapped to slides
        """
        import re

        self._log("Building slide timeline")

        chapters = json_data["chapters"]

        timeline = []

        for i, chapter in enumerate(chapters):
            start_time = float(chapter["start_time"])
            end_time = float(chapter["end_time"])
            title = chapter.get("title", f"Chapter {i+1}")

            # Duration should be at least 0.1 seconds to avoid ffmpeg issues
            duration = end_time - start_time
            if duration < 0.1:
                self._log(
                    f"Warning: Chapter {i+1} duration too short ({duration}s), setting to 0.1s"
                )
                end_time = start_time + 0.1

            # Extract slide ID from chapter title (e.g., "Slide 001" -> "001")
            slide_id_match = re.search(r"Slide\s+(\d+)", title)

            if slide_id_match:
                slide_id = slide_id_match.group(1)

                if slide_id in slide_mapping:
                    slide_path, slide_type = slide_mapping[slide_id]
                    timeline.append((start_time, end_time, slide_path, slide_type))
                    self._log(
                        f"Chapter {i+1} ({title}): {start_time:.2f}s-{end_time:.2f}s -> {slide_path.name} ({slide_type})"
                    )
                else:
                    self._log(f"Warning: No slide file found for chapter {i+1} ({title}), skipping")
            else:
                self._log(
                    f"Warning: Could not extract slide ID from chapter title '{title}', skipping"
                )

        if not timeline:
            raise ValidationError("No chapters found to create timeline")

        self._log(f"Built timeline with {len(timeline)} entries")
        return timeline


class VideoGenerator:
    """Generates the final video using FFmpeg."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def _log(self, message: str):
        """Log message if verbose mode is enabled."""
        if self.verbose:
            click.echo(f"[Generator] {message}")

    def process(
        self,
        timeline: List[Tuple[float, float, Path, str]],
        speaker_video: Path,
        output: str,
        pip_scale: float,
        pip_position: str,
        preset: str = "medium",
        crf: int = 23,
    ):
        """
        Generate the final presentation video.

        Args:
            timeline: List of (start_time, end_time, slide_path, slide_type) tuples
            speaker_video: Path to the main speaker video
            output: Output filename
            pip_scale: Scale factor for picture-in-picture (0-1)
            pip_position: Position of PiP (top-right, top-left, bottom-right, bottom-left)
            preset: FFmpeg encoding preset (ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow)
            crf: Constant Rate Factor for quality (0-51, lower is better quality, 23 is default)
        """
        self._log("Starting video generation")
        self._log(f"Output: {output}")

        # Build slide streams
        slide_streams = []

        for i, (start_time, end_time, slide_path, slide_type) in enumerate(timeline):
            duration = end_time - start_time
            self._log(
                f"Processing slide {i+1}/{len(timeline)}: {slide_path.name} ({slide_type}, {duration:.2f}s)"
            )

            if slide_type == "image":
                # Create looped image for duration
                stream = (
                    ffmpeg.input(str(slide_path), loop=1, t=duration, framerate=25)
                    .filter("scale", "trunc(iw/2)*2", "trunc(ih/2)*2")  # Ensure even dimensions
                    .filter("setsar", "1")  # Set sample aspect ratio to 1:1
                )
            else:  # video
                # Use video slide, trim to duration if needed
                stream = (
                    ffmpeg.input(str(slide_path))
                    .filter("trim", duration=duration)
                    .filter("setpts", "PTS-STARTPTS")
                    .filter("scale", "trunc(iw/2)*2", "trunc(ih/2)*2")  # Ensure even dimensions
                )

            slide_streams.append(stream)

        # Concatenate all slides
        self._log("Concatenating slides")
        slides = ffmpeg.concat(*slide_streams, v=1, a=0).node

        # Create PiP from speaker video
        self._log(f"Creating picture-in-picture (scale={pip_scale}, position={pip_position})")
        speaker = ffmpeg.input(str(speaker_video))

        # Scale the PiP
        # Calculate width, then height with aspect ratio maintained and even value
        pip = speaker.video.filter(
            "scale", f"iw*{pip_scale}", "-2"
        )  # -2 maintains aspect ratio with even height

        # Position mapping (no padding, directly in corners)
        positions = {
            "top-right": {"x": "W-w", "y": "0"},
            "top-left": {"x": "0", "y": "0"},
            "bottom-right": {"x": "W-w", "y": "H-h"},
            "bottom-left": {"x": "0", "y": "H-h"},
        }

        # Overlay PiP on slides
        video = ffmpeg.overlay(slides[0], pip, **positions[pip_position])

        # Use audio from speaker video
        audio = speaker.audio

        # Output
        self._log("Running FFmpeg")
        try:
            output_args = {
                "vcodec": "libx264",
                "acodec": "aac",
                "strict": "experimental",
                "preset": preset,
                "crf": crf,
            }

            ffmpeg.output(video, audio, output, **output_args).overwrite_output().run(
                capture_stdout=not self.verbose, capture_stderr=not self.verbose
            )

            self._log(f"Video generation complete: {output}")
            click.echo(f"✓ Successfully created: {output}")

        except ffmpeg.Error as e:
            if self.verbose and e.stderr:
                click.echo(e.stderr.decode(), err=True)
            raise ValidationError(f"FFmpeg error during video generation: {e}")


@click.command()
@click.argument("input_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--output", "-o", help="Output video filename (default: INPUT_NAME_slides.mp4)")
@click.option(
    "--pip-scale",
    default=0.1,
    type=float,
    help="Picture-in-picture scale factor (0-1, default: 0.1)",
)
@click.option(
    "--pip-position",
    default="top-right",
    type=click.Choice(
        ["top-right", "top-left", "bottom-right", "bottom-left"], case_sensitive=False
    ),
    help="Picture-in-picture position (default: top-right)",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output for debugging")
@click.option(
    "--preset",
    default="medium",
    type=click.Choice(
        [
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        ],
        case_sensitive=False,
    ),
    help="FFmpeg encoding preset (default: medium). Use 'veryfast' or 'ultrafast' for faster encoding.",
)
@click.option(
    "--crf",
    default=23,
    type=int,
    help="Quality setting (0-51, lower is better quality, default: 23)",
)
def main(
    input_dir: str,
    output: Optional[str],
    pip_scale: float,
    pip_position: str,
    verbose: bool,
    preset: str,
    crf: int,
):
    """
    Process yt-dlp downloaded content into presentation video.

    This tool creates a presentation-style video from already-downloaded yt-dlp content,
    combining slides with speaker audio and picture-in-picture video.

    INPUT_DIR should contain:
    - Main speaker video: [title] [id].mp4
    - Metadata: [title] [id].info.json
    - Slide images: [title] [id].[slide_id].[ext]
    - Optional slide videos: [title] - Slide [slide_id] [id-slide_id].mp4
    """

    # Validate pip_scale
    if not 0 < pip_scale <= 1:
        click.echo("Error: --pip-scale must be between 0 and 1", err=True)
        sys.exit(1)

    # Validate crf
    if not 0 <= crf <= 51:
        click.echo("Error: --crf must be between 0 and 51", err=True)
        sys.exit(1)

    # Initialize components
    validator = ContentValidator(verbose=verbose)
    mapper = SlideMapper(verbose=verbose)
    generator = VideoGenerator(verbose=verbose)

    # Step 1: Validate all files present
    if verbose:
        click.echo("=" * 60)
        click.echo("Step 1: Validating input files")
        click.echo("=" * 60)

    try:
        video_path, json_data, slide_mapping = validator.validate_all(input_dir)
    except ValidationError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Step 2: Build slide timeline
    if verbose:
        click.echo("\n" + "=" * 60)
        click.echo("Step 2: Building slide timeline")
        click.echo("=" * 60)

    try:
        timeline = mapper.build_slide_timeline(json_data, slide_mapping)
    except ValidationError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Generate output filename if not provided
    if not output:
        output = str(video_path.parent / f"{video_path.stem}_slides.mp4")

    # Step 3: Generate video
    if verbose:
        click.echo("\n" + "=" * 60)
        click.echo("Step 3: Generating video")
        click.echo("=" * 60)

    try:
        generator.process(
            timeline=timeline,
            speaker_video=video_path,
            output=output,
            pip_scale=pip_scale,
            pip_position=pip_position,
            preset=preset,
            crf=crf,
        )
    except ValidationError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        if verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
