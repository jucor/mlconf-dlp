#!/usr/bin/env python3
"""
yt-dlp-slides: A tool for creating presentation-style videos from yt-dlp content.

This script processes already-downloaded yt-dlp content to create a presentation video
with slides, audio, and picture-in-picture speaker video.
"""

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from urllib.parse import urlparse

import click
import ffmpeg
import yt_dlp


class ValidationError(Exception):
    """Custom exception for validation errors."""

    pass


class VideoDownloader:
    """Downloads videos from URLs using yt-dlp."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def download_video(self, url: str, output_dir: str, high_res_speaker: bool = False) -> str:
        """
        Download a video and its metadata using yt-dlp.

        Args:
            url: Video URL to download
            output_dir: Directory to save downloaded files
            high_res_speaker: If True, download best quality video; if False, use worst video for smaller file size

        Returns:
            Path to the directory containing downloaded files

        Raises:
            ValidationError: If download fails
        """
        click.echo(f"Downloading video from: {url}")
        click.echo(f"Saving to: {output_dir}")

        # Custom logger to capture thumbnail download messages
        import re
        import logging
        from tqdm import tqdm

        class ThumbnailLogger:
            """Custom logger to capture and display thumbnail download info with progress bar."""

            def __init__(self, verbose):
                self.verbose = verbose
                self.pbar = None  # Progress bar for thumbnails
                self.max_slide = None  # Highest slide number (initialized on first thumbnail)
                self.downloading_video = False  # Track when video download starts

            def _handle_thumbnail(self, msg):
                """Handle thumbnail download messages and update progress bar."""
                match = re.search(r"\.(\d+)\.(png|jpg|jpeg|webp)", msg)
                if match:
                    slide_num = int(match.group(1))

                    # Initialize progress bar on first thumbnail (highest number)
                    if self.pbar is None:
                        self.max_slide = slide_num
                        # Total slides from max_slide down to 1 (not 0)
                        self.pbar = tqdm(
                            total=slide_num,  # Count from max_slide to 1
                            desc="Downloading slides",
                            unit="slide",
                            initial=0
                        )

                    # Update progress: count how many slides we've completed
                    # yt-dlp goes from max down to 1, so completed = (max_slide - current_slide)
                    completed = self.max_slide - slide_num
                    self.pbar.n = completed
                    self.pbar.set_postfix_str(f"slide {slide_num}")
                    self.pbar.refresh()

                    # Close progress bar when we reach slide 1
                    if slide_num == 1 and self.pbar is not None:
                        self.pbar.n = self.max_slide  # Complete it
                        self.pbar.close()
                        self.pbar = None

                    return True
                return False

            def debug(self, msg):
                # Capture thumbnail download messages (ALWAYS, even in non-verbose mode)
                if "Writing thumbnail" in msg or "Writing video thumbnail" in msg or "thumbnail" in msg.lower():
                    if self._handle_thumbnail(msg):
                        return

                # Show ALL debug messages during video download (even in non-verbose mode)
                if self.downloading_video:
                    click.echo(f"[debug] {msg}")
                    return

                # Only show other debug messages in verbose mode
                if self.verbose:
                    click.echo(f"[debug] {msg}")

            def info(self, msg):
                # Capture thumbnail download messages (ALWAYS, even in non-verbose mode)
                # yt-dlp outputs: "[info] Writing thumbnail to: filename.123.png"
                if "Writing thumbnail" in msg or "Writing video thumbnail" in msg:
                    if self._handle_thumbnail(msg):
                        return

                # Detect when yt-dlp moves on from downloading slides to other activities
                # This could be: downloading video files, extracting info, merging formats, etc.
                # Close the thumbnail progress bar if it's still open and we see non-slide activity
                if self.pbar is not None:
                    # These messages indicate yt-dlp has moved on from slides
                    non_slide_indicators = [
                        "Downloading",
                        "destination:",
                        "[download]",
                        "Merging formats",
                        "Deleting original file",
                        "has already been downloaded",
                        "Extracting URL",
                        "[ExtractAudio]",
                        "Post-processing"
                    ]
                    if any(indicator in msg for indicator in non_slide_indicators):
                        # Complete and close the progress bar
                        self.pbar.n = self.pbar.total  # Mark as complete
                        self.pbar.close()
                        self.pbar = None
                        self.downloading_video = True

                # Show video download and processing messages (ALWAYS, even in non-verbose mode)
                if self.downloading_video:
                    click.echo(f"[info] {msg}")
                    return

                # Only show other info messages in verbose mode
                if self.verbose:
                    click.echo(f"[info] {msg}")

            def warning(self, msg):
                # Always show warnings during video download
                if self.downloading_video:
                    click.echo(f"[warning] {msg}")
                    return

                if self.verbose:
                    click.echo(f"[warning] {msg}")

            def error(self, msg):
                click.echo(f"[error] {msg}", err=True)

        logger = ThumbnailLogger(self.verbose)

        # Check if the URL is from SlidesLive (the intended platform)
        # This tool is designed for SlidesLive videos which have chapter slides
        try:
            click.echo("Checking video source...")
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                # Extract info without downloading to check the extractor
                test_info = ydl.extract_info(url, download=False)
                extractor = test_info.get('extractor_key', 'unknown')

                if extractor != 'SlidesLive':
                    click.echo(f"\n⚠️  Warning: This video is from '{extractor}', not SlidesLive.", err=True)
                    click.echo("This tool is specifically designed for SlidesLive conference presentations.", err=True)
                    click.echo("Videos from other platforms likely won't have chapter slides and may not work correctly.", err=True)

                    # Ask user if they want to proceed anyway (default: No)
                    if not click.confirm("\nDo you want to proceed anyway?", default=False):
                        raise ValidationError("Download cancelled by user - video not from SlidesLive")

                    click.echo("\nProceeding with download (may not work as expected)...\n")
                else:
                    click.echo(f"✓ Detected SlidesLive video - compatible format")

        except yt_dlp.utils.DownloadError as e:
            raise ValidationError(f"Could not access URL: {e}")

        # Download in two passes:
        # Pass 1: Download thumbnails only (with custom logger for progress bar)
        # Pass 2: Download videos (without logger to show native yt-dlp progress)

        try:
            # Pass 1: Thumbnails with progress bar
            click.echo("Downloading slides...")
            ydl_opts_thumbnails = {
                "skip_download": True,  # Don't download videos in this pass
                "writeinfojson": True,  # --write-info-json: save metadata
                "write_all_thumbnails": True,  # --write-all-thumbnails: save ALL thumbnails
                "outtmpl": os.path.join(output_dir, "%(title)s [%(id)s].%(ext)s"),
                "logger": logger,  # Use custom logger for thumbnail progress
            }

            with yt_dlp.YoutubeDL(ydl_opts_thumbnails) as ydl:
                info = ydl.extract_info(url, download=True)

            # Pass 2: Download videos with native yt-dlp progress (no custom logger)
            click.echo("\nDownloading video files...")

            # Determine format based on high_res_speaker flag
            if high_res_speaker:
                # High resolution: best audio + best video
                video_format = "bestaudio+bestvideo"
                click.echo("Using high-resolution speaker video (bestaudio+bestvideo)")
            else:
                # Low resolution for PiP: best audio + worst video, fallback to best video for slides
                video_format = "bestaudio+worstvideo/bestvideo"
                click.echo("Using low-resolution speaker video (bestaudio+worstvideo/bestvideo)")

            ydl_opts_videos = {
                "concurrent_fragment_downloads": 5,  # -N 5: parallel downloads
                "format": video_format,
                "outtmpl": os.path.join(output_dir, "%(title)s [%(id)s].%(ext)s"),
                # No logger - let yt-dlp show its native progress bars
            }

            with yt_dlp.YoutubeDL(ydl_opts_videos) as ydl:
                ydl.download([url])

                if info:
                    click.echo(f"✓ Download complete: {info.get('title', 'Video')}")
                    return output_dir

        except Exception as e:
            raise ValidationError(f"Download failed: {e}")


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

        import re

        slide_mapping = {}
        chapters = json_data["chapters"]
        thumbnails = json_data["thumbnails"]

        # Create a set of thumbnail IDs for quick lookup
        thumbnail_ids = {thumb["id"] for thumb in thumbnails}

        # Counters for reporting
        skipped_count = 0
        image_count = 0
        video_count = 0

        # Go through chapters and match with thumbnails
        thumbnail_idx = 0
        for chapter_idx, chapter in enumerate(chapters):
            # Extract slide ID from chapter title (e.g., "Slide 006" -> "006")
            title = chapter.get("title", "")
            match = re.search(r"Slide\s+(\d+)", title)

            if not match:
                self._log(
                    f"Warning: Chapter {chapter_idx} has no slide ID in title: '{title}', skipping"
                )
                skipped_count += 1
                continue

            slide_id = match.group(1)

            # Check if this slide has a thumbnail (image)
            if slide_id in thumbnail_ids:
                # This slide has an image - use the thumbnail
                # Find the thumbnail with this ID
                thumbnail = next((t for t in thumbnails if t["id"] == slide_id), None)
                if thumbnail:
                    url = thumbnail["url"]
                    url_path = Path(url)
                    ext = url_path.suffix.lstrip(".")

                    # Check for image slide
                    image_path = input_dir / f"{video_name}.{slide_id}.{ext}"
                    if image_path.exists():
                        slide_mapping[slide_id] = (image_path, "image")
                        image_count += 1
                        self._log(f"Found image slide: {image_path.name}")
                    else:
                        # Try other common image extensions
                        found = False
                        for alt_ext in ["png", "jpg", "jpeg", "webp"]:
                            alt_path = input_dir / f"{video_name}.{slide_id}.{alt_ext}"
                            if alt_path.exists():
                                slide_mapping[slide_id] = (alt_path, "image")
                                image_count += 1
                                self._log(f"Found image slide: {alt_path.name}")
                                found = True
                                break

                        if not found:
                            raise ValidationError(
                                f"Slide file not found for thumbnail {slide_id}. "
                                f"Expected: {video_name}.{slide_id}.{ext}"
                            )
            else:
                # This slide does NOT have a thumbnail - look for video slide
                video_pattern = f"*Slide {slide_id}*.mp4"
                video_slides = list(input_dir.glob(video_pattern))

                if video_slides:
                    slide_mapping[slide_id] = (video_slides[0], "video")
                    video_count += 1
                    self._log(f"Found video slide: {video_slides[0].name}")
                else:
                    self._log(
                        f"Warning: No slide file found for chapter {chapter_idx} (Slide {slide_id}), skipping"
                    )
                    skipped_count += 1

        self._log(
            f"Detailed breakdown: {image_count} images, {video_count} videos, {skipped_count} skipped"
        )
        return slide_mapping, image_count, video_count, skipped_count

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
        slide_mapping, image_count, video_count, skipped_count = self.validate_slide_files(
            input_path, json_data, video_name
        )

        return video_path, json_data, slide_mapping, image_count, video_count, skipped_count


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
        max_duration: Optional[int] = None,
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
            max_duration: Maximum video duration in seconds (for debugging)
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

        # Load speaker video with optional duration limit
        if max_duration is not None:
            speaker = ffmpeg.input(str(speaker_video), t=max_duration)
        else:
            speaker = ffmpeg.input(str(speaker_video))

        # Position mapping (no padding, directly in corners)
        # W and H in overlay refer to the main video (slides) dimensions
        # w and h refer to the overlay video (PiP) dimensions
        positions = {
            "top-right": {"x": "W-w", "y": "0"},
            "top-left": {"x": "0", "y": "0"},
            "bottom-right": {"x": "W-w", "y": "H-h"},
            "bottom-left": {"x": "0", "y": "H-h"},
        }

        # Scale PiP relative to the main video (slides) dimensions
        # Since scale2ref is deprecated and has issues, let's use a different approach
        # We'll probe the first slide to get its dimensions, then scale accordingly

        # Get dimensions of the first slide
        import subprocess
        import json as json_module

        # Get the first slide path from timeline
        first_slide_path = str(timeline[0][2])

        # Probe the slide to get dimensions
        probe_cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'json',
            first_slide_path
        ]

        try:
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
            probe_data = json_module.loads(probe_result.stdout)
            slide_width = probe_data['streams'][0]['width']
            slide_height = probe_data['streams'][0]['height']

            # Calculate target PiP width
            target_pip_width = int(slide_width * pip_scale)

            self._log(f"Slide dimensions: {slide_width}x{slide_height}")
            self._log(f"Target PiP width: {target_pip_width} (scale={pip_scale})")

            # Scale the PiP to the calculated width, maintaining aspect ratio
            pip = speaker.video.filter("scale", target_pip_width, -2)  # -2 maintains aspect ratio with even height

        except (subprocess.CalledProcessError, json_module.JSONDecodeError, KeyError) as e:
            self._log(f"Warning: Could not probe slide dimensions: {e}")
            self._log(f"Falling back to default scaling")
            # Fallback: assume 1920x1080 and scale accordingly
            target_pip_width = int(1920 * pip_scale)
            pip = speaker.video.filter("scale", target_pip_width, -2)

        # Overlay the scaled PiP on the slides
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

            # Configure FFmpeg output based on verbose mode
            if self.verbose:
                # Verbose mode: show all FFmpeg output
                ffmpeg.output(video, audio, output, **output_args).overwrite_output().run()
            else:
                # Non-verbose mode: show progress bar with tqdm
                import subprocess
                import sys
                import os
                import re
                from tqdm import tqdm

                cmd = (
                    ffmpeg.output(video, audio, output, **output_args).overwrite_output().compile()
                )

                # Calculate total duration from timeline
                total_duration = timeline[-1][1] if timeline else 0

                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=False,
                    bufsize=0,
                )

                # Create progress bar
                # Helper function to format seconds as MM:SS
                def format_time(seconds):
                    mins = int(seconds // 60)
                    secs = int(seconds % 60)
                    return f"{mins:02d}:{secs:02d}"

                pbar = tqdm(
                    total=total_duration,
                    desc="Encoding",
                    bar_format="{desc}: {percentage:3.0f}%|{bar}| {postfix} [{elapsed}<{remaining}]",
                )

                # Read stderr in real-time and update progress bar
                buffer = b""
                last_time = 0

                # Make stderr non-blocking on Unix systems
                if os.name != "nt":
                    import fcntl
                    flags = fcntl.fcntl(process.stderr, fcntl.F_GETFL)
                    fcntl.fcntl(process.stderr, fcntl.F_SETFL, flags | os.O_NONBLOCK)

                while True:
                    # Check if process has ended
                    if process.poll() is not None:
                        # Process finished - read any remaining data
                        try:
                            remaining = process.stderr.read()
                            if remaining:
                                buffer += remaining
                        except:
                            pass
                        break

                    # Try to read data (non-blocking on Unix)
                    try:
                        chunk = process.stderr.read(1024)
                        if chunk:
                            buffer += chunk
                    except (BlockingIOError, IOError):
                        # No data available right now, sleep briefly to avoid busy-waiting
                        import time
                        time.sleep(0.01)

                    # Process complete lines (ending with \r or \n)
                    while b"\r" in buffer or b"\n" in buffer:
                        if b"\r" in buffer:
                            idx = buffer.index(b"\r")
                        elif b"\n" in buffer:
                            idx = buffer.index(b"\n")

                        line = buffer[:idx].decode("utf-8", errors="ignore").strip()
                        buffer = buffer[idx + 1 :]

                        # Extract time and speed from FFmpeg progress line
                        if "time=" in line:
                            # Extract time (format: HH:MM:SS.ZZ)
                            time_match = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", line)
                            if time_match:
                                hours = int(time_match.group(1))
                                minutes = int(time_match.group(2))
                                seconds = float(time_match.group(3))
                                current_time = hours * 3600 + minutes * 60 + seconds

                                # Update progress bar
                                pbar.n = min(current_time, total_duration)

                                # Format current and total time as MM:SS
                                current_str = format_time(current_time)
                                total_str = format_time(total_duration)

                                # Extract and display speed
                                speed_match = re.search(r"speed=\s*(\S+)", line)
                                speed_str = ""
                                if speed_match:
                                    speed = speed_match.group(1)
                                    speed_str = f", speed={speed}"

                                pbar.set_postfix_str(f"{current_str}/{total_str}{speed_str}")

                                pbar.refresh()
                                last_time = current_time

                # Ensure progress bar reaches 100% before closing
                pbar.n = total_duration
                pbar.set_postfix_str(f"{format_time(total_duration)}/{format_time(total_duration)}, done")
                pbar.refresh()
                pbar.close()

                process.wait()
                if process.returncode != 0:
                    raise ffmpeg.Error("ffmpeg", "", "")

            self._log(f"Video generation complete: {output}")
            click.echo(f"✓ Successfully created: {output}")

        except ffmpeg.Error as e:
            if self.verbose and e.stderr:
                click.echo(e.stderr.decode(), err=True)
            raise ValidationError(f"FFmpeg error during video generation: {e}")


@click.command()
@click.argument("input", metavar="INPUT")
@click.option("--output", "-o", help="Output video filename (default: INPUT_NAME_slides.mp4)")
@click.option(
    "--keep-temp",
    is_flag=True,
    help="Keep temporary download folder (only for URLs). Note: automatically preserved on FFmpeg errors for debugging.",
)
@click.option(
    "--temp-dir",
    type=click.Path(),
    help="Use specific temporary directory for downloads (creates if doesn't exist, resumes if exists)",
)
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
    default="ultrafast",
    type=click.Choice(["ultrafast", "veryfast", "medium", "slow"], case_sensitive=False),
    help="Encoding preset (default: ultrafast). ultrafast=fast/lower quality, slow=slow/high quality.",
)
@click.option(
    "--crf",
    default=None,
    type=int,
    help="Quality override (0-51, lower is better). If not set, uses preset default.",
)
@click.option(
    "--max-duration",
    default=None,
    type=int,
    help="Maximum video duration in seconds (for debugging). If not set, uses full video length.",
)
@click.option(
    "--high-res-speaker",
    is_flag=True,
    help="Download high-resolution speaker video (useful for larger picture-in-picture). Default uses low-res for smaller file size.",
)
def main(
    input: str,
    output: Optional[str],
    keep_temp: bool,
    temp_dir: Optional[str],
    pip_scale: float,
    pip_position: str,
    verbose: bool,
    preset: str,
    crf: Optional[int],
    max_duration: Optional[int],
    high_res_speaker: bool,
):
    """
    Process yt-dlp content into presentation video.

    This tool can download from a URL or process already-downloaded content,
    creating a presentation-style video with slides, speaker audio, and picture-in-picture video.

    INPUT can be:
    - A YouTube/video URL: Will download with yt-dlp to a temporary folder
    - A local directory: Should contain yt-dlp downloaded files

    Downloaded/existing content should include:
    - Main speaker video: [title] [id].mp4
    - Metadata: [title] [id].info.json
    - Slide images: [title] [id].[slide_id].[ext]
    - Optional slide videos: [title] - Slide [slide_id] [id-slide_id].mp4
    """

    # Check if input is a URL or directory
    parsed = urlparse(input)
    is_url = bool(parsed.scheme and parsed.netloc)

    created_temp_dir = False
    input_dir = input

    if is_url:
        # Download from URL to temporary directory
        if temp_dir:
            # Use specified temp directory (create if doesn't exist, resume if exists)
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
                created_temp_dir = True
                if verbose:
                    click.echo(f"Created temporary directory: {temp_dir}")
            else:
                if verbose:
                    click.echo(f"Resuming download in existing directory: {temp_dir}")
        else:
            # Create new temp directory with random name
            temp_dir = tempfile.mkdtemp(prefix="mlconf-dlp-", dir=".")
            created_temp_dir = True

        downloader = VideoDownloader(verbose=verbose)

        try:
            input_dir = downloader.download_video(input, temp_dir, high_res_speaker=high_res_speaker)
        except ValidationError as e:
            # Clean up temp dir on download failure (only if we created it)
            if created_temp_dir and temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)
    else:
        # Validate that directory exists
        if not os.path.exists(input):
            click.echo(f"Error: Directory does not exist: {input}", err=True)
            sys.exit(1)
        if not os.path.isdir(input):
            click.echo(f"Error: Input path is not a directory: {input}", err=True)
            sys.exit(1)

    # Validate pip_scale
    if not 0 < pip_scale <= 1:
        click.echo("Error: --pip-scale must be between 0 and 1", err=True)
        sys.exit(1)

    # Map preset to default CRF if not overridden
    preset_crf_map = {
        "ultrafast": 28,
        "veryfast": 23,
        "medium": 23,
        "slow": 18,
    }

    if crf is None:
        crf = preset_crf_map[preset]
        if verbose:
            click.echo(f"Using preset '{preset}' with default CRF {crf}")
    else:
        # Validate custom crf
        if not 0 <= crf <= 51:
            click.echo("Error: --crf must be between 0 and 51", err=True)
            sys.exit(1)
        if verbose:
            click.echo(f"Using preset '{preset}' with custom CRF {crf}")

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
        video_path, json_data, slide_mapping, image_count, video_count, skipped_count = (
            validator.validate_all(input_dir)
        )
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

    # Apply max_duration limit if specified (for debugging)
    if max_duration is not None:
        original_length = len(timeline)
        # Keep only slides that start before max_duration
        timeline = [
            (start, min(end, max_duration), path, slide_type)
            for start, end, path, slide_type in timeline
            if start < max_duration
        ]
        if verbose:
            click.echo(
                f"Applied max_duration limit: kept {len(timeline)}/{original_length} slides (up to {max_duration}s)"
            )

    # Generate output filename if not provided
    # Save to current directory (not temp directory) to avoid deletion on cleanup
    if not output:
        output = f"{video_path.stem}_slides.mp4"

    # Calculate statistics from timeline
    total_slides = len(timeline)
    total_duration = timeline[-1][1] if timeline else 0  # End time of last slide

    # Display summary (always shown, not just in verbose mode)
    click.echo("\n" + "=" * 60)
    click.echo("Video Generation Summary")
    click.echo("=" * 60)
    click.echo(f"Total slides found: {total_slides}")
    click.echo(f"  - Static slides: {image_count}")
    click.echo(f"  - Video slides: {video_count}")
    click.echo(f"  - Skipped chapters: {skipped_count}")

    # Format duration as HH:MM:SS
    hours = int(total_duration // 3600)
    minutes = int((total_duration % 3600) // 60)
    seconds = int(total_duration % 60)
    duration_str = (
        f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours > 0 else f"{minutes:02d}:{seconds:02d}"
    )

    click.echo(f"Total video length: {duration_str}")
    click.echo(f"Output file: {output}")
    click.echo(f"Encoding preset: {preset} (CRF {crf})")
    click.echo("=" * 60 + "\n")

    # Step 3: Generate video
    if verbose:
        click.echo("Step 3: Generating video")
        click.echo("=" * 60)

    # Track if there was an ffmpeg error (to preserve temp dir for debugging)
    ffmpeg_error = False

    try:
        generator.process(
            timeline=timeline,
            speaker_video=video_path,
            output=output,
            pip_scale=pip_scale,
            pip_position=pip_position,
            preset=preset,
            crf=crf,
            max_duration=max_duration,
        )
    except ValidationError as e:
        click.echo(f"Error: {e}", err=True)
        # Check if this is an FFmpeg error
        if "FFmpeg error" in str(e):
            ffmpeg_error = True
            click.echo(f"\n⚠ FFmpeg error detected - temporary directory preserved for debugging: {temp_dir}")
        # Clean up temp dir on error (only if we created it and it's not an ffmpeg error)
        if created_temp_dir and temp_dir and os.path.exists(temp_dir) and not ffmpeg_error:
            shutil.rmtree(temp_dir)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        if verbose:
            import traceback

            traceback.print_exc()
        # Clean up temp dir on error (only if we created it)
        if created_temp_dir and temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        sys.exit(1)

    # Cleanup or preserve temporary directory
    if temp_dir:
        # If user specified --temp-dir OR --keep-temp OR resumed from existing dir OR ffmpeg error, keep it
        should_keep = keep_temp or not created_temp_dir or ffmpeg_error

        if should_keep:
            click.echo(f"\n✓ Downloaded files kept in: {temp_dir}")
        else:
            # Only auto-cleanup if we created a new random temp dir and user didn't ask to keep
            shutil.rmtree(temp_dir)
            if verbose:
                click.echo(f"\nCleaned up temporary directory: {temp_dir}")


if __name__ == "__main__":
    main()
