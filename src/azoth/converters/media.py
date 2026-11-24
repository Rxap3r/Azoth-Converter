"""Video and audio conversions with FFmpeg.

Quality first: every stream (picture, sound, subtitles) the target can hold is
copied unchanged ("remuxing": MKV → MP4 takes seconds and loses nothing). Only what
the target can't hold is re-encoded, with the settings in ``quality.py``; lossless
sound stays lossless where the target allows it (FLAC → M4A becomes Apple Lossless).

Privacy: FFmpeg may only open local files (``-protocol_whitelist file``), so a
playlist or a crafted file can't make it reach the network. Phone videos carry the
place they were filmed (GPS), the phone model and dates in their metadata: these are
removed like photo metadata. Kept are titles, and for music the usual song tags
(artist, album, track …), so a music library stays sorted. GoPro-style data tracks
(GPS logs) are left out.

FFmpeg comes with the app on Windows (``resources/ffmpeg``, fetched by
``packaging/fetch_ffmpeg.py``); elsewhere the system's ``ffmpeg`` is used.
"""

from __future__ import annotations

import functools
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .. import quality
from .base import ConversionContext, ConversionError, Converter

BUNDLED = Path(__file__).resolve().parent.parent / "resources" / "ffmpeg"

VIDEO_SOURCES = ("mp4", "mov", "mkv", "webm", "avi", "wmv", "mpg", "mts", "flv", "3gp")
VIDEO_TARGETS = ("mp4", "mov", "mkv", "webm", "avi", "gif")
AUDIO_SOURCES = ("mp3", "m4a", "wav", "flac", "ogg", "opus", "wma", "aiff", "aac")
AUDIO_TARGETS = ("mp3", "m4a", "wav", "flac", "ogg", "opus")
GIF_TO_VIDEO = ("mp4", "webm")  # animated GIF → a much smaller video

LOSSLESS_AUDIO = {"flac", "alac", "wavpack", "ape", "tta", "truehd", "mlp"}
TEXT_SUBTITLES = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}

# Codecs each target holds as they are (copied, not re-encoded).
VIDEO_COPY = {
    "mp4": {"h264", "hevc", "av1", "mpeg4"},
    "mov": {"h264", "hevc", "prores", "mjpeg", "mpeg4"},
    "webm": {"vp8", "vp9", "av1"},
    "avi": {"mpeg4", "msmpeg4v3", "mjpeg"},  # what old players can play
}
AUDIO_COPY = {
    "mp4": {"aac", "mp3", "ac3", "eac3", "alac"},
    "mov": {"aac", "mp3", "ac3", "eac3", "alac", "pcm_s16le", "pcm_s24le"},
    "webm": {"opus", "vorbis"},
    "avi": {"mp3", "ac3", "pcm_s16le"},
    "mp3": {"mp3"},
    "m4a": {"aac", "alac"},
    "wav": {"pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_u8"},
    "flac": {"flac"},
    "ogg": {"vorbis"},
    "opus": {"opus"},
}
COVER_TARGETS = {"mp3", "m4a", "flac"}  # can hold an album cover
COVER_CODECS = {"mjpeg", "png"}

# Global tags that are kept. Everything else (GPS location, phone make and model,
# software, dates, comments …) is removed.
VIDEO_TAGS = {"title"}
MUSIC_TAGS = {
    "title", "artist", "album", "album_artist", "albumartist", "date", "year", "track",
    "tracknumber", "disc", "discnumber", "genre", "composer", "performer", "copyright",
    "publisher", "lyrics", "compilation", "bpm", "tbpm",
}  # fmt: skip

HDR_TRANSFERS = ("smpte2084", "arib-std-b67")  # PQ (HDR10, Dolby Vision) and HLG (iPhone)
_STREAM = re.compile(
    r"Stream #0:(\d+)(?:\[\w+\])?(?:\((\w+)\))?: (Video|Audio|Subtitle|Data|Attachment): (\w+)(.*)"
)
_TAG = re.compile(r"^(\s*)(\S[^:]*?)?\s*: (.*)$")
_DURATION = re.compile(r"Duration: (\d+):(\d\d):(\d\d(?:\.\d+)?)")
_SAMPLE_FMT = re.compile(r"^(u8|s16|s32|s64|flt|dbl)p?(?: \((\d+) bit\))?(?= |$)")
_FPS = re.compile(r"([\d.]+) fps")


def find_ffmpeg() -> Path | None:
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    if (BUNDLED / name).is_file():
        return BUNDLED / name
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _input(path: Path) -> list[str]:
    # "file:" so a name like "a:b.mp4" is never read as a network address; only local
    # files may be opened, also by playlists or other files the input refers to.
    return ["-protocol_whitelist", "file", "-i", f"file:{path}"]


# --- What's inside the file -----------------------------------------------------------


@dataclass
class Stream:
    index: int
    kind: str  # "video", "audio", "subtitle", "data", "attachment"
    codec: str
    cover: bool = False  # an album cover or thumbnail, not real video
    bits: int = 0  # audio sample size (16, 24, 32), 0 if unknown
    float_samples: bool = False
    fps: float = 0.0
    hdr: bool = False  # HDR video (e.g. from an iPhone): needs a colour conversion for H.264
    tags: dict[str, str] = field(default_factory=dict)  # this track's own tags

    @property
    def language(self) -> str:
        lang = self.tags.get("language", "")
        return "" if lang in ("", "und") else lang


@dataclass
class MediaInfo:
    duration: float | None
    streams: list[Stream] = field(default_factory=list)

    def of(self, kind: str) -> list[Stream]:
        return [s for s in self.streams if s.kind == kind and not s.cover]

    @property
    def covers(self) -> list[Stream]:
        return [s for s in self.streams if s.cover and s.codec in COVER_CODECS]


def parse_info(text: str) -> MediaInfo:
    """Read FFmpeg's description of an input file (what ``ffmpeg -i file`` prints)."""
    duration = None
    if m := _DURATION.search(text):
        duration = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    info = MediaInfo(duration)
    stream: Stream | None = None
    tag_indent = -1  # indentation of the current track's "Metadata:" line
    last_key = ""
    for line in text.splitlines():
        if line.lstrip().startswith("Input #1"):
            break
        indent = len(line) - len(line.lstrip())
        if stream is not None and line.strip() == "Metadata:":
            tag_indent = indent
            continue
        if stream is not None and tag_indent >= 0 and indent > tag_indent:
            if t := _TAG.match(line):
                key = (t[2] or "").strip().lower()
                if key:
                    last_key = key
                    stream.tags[key] = t[3]
                elif last_key:  # a value over several lines
                    stream.tags[last_key] += "\n" + t[3]
            continue
        tag_indent = -1
        m = _STREAM.search(line)
        if not m:
            stream = None if indent <= 2 else stream
            continue
        stream = Stream(int(m[1]), m[3].lower(), m[4], cover="(attached pic)" in line)
        stream.hdr = any(t in m[5] for t in HDR_TRANSFERS)
        if m[2]:
            stream.tags["language"] = m[2]
        rest = [part.strip() for part in m[5].split(",")]
        for part in rest:
            if s := _SAMPLE_FMT.match(part):
                bits = {"u8": 8, "s16": 16, "s32": 32, "s64": 64, "flt": 32, "dbl": 64}
                stream.bits = int(s[2]) if s[2] else bits[s[1]]
                stream.float_samples = s[1] in ("flt", "dbl")
            if f := _FPS.search(part):
                stream.fps = float(f[1])
        info.streams.append(stream)
    return info


def probe(ffmpeg: Path, src: Path) -> MediaInfo:
    run = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-nostdin", *_input(src)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_no_window(),
        timeout=120,
    )
    info = parse_info(run.stderr)
    if not info.streams:
        raise ConversionError(
            "Cannot read this file as a video or sound file. Possibly, the file is "
            "damaged or incomplete, or its name shows the wrong format."
        )
    return info


def read_tags(ffmpeg: Path, src: Path) -> dict[str, str]:
    """The file's global tags (title, artist …), lower-case names."""
    run = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-nostdin", "-v", "error", *_input(src)]
        + ["-f", "ffmetadata", "-"],
        capture_output=True,
        creationflags=_no_window(),
        timeout=120,
    )
    text = run.stdout.decode("utf-8", errors="replace")
    tags: dict[str, str] = {}
    for line in _logical_lines(text):
        if line.startswith("["):
            break  # chapters and streams follow; they're copied by FFmpeg itself
        if not line or line.startswith((";", "#")):
            continue
        key, sep, value = _split_unescaped(line)
        if sep:
            tags[key.strip().lower()] = value
    return tags


def _logical_lines(text: str) -> list[str]:
    """ffmetadata lines; a backslash before a line break continues the value."""
    lines, current = [], ""
    for raw in text.split("\n"):
        current += raw
        if current.endswith("\\") and not current.endswith("\\\\"):
            current = current[:-1] + "\n"
            continue
        lines.append(current)
        current = ""
    if current:
        lines.append(current)
    return lines


def _split_unescaped(line: str) -> tuple[str, str, str]:
    key, value, escaped, in_value = [], [], False, False
    for ch in line:
        if escaped:
            (value if in_value else key).append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == "=" and not in_value:
            in_value = True
        else:
            (value if in_value else key).append(ch)
    return "".join(key), "=" if in_value else "", "".join(value)


def _escape(text: str) -> str:
    return re.sub(r"([=;#\\\n])", r"\\\1", text)


def write_tags(tags: dict[str, str], path: Path) -> None:
    lines = [";FFMETADATA1"] + [f"{_escape(k)}={_escape(v)}" for k, v in tags.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- Choosing how each stream is written ----------------------------------------------


def _audio_encoder(target: str, stream: Stream, out: int) -> list[str]:
    """Options that copy or encode audio stream number ``out`` of the result."""
    a = f":a:{out}"
    if stream.codec in AUDIO_COPY.get(target, set()):
        return [f"-c{a}", "copy"]
    lossless = stream.codec in LOSSLESS_AUDIO or stream.codec.startswith("pcm_")
    if target in ("mp4", "mov", "m4a"):
        if lossless:
            return [f"-c{a}", "alac"]
        return [f"-c{a}", "aac", f"-b{a}", f"{quality.AAC_KBPS}k"]
    if target in ("webm", "opus"):
        return [f"-c{a}", "libopus", f"-b{a}", f"{quality.OPUS_KBPS}k"]
    if target == "ogg":
        return [f"-c{a}", "libvorbis", f"-q{a}", str(quality.VORBIS_QUALITY)]
    if target == "mp3":
        return [f"-c{a}", "libmp3lame", f"-q{a}", str(quality.MP3_VBR)]
    if target == "avi":
        return [f"-c{a}", "libmp3lame", f"-b{a}", f"{quality.AVI_MP3_KBPS}k"]
    deep = lossless and not stream.float_samples and stream.bits > 16
    if target == "wav":
        codec = ("pcm_s24le" if stream.bits == 24 else "pcm_s32le") if deep else "pcm_s16le"
        return [f"-c{a}", codec]
    if target == "flac":
        return [f"-c{a}", "flac", f"-sample_fmt{a}", "s32" if deep else "s16"]
    raise ConversionError(f"Cannot write sound as {target.upper()}.")


def _video_encoder(target: str, stream: Stream) -> list[str]:
    if stream.codec in VIDEO_COPY.get(target, set()):
        args = ["-c:v:0", "copy"]
        if stream.codec == "hevc" and target in ("mp4", "mov"):
            args += ["-tag:v:0", "hvc1"]  # so Apple devices and Windows play it
        return args
    if target == "webm":
        return [
            "-c:v:0", "libvpx-vp9", "-crf", str(quality.VP9_CRF), "-b:v", "0",
            "-row-mt", "1", "-deadline", "good", "-cpu-used", "4", "-pix_fmt", "yuv420p",
        ]  # fmt: skip
    if target == "avi":
        return ["-c:v:0", "mpeg4", "-q:v", "2", "-tag:v", "XVID"]
    crf = min(quality.VIDEO_CRF, quality.MAX_VIDEO_CRF)
    return [
        "-c:v:0", "libx264", "-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",  # H.264 needs even sizes
    ]  # fmt: skip


def _language(stream: Stream, letter: str, n: int) -> list[str]:
    """Keeps a track's language (so players pick the right sound and subtitles)."""
    lang = re.sub(r"[^A-Za-z-]", "", stream.language)[:12]
    return [f"-metadata:s:{letter}:{n}", f"language={lang}"] if lang else []


def plan_video(target: str, info: MediaInfo) -> list[str]:
    """Output options for a video target (stream selection, codecs)."""
    videos = info.of("video")
    if not videos:
        raise ConversionError("This file has no picture, only sound. Select a sound format.")
    if target == "mkv":  # Matroska holds everything: copy every track unchanged
        args = []
        for kind, letter in (("video", "v"), ("audio", "a"), ("subtitle", "s")):
            for n, s in enumerate(info.of(kind)):
                args += ["-map", f"0:{s.index}", *_language(s, letter, n)]
        return [*args, "-map", "0:t?", "-c", "copy"]
    args = ["-map", f"0:{videos[0].index}"] + _video_encoder(target, videos[0])
    for n, a in enumerate(info.of("audio")):
        args += ["-map", f"0:{a.index}", *_language(a, "a", n)] + _audio_encoder(target, a, n)
    if target in ("mp4", "mov"):
        text = [s for s in info.of("subtitle") if s.codec in TEXT_SUBTITLES]
        for n, s in enumerate(text):
            args += ["-map", f"0:{s.index}", f"-c:s:{n}", "mov_text", *_language(s, "s", n)]
        args += ["-movflags", "+faststart"]  # starts playing before fully loaded
    return args


def plan_gif(info: MediaInfo) -> list[str]:
    videos = info.of("video")
    if not videos:
        raise ConversionError("This file has no picture, only sound.")
    fps = min(videos[0].fps or quality.GIF_MAX_FPS, quality.GIF_MAX_FPS)
    graph = (
        f"[0:{videos[0].index}]fps={fps:g},split[a][b];"
        "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a"
    )
    return ["-filter_complex", graph, "-loop", "0"]


def plan_audio(target: str, info: MediaInfo) -> list[str]:
    sounds = info.of("audio")
    if not sounds:
        raise ConversionError("This video has no sound. There is no audio to save.")
    first = sounds[0]
    args = ["-map", f"0:{first.index}"] + _audio_encoder(target, first, 0)
    if target in COVER_TARGETS and info.covers:
        cover = info.covers[0]
        args += ["-map", f"0:{cover.index}", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
    if target == "mp3":
        args += ["-id3v2_version", "3"]  # tags Windows Explorer and old players show
    if target == "m4a":
        args += ["-movflags", "+faststart"]
    return args


def plan_shrink(level: str, info: MediaInfo, tonemap: bool = True) -> list[str]:
    """Output options for "Make smaller": H.264 + AAC in MP4, the shorter side at most the
    level's size, at most 30 frames per second. HDR becomes normal colours (``tonemap``:
    FFmpeg has the "zscale" filter; without it the colours would look pale)."""
    if level not in quality.SHRINK_LEVELS:
        raise ConversionError(f"“{level}” is not a known size for a smaller video.")
    videos = info.of("video")
    if not videos:
        raise ConversionError("This file has no picture, only sound.")
    video = videos[0]
    side, crf = quality.SHRINK_LEVELS[level]
    crf = min(crf, quality.MAX_SHRINK_CRF)
    filters = []
    if video.fps > quality.SHRINK_MAX_FPS + 0.5:
        filters.append(f"fps={quality.SHRINK_MAX_FPS}")
    # The shorter side becomes at most ``side`` (portrait videos too), never bigger; even
    # numbers, as H.264 needs them. Phone videos are already turned upright here.
    # The quotes keep the commas inside the expressions.
    width = f"if(gte(iw,ih),-2,trunc(min(iw,{side})/2)*2)"
    height = f"if(gte(iw,ih),trunc(min(ih,{side})/2)*2,-2)"
    filters.append(f"scale='{width}':'{height}'")
    colour = []
    if video.hdr and tonemap:
        filters.append(
            "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
            "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv"
        )
        colour = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    filters.append("format=yuv420p")
    args = [
        "-map", f"0:{video.index}", "-c:v:0", "libx264", "-crf", str(crf),
        "-preset", "medium", "-vf", ",".join(filters), *colour,
    ]  # fmt: skip
    for n, a in enumerate(info.of("audio")):
        args += ["-map", f"0:{a.index}", *_language(a, "a", n)]
        if a.codec == "aac":
            args += [f"-c:a:{n}", "copy"]  # already small; copying loses nothing
        else:
            args += [f"-c:a:{n}", "aac", f"-b:a:{n}", f"{quality.MIN_AUDIO_KBPS}k"]
    text = [s for s in info.of("subtitle") if s.codec in TEXT_SUBTITLES]
    for n, s in enumerate(text):
        args += ["-map", f"0:{s.index}", f"-c:s:{n}", "mov_text", *_language(s, "s", n)]
    return args + ["-movflags", "+faststart"]


@functools.cache
def has_filter(ffmpeg: Path, name: str) -> bool:
    try:
        run = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=30, creationflags=_no_window(),
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return False
    return any(line.split()[1:2] == [name] for line in run.stdout.splitlines())


def plan(src: str, target: str, info: MediaInfo) -> list[str]:
    if target == "gif":
        return plan_gif(info)
    if target in AUDIO_TARGETS:
        return plan_audio(target, info)
    return plan_video(target, info)


# --- The converter --------------------------------------------------------------------


class MediaConverter(Converter):
    id = "ffmpeg"
    label = "FFmpeg"
    priority = 10

    def __init__(self) -> None:
        self._ffmpeg: Path | None = None
        self._looked = False

    @property
    def ffmpeg(self) -> Path | None:
        if not self._looked:
            self._ffmpeg = find_ffmpeg()
            self._looked = True
        return self._ffmpeg

    def is_available(self) -> bool:
        return self.ffmpeg is not None

    def unavailable_reason(self) -> str:
        return (
            "Video and audio conversions need FFmpeg, and FFmpeg is missing. Install Azoth "
            "Converter again."
        )

    def capabilities(self) -> Iterable[tuple[str, str]]:
        for src in VIDEO_SOURCES:
            for dst in VIDEO_TARGETS + AUDIO_TARGETS:
                if dst != src:
                    yield src, dst
        for src in AUDIO_SOURCES:
            for dst in AUDIO_TARGETS:
                if dst != src:
                    yield src, dst
        for dst in GIF_TO_VIDEO:
            yield "gif", dst

    def supports_shrink(self, src: str) -> bool:
        return src in VIDEO_SOURCES

    def first_only(self, src: str, dst: str) -> bool:
        return src == "gif"  # no PNG → GIF → MP4 "videos" of a single picture

    def final_only(self, src: str, dst: str) -> bool:
        return dst == "gif"  # no video → GIF → PNG (only the first frame)

    def quality_note(self, src: str, dst: str) -> str | None:
        if dst == "gif":
            return (
                f"GIF has only 256 colours and at most {quality.GIF_MAX_FPS} frames per "
                "second here, without sound. Best for short clips."
            )
        if src == "gif":
            return None
        if dst == "mkv":
            return "Every picture, sound and subtitle track is copied unchanged."
        if dst in LOSSY_WORDS:
            return (
                "Tracks the new format can hold are copied unchanged; the others are "
                f"re-encoded at high quality ({LOSSY_WORDS[dst]})."
            )
        return None

    def convert(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        ffmpeg = self.ffmpeg
        if ffmpeg is None:
            raise ConversionError(self.unavailable_reason())
        from .. import formats

        source = formats.detect(src)
        target = dst.suffix.lower().lstrip(".")
        target = formats.get(target).id
        info = probe(ffmpeg, src)
        shrink = ctx.option("shrink", None)
        if shrink:
            if target != "mp4":
                raise ConversionError("Azoth Converter always saves a smaller video as MP4.")
            output = plan_shrink(shrink, info, has_filter(ffmpeg, "zscale"))
        else:
            output = plan(source.id if source else "", target, info)

        cmd = [str(ffmpeg), "-hide_banner", "-nostdin", "-n", "-fflags", "+genpts", *_input(src)]
        if ctx.option("keep_metadata", False):  # the user asked to keep everything
            cmd += output + ["-progress", "pipe:1", "-nostats", str(dst)]
            _run(cmd, info.duration, ctx)
            return _smaller(src, dst) if shrink else _checked(dst)
        tags = read_tags(ffmpeg, src) if target != "gif" else {}
        keep = MUSIC_TAGS if target in AUDIO_TARGETS else VIDEO_TAGS
        if target in AUDIO_TARGETS and info.of("audio"):
            # Ogg and Opus keep song tags on the sound track, not on the file.
            tags = {**info.of("audio")[0].tags, **tags}
        meta = ctx.work_dir / "tags.txt"
        write_tags({k: v for k, v in tags.items() if k in keep}, meta)

        cmd += ["-f", "ffmetadata", *_input(meta)]
        # Only the kept tags; no track tags except each track's language; chapters stay.
        cmd += ["-map_metadata", "1", "-map_metadata:s", "-1"]
        cmd += output
        cmd += ["-progress", "pipe:1", "-nostats", str(dst)]
        _run(cmd, info.duration, ctx)
        return _smaller(src, dst) if shrink else _checked(dst)


def _smaller(src: Path, dst: Path) -> list[Path]:
    """ "Make smaller" result, only if it really is smaller than the original."""
    result = _checked(dst)
    if dst.stat().st_size >= src.stat().st_size:
        dst.unlink()
        raise ConversionError(
            "This video is already small. A smaller copy does not save space, so "
            "Azoth Converter did not save a file."
        )
    return result


def _checked(dst: Path) -> list[Path]:
    if not dst.is_file() or dst.stat().st_size == 0:
        raise ConversionError("FFmpeg did not make a file.")
    return [dst]


LOSSY_WORDS = {
    "mp3": "MP3 V0, about 245 kbit/s",
    "ogg": "Vorbis, about 192 kbit/s",
    "opus": f"Opus {quality.OPUS_KBPS} kbit/s",
    "webm": f"VP9 and Opus {quality.OPUS_KBPS} kbit/s",
    "avi": "MPEG-4 and MP3 320 kbit/s",
    "m4a": f"AAC {quality.AAC_KBPS} kbit/s, or Apple Lossless for lossless sound",
    "mp4": f"H.264 and AAC {quality.AAC_KBPS} kbit/s",
    "mov": f"H.264 and AAC {quality.AAC_KBPS} kbit/s",
}


def _run(cmd: list[str], duration: float | None, ctx: ConversionContext) -> None:
    log = ctx.work_dir / "ffmpeg.log"
    with log.open("wb") as err:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=err,
            stdin=subprocess.DEVNULL,
            creationflags=_no_window(),
        )
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                if ctx.cancel_event.is_set():
                    break
                line = raw.decode("ascii", errors="replace").strip()
                if line.startswith("out_time_us=") and duration:
                    try:
                        done = int(line.split("=", 1)[1]) / 1_000_000
                    except ValueError:
                        continue
                    ctx.progress(min(done / duration, 0.99), _clock(done, duration))
        finally:
            if ctx.cancel_event.is_set() and proc.poll() is None:
                proc.kill()
            proc.wait()
    ctx.check_cancelled()
    if proc.returncode != 0:
        detail = _last_error(log.read_text(encoding="utf-8", errors="replace"))
        raise ConversionError(
            "Cannot convert the file. Possibly, the file is damaged or uses an unusual "
            "format." + (f" (FFmpeg: {detail})" if detail else "")
        )


def _clock(done: float, total: float) -> str:
    def mmss(t: float) -> str:
        t = max(0, int(t))
        return f"{t // 60}:{t % 60:02d}"

    return f"{mmss(done)} of {mmss(total)}"


def _last_error(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in reversed(lines):
        if "error" in line.lower() or "invalid" in line.lower():
            return line[:200]
    return lines[-1][:200] if lines else ""
