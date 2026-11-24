"""Show and remove the metadata of videos and music ("Remove metadata only").

Videos from phones and cameras record where they were filmed (GPS), the phone model,
dates and the software; action cameras add a GPS log as a separate data track. The
cleaned copy keeps every picture, sound and subtitle track bit for bit (FFmpeg copies
them, nothing is re-encoded), checked by comparing every packet before saving. Kept:
the title and, for music, the song tags (artist, album, track, cover …), chapters, and
each track's language and name ("English", "Commentary").

Files can be several GB, so nothing is read into memory: FFmpeg works on the files.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from . import formats
from .converters import ConversionError
from .converters.media import (
    AUDIO_SOURCES,
    MUSIC_TAGS,
    VIDEO_TAGS,
    MediaInfo,
    _input,
    _no_window,
    find_ffmpeg,
    probe,
    read_tags,
    write_tags,
)
from .engine import TEMP_PREFIX

# Formats whose tracks FFmpeg copies into the same kind of file reliably.
CLEANABLE = (
    "mp4", "mov", "mkv", "webm", "avi", "3gp",
    "mp3", "m4a", "wav", "flac", "ogg", "opus", "aiff",
)  # fmt: skip

# Technical tags that say nothing about the user (not listed as "found").
_TECHNICAL = {
    "major_brand", "minor_version", "compatible_brands", "encoder", "handler_name",
    "vendor_id", "language", "duration", "bps", "number_of_frames", "number_of_bytes",
    "_statistics_tags", "_statistics_writing_app", "_statistics_writing_date_utc",
    "filename", "mimetype", "title",
}  # fmt: skip
_LABELS = [  # (words in the tag name, what the user is shown)
    (("location", "iso6709", "gps", "xyz"), "Location (GPS)"),
    (("make", "model", "manufacturer", "camera", "device"), "Camera or phone"),
    (("creation_time", "date", "time"), "Date"),
    (("software", "encoded_by", "tool", "writing_app"), "Software"),
    (("author", "artist", "copyright", "owner", "publisher"), "Author"),
    (("comment", "description", "synopsis", "keywords"), "Comment"),
]


def _ffmpeg() -> Path:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise ConversionError(
            "Video and audio need FFmpeg, and FFmpeg is missing. Install Azoth Converter again."
        )
    return ffmpeg


def _kept_tags(fmt: str) -> set[str]:
    return MUSIC_TAGS if fmt in AUDIO_SOURCES else VIDEO_TAGS


def _label(key: str) -> str:
    for words, text in _LABELS:
        if any(w in key for w in words):
            return text
    return key.replace("_", " ").replace(".", " ").strip().capitalize()


def _base_key(key: str) -> str:
    """ "BPS-eng" → "bps"; "com.apple.quicktime.model" stays (lower case)."""
    key = key.lower()
    return key.rsplit("-", 1)[0] if key.rsplit("-", 1)[-1].isalpha() and "-" in key else key


def findings(fmt: str, tags: dict[str, str], info: MediaInfo) -> list[tuple[str, str]]:
    """What the cleaned copy won't contain: (what, value) pairs, for "Show metadata"."""
    kept = _kept_tags(fmt)
    found: list[tuple[str, str]] = []
    for key, value in tags.items():
        if key in kept or _base_key(key) in _TECHNICAL or not value.strip():
            continue
        found.append((_label(key), value.strip()[:80]))
    for stream in info.streams:
        for key, value in stream.tags.items():
            if _base_key(key) in _TECHNICAL or not value.strip():
                continue
            if stream.kind == "audio" and key.lower() in kept:
                continue  # Ogg/Opus keep song tags on the track: they stay
            if stream.cover and key.lower() == "comment":
                continue  # the cover's picture type ("Front cover"), not a comment
            found.append((_label(key), value.strip()[:80]))
    if info.of("data"):
        found.append(("Data track", "e.g. a GPS log from an action camera"))
    unique: list[tuple[str, str]] = []
    for item in found:
        if item not in unique:
            unique.append(item)
    return unique


def inspect(path: Path, fmt: str) -> list[tuple[str, str]]:
    ffmpeg = _ffmpeg()
    return findings(fmt, read_tags(ffmpeg, path), probe(ffmpeg, path))


def _stream_hashes(ffmpeg: Path, path: Path) -> list[str]:
    """A checksum of every picture, sound and subtitle packet, track by track."""
    run = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-nostdin", "-v", "error", *_input(path)]
        + ["-map", "0", "-map", "-0:d?", "-map", "-0:t?", "-c", "copy"]
        + ["-f", "streamhash", "-hash", "md5", "-"],
        capture_output=True,
        text=True,
        creationflags=_no_window(),
    )
    if run.returncode != 0:
        raise ConversionError("Cannot read this file. Possibly, the file is damaged.")
    return [line.split(",", 2)[-1] for line in run.stdout.splitlines() if "=" in line]


def clean(source: Path, target: Path, fmt: str) -> list[tuple[str, str]]:
    """Save ``target``: ``source`` without its metadata, every track copied unchanged.
    Returns what was removed. Nothing is saved if a track would change."""
    ffmpeg = _ffmpeg()
    info = probe(ffmpeg, source)
    tags = read_tags(ffmpeg, source)
    if fmt in AUDIO_SOURCES and info.of("audio"):
        tags = {**info.of("audio")[0].tags, **tags}  # Ogg/Opus: song tags on the track
    removed = findings(fmt, tags, info)
    kept = {k: v for k, v in tags.items() if k in _kept_tags(fmt)}
    with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as tmp:  # deleted afterwards
        work = Path(tmp)
        meta = work / "tags.txt"
        write_tags(kept, meta)
        result = work / f"clean{target.suffix}"
        cmd = [str(ffmpeg), "-hide_banner", "-nostdin", "-v", "error", "-n", *_input(source)]
        cmd += ["-f", "ffmetadata", *_input(meta)]
        cmd += ["-map", "0", "-map", "-0:d?", "-c", "copy"]  # no GPS data tracks
        cmd += ["-map_metadata", "1", "-map_metadata:s", "-1"]
        out = 0
        for stream in info.streams:
            if stream.kind == "data":
                continue
            for key in ("language", "title", "filename", "mimetype"):
                value = stream.tags.get(key, "")
                if key == "title" and stream.kind == "video":
                    continue  # track names are kept for sound and subtitles only
                if value and value != "und":
                    cmd += [f"-metadata:s:{out}", f"{key}={value}"]
            out += 1
        if fmt == "mp3":
            cmd += ["-id3v2_version", "3"]  # tags Windows Explorer shows
        cmd.append(str(result))
        run = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace", creationflags=_no_window()
        )
        if run.returncode != 0 or not result.is_file():
            detail = run.stderr.strip().splitlines()[-1][:200] if run.stderr.strip() else ""
            raise ConversionError(
                "Cannot remove the metadata from this file. Possibly, the file is damaged."
                + (f" (FFmpeg: {detail})" if detail else "")
            )
        if _stream_hashes(ffmpeg, result) != _stream_hashes(ffmpeg, source):
            raise ConversionError(
                "Azoth Converter cannot remove the metadata without a change to the video "
                "or sound, so it did not save a file."
            )
        if formats.detect(result) is None:
            raise ConversionError(
                "Azoth Converter cannot check the cleaned copy, so it did not save a file."
            )
        shutil.move(str(result), target)
    return removed
