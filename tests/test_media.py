"""Video and audio with FFmpeg: copies where possible, privacy, tags, errors."""

import subprocess
import threading
from pathlib import Path

import pytest

from azoth import formats
from azoth.converters import ConversionCancelled, ConversionError
from azoth.converters.media import _input, find_ffmpeg, parse_info
from azoth.engine import Engine

FFMPEG = find_ffmpeg()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg isn't installed")

VIDEO = ["-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=1"]
SOUND = ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"]


def ffmpeg(*args: str) -> str:
    run = subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", *args], capture_output=True, text=True, check=True
    )
    return run.stdout


def make(path, *args):
    ffmpeg(*args, str(path))
    return path


def tags(path) -> str:
    """Everything FFmpeg says about the file: its tags and every track's tags."""
    return subprocess.run(
        [str(FFMPEG), "-hide_banner", "-i", str(path)], capture_output=True, text=True
    ).stderr.replace(" ", "")


def packets(path, stream: str) -> str:
    """A checksum of the stream's compressed data: equal means copied unchanged."""
    return ffmpeg("-i", str(path), "-map", stream, "-c", "copy", "-f", "md5", "-")


@pytest.fixture
def phone_video(tmp_path):
    """Like an iPhone video: GPS location, phone model and date in the metadata."""
    return make(
        tmp_path / "holiday.mov",
        *VIDEO, *SOUND, "-c:v", "libx264", "-c:a", "aac", "-shortest",
        "-metadata", "title=Holiday",
        "-metadata", "location=+47.3769+008.5417/",
        "-metadata", "com.apple.quicktime.location.ISO6709=+47.3769+008.5417/",
        "-metadata", "com.apple.quicktime.model=iPhone 15",
        "-metadata", "creation_time=2026-01-01T10:00:00Z",
        "-movflags", "use_metadata_tags",
    )  # fmt: skip


@pytest.fixture
def song(tmp_path):
    """An MP3 with song tags, a comment and an album cover."""
    return make(
        tmp_path / "song.mp3",
        *SOUND, "-f", "lavfi", "-i", "color=red:size=64x64:duration=0.1",
        "-map", "0", "-map", "1", "-c:v", "mjpeg", "-frames:v", "1",
        "-disposition:v", "attached_pic", "-id3v2_version", "3",
        "-metadata", "title=Song", "-metadata", "artist=Band", "-metadata", "album=First",
        "-metadata", "comment=Recorded at Main Street 5",
    )  # fmt: skip


def test_parse_info():
    text = """Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'x.mp4':
  Duration: 00:01:02.50, start: 0.000000, bitrate: 31 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p, 160x120, 10 fps, 10 tbr (default)
  Stream #0:1[0x2](deu): Audio: flac, 48000 Hz, stereo, s32 (24 bit) (default)
  Stream #0:2: Video: mjpeg (Baseline), yuvj420p, 64x64, 90k tbn (attached pic)
  Stream #0:3(eng): Subtitle: subrip
"""  # noqa: E501
    info = parse_info(text)
    assert info.duration == 62.5
    video, audio, cover, sub = info.streams
    assert (video.kind, video.codec, video.fps, video.cover) == ("video", "h264", 10.0, False)
    assert (audio.codec, audio.bits, audio.float_samples) == ("flac", 24, False)
    assert cover.cover and info.covers == [cover] and info.of("video") == [video]
    assert sub.kind == "subtitle"


def test_ffmpeg_may_only_open_local_files():
    path = Path("videos") / "a:b.mp4"
    args = _input(path)
    assert args[:2] == ["-protocol_whitelist", "file"]
    assert args[-1] == f"file:{path}"  # never read as a network address


@needs_ffmpeg
def test_targets_offered():
    engine = Engine()
    video = [t.id for t in engine.targets_for("mov")]
    assert {"mp4", "mkv", "webm", "avi", "gif", "mp3", "m4a", "wav", "flac"} <= set(video)
    audio = [t.id for t in engine.targets_for("flac")]
    assert set(audio) == {"mp3", "m4a", "wav", "ogg", "opus"}
    assert "png" not in video  # no video → GIF → first frame
    assert "mp4" not in [t.id for t in engine.targets_for("png")]  # no PNG → GIF → MP4
    assert "mp4" in [t.id for t in engine.targets_for("gif")]


@needs_ffmpeg
@pytest.mark.parametrize(
    ("ext", "expected", "extra"),
    [
        ("mp4", "mp4", []),
        ("mov", "mov", []),
        ("mkv", "mkv", []),
        ("webm", "webm", []),
        ("avi", "avi", []),
        ("wmv", "wmv", []),
        ("flv", "flv", []),
        ("mts", "mts", ["-c:v", "libx264", "-c:a", "aac", "-f", "mpegts"]),
    ],
)
def test_detect_video_by_content(tmp_path, ext, expected, extra):
    src = make(tmp_path / f"v.{ext}", *VIDEO, *SOUND, "-shortest", *extra)
    renamed = src.rename(tmp_path / "renamed.bin")
    assert formats.detect(renamed).id == expected


@needs_ffmpeg
@pytest.mark.parametrize("ext", ["mp3", "m4a", "wav", "flac", "ogg", "opus", "aiff", "aac", "wma"])
def test_detect_audio_by_content(tmp_path, ext):
    src = make(tmp_path / f"a.{ext}", *SOUND)
    assert formats.detect(src).id == ext
    if ext != "wma":  # WMA and WMV share one container: the name tells them apart
        assert formats.detect(src.rename(tmp_path / "renamed.bin")).id == ext


@needs_ffmpeg
def test_remux_copies_picture_and_sound_unchanged(phone_video, tmp_path):
    for target in ("mp4", "mkv"):
        [out] = Engine().convert(phone_video, target, tmp_path / target).outputs
        assert packets(out, "0:v") == packets(phone_video, "0:v")
        assert packets(out, "0:a") == packets(phone_video, "0:a")


@needs_ffmpeg
def test_phone_video_loses_location_and_phone_model(phone_video, tmp_path):
    assert "47.3769" in tags(phone_video)  # the test file really has them
    for target in ("mp4", "mkv", "webm", "mp3"):
        [out] = Engine().convert(phone_video, target, tmp_path / target).outputs
        found = tags(out)
        assert "47.3769" not in found and "iPhone" not in found, target
        assert "2026-01-01" not in found, target
        assert "title:Holiday" in found, target


@needs_ffmpeg
def test_song_keeps_tags_and_cover_but_not_comments(song, tmp_path):
    for target in ("m4a", "flac", "ogg"):
        [out] = Engine().convert(song, target, tmp_path / target).outputs
        found = tags(out)
        assert "title:Song" in found and "artist:Band" in found and "album:First" in found
        assert "MainStreet" not in found, target
        info = parse_info(
            subprocess.run([str(FFMPEG), "-i", str(out)], capture_output=True, text=True).stderr
        )
        assert bool(info.covers) == (target != "ogg"), target  # Ogg can't hold a cover


@needs_ffmpeg
def test_video_to_sound(phone_video, tmp_path):
    [out] = Engine().convert(phone_video, "m4a", tmp_path).outputs
    assert packets(out, "0:a") == packets(phone_video, "0:a")  # AAC copied as it is
    [mp3] = Engine().convert(phone_video, "mp3", tmp_path).outputs
    assert formats.detect(mp3).id == "mp3"


@needs_ffmpeg
def test_silent_video_to_sound_explains(tmp_path):
    src = make(tmp_path / "silent.mp4", *VIDEO)
    with pytest.raises(ConversionError, match="no sound"):
        Engine().convert(src, "mp3", tmp_path / "out")
    assert not (tmp_path / "out" / "silent.mp3").exists()


@needs_ffmpeg
def test_gif_both_ways(tmp_path):
    src = make(tmp_path / "clip.mp4", *VIDEO)
    [gif] = Engine().convert(src, "gif", tmp_path).outputs
    from PIL import Image

    with Image.open(gif) as im:
        assert im.n_frames == 10 and im.size == (160, 120)
    [back] = Engine().convert(gif, "mp4", tmp_path / "back").outputs
    assert formats.detect(back).id == "mp4"


@needs_ffmpeg
def test_damaged_file_is_refused_clearly(tmp_path):
    src = tmp_path / "broken.mp4"
    src.write_bytes(b"\x00\x00\x00\x18ftypisom" + bytes(range(256)) * 20)
    with pytest.raises(ConversionError, match="Cannot read this file"):
        Engine().convert(src, "mkv", tmp_path / "out")


@needs_ffmpeg
def test_playlist_pretending_to_be_a_video_cannot_reach_the_network(tmp_path):
    src = tmp_path / "trap.mp4"
    src.write_text("#EXTM3U\n#EXTINF:10,\nhttp://example.com/a.ts\n#EXT-X-ENDLIST\n")
    with pytest.raises(ConversionError):
        Engine().convert(src, "mkv", tmp_path / "out")


@needs_ffmpeg
def test_cancel_stops_ffmpeg(phone_video, tmp_path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ConversionCancelled):
        Engine().convert(phone_video, "webm", tmp_path / "out", cancel_event=cancel)
    assert not list((tmp_path / "out").glob("*.webm")) if (tmp_path / "out").exists() else True


@needs_ffmpeg
def test_progress_is_reported(tmp_path):
    src = make(
        tmp_path / "long.mp4", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=4"
    )
    seen = []
    Engine().convert(src, "webm", tmp_path / "out", progress=lambda f, m: seen.append((f, m)))
    assert seen[-1][0] == 1.0
    assert any("of 0:04" in m for _, m in seen)


@needs_ffmpeg
def test_ogg_song_tags_are_filtered_too(tmp_path):
    """Ogg keeps tags on the sound track itself: they're filtered like file tags."""
    src = make(
        tmp_path / "voice.ogg", *SOUND, "-c:a", "libvorbis",
        "-metadata:s:a:0", "title=Memo", "-metadata:s:a:0", "comment=At Main Street 5",
    )  # fmt: skip
    for target in ("mp3", "opus"):
        [out] = Engine().convert(src, target, tmp_path / target).outputs
        found = tags(out)
        assert "title:Memo" in found and "MainStreet" not in found, target


@needs_ffmpeg
def test_track_languages_are_kept(tmp_path):
    src = make(
        tmp_path / "film.mkv", *VIDEO, *SOUND, *SOUND, "-map", "0", "-map", "1", "-map", "2",
        "-c:v", "libx264", "-c:a", "aac", "-shortest",
        "-metadata:s:a:0", "language=deu", "-metadata:s:a:1", "language=eng",
        "-metadata:s:a:1", "comment=secret",
    )  # fmt: skip
    for target in ("mp4", "webm"):
        [out] = Engine().convert(src, target, tmp_path / target).outputs
        info = parse_info(tags_raw(out))
        assert [a.language for a in info.of("audio")] == ["deu", "eng"], target
        assert "secret" not in tags(out)


def tags_raw(path) -> str:
    return subprocess.run(
        [str(FFMPEG), "-hide_banner", "-i", str(path)], capture_output=True, text=True
    ).stderr


def test_photo_quality_choice_is_hidden_for_video_and_sound():
    from azoth.gui import targets

    mov, mp3, jpg = (formats.FORMATS[f] for f in ("mov", "mp3", "jpg"))
    assert not targets.uses_quality([mov], "mp4")
    assert not targets.uses_quality([mp3], "wav")
    assert not targets.uses_quality([mov], "gif")  # a GIF from a video: own settings
    assert targets.uses_quality([jpg], "webp")
    assert not targets.uses_quality([], None)


@needs_ffmpeg
def test_keep_metadata_setting_keeps_everything(phone_video, tmp_path):
    [out] = Engine().convert(phone_video, "mp4", tmp_path, options={"keep_metadata": True}).outputs
    assert "47.3769" in tags(out)


def test_missing_ffmpeg_says_reinstall_and_offers_no_download(monkeypatch):
    from azoth.converters import all_converters, media

    monkeypatch.setattr(media, "find_ffmpeg", lambda: None)
    engine = Engine(all_converters())
    [conv] = [c for c in engine.unavailable() if c.id == "ffmpeg"]
    assert "Install Azoth Converter again" in conv.unavailable_reason()
    assert not conv.download_url  # FFmpeg comes with the app: nothing to download
    with pytest.raises(ConversionError):
        conv.convert(Path("a.mp4"), Path("a.mkv"), None)


# --- "Remove metadata only" for videos and music ---------------------------------------


@needs_ffmpeg
def test_remove_metadata_from_a_phone_video(phone_video, tmp_path):
    from azoth import metadata

    found = [str(f) for f in metadata.inspect(phone_video)]
    assert any(f.startswith("Location (GPS)") for f in found)
    assert any("iPhone" in f for f in found)
    result = metadata.clean_file(phone_video)
    assert result.output.name == "holiday (clean).mov"  # next to the original
    assert phone_video.is_file()  # the original is untouched
    assert metadata.inspect(result.output) == []
    after = tags(result.output)
    assert "47.3769" not in after and "iPhone" not in after and "title:Holiday" in after
    assert packets(result.output, "0:v") == packets(phone_video, "0:v")
    assert packets(result.output, "0:a") == packets(phone_video, "0:a")


@needs_ffmpeg
def test_remove_metadata_keeps_song_tags_and_cover(song, tmp_path):
    from azoth import metadata

    assert [str(f) for f in metadata.inspect(song)] == ["Comment: Recorded at Main Street 5"]
    result = metadata.clean_file(song, tmp_path / "out")
    after = tags(result.output)
    assert "title:Song" in after and "artist:Band" in after and "MainStreet" not in after
    info = parse_info(tags_raw(result.output))
    assert info.covers  # the album cover stays


@needs_ffmpeg
def test_nothing_is_saved_if_a_track_would_change(phone_video, tmp_path, monkeypatch):
    from azoth import media_metadata, metadata

    hashes = iter([["a"], ["b"]])
    monkeypatch.setattr(media_metadata, "_stream_hashes", lambda ffmpeg, path: next(hashes))
    with pytest.raises(ConversionError, match="did not save a file"):
        metadata.clean_file(phone_video, tmp_path / "out")
    assert not list((tmp_path / "out").glob("*"))


def test_videos_and_music_offer_remove_metadata():
    from azoth import metadata
    from azoth.gui import targets

    for fmt in ("mp4", "mov", "mkv", "mp3", "m4a", "flac"):
        assert fmt in metadata.CLEANABLE
        assert targets.choices(Engine(), [formats.FORMATS[fmt]]).can_clean


# --- "Make smaller" ----------------------------------------------------------------------


def probe_video(path) -> dict[str, str]:
    """Codec, picture size, frame rate and colours of the first video track, read from
    what FFmpeg says about the file (no ffprobe: the app doesn't bundle it)."""
    import re

    text = subprocess.run(
        [str(FFMPEG), "-hide_banner", "-i", str(path)], capture_output=True, text=True
    ).stderr
    line = next(x for x in text.splitlines() if "Video:" in x)
    size = re.search(r", (\d+)x(\d+)", line)
    info = {
        "codec_name": line.split("Video: ")[1].split()[0],
        "width": size[1],
        "height": size[2],
        "fps": re.search(r"([\d.]+) fps", line)[1],
        "color_transfer": "bt709" if re.search(r"bt709[,)]", line) else "",
    }
    if "rotation of" in text:
        info["rotation"] = "yes"
    return info


def big_phone_video(path, size="1920x1080", rate=60, *extra):
    return make(
        path,
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration=1", *SOUND,
        "-c:v", "libx264", "-crf", "10", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
        "-metadata", "location=+47.3769+008.5417/", "-movflags", "use_metadata_tags", *extra,
    )  # fmt: skip


@needs_ffmpeg
def test_make_smaller_phone_video(tmp_path):
    src = big_phone_video(tmp_path / "party.mov")
    before = src.read_bytes()
    result = Engine().convert(src, "mp4", tmp_path / "out", options={"shrink": "720"})
    [out] = result.outputs
    assert out.name == "party (smaller).mp4"
    info = probe_video(out)
    assert info["codec_name"] == "h264" and (info["width"], info["height"]) == ("1280", "720")
    assert info["fps"] == "30"  # 60 fps phone video: half the frames
    assert packets(out, "0:a") == packets(src, "0:a")  # AAC sound copied unchanged
    assert out.stat().st_size < src.stat().st_size
    assert "47.3769" not in tags(out)  # still no location
    assert src.read_bytes() == before  # the original is never touched


@needs_ffmpeg
def test_make_smaller_keeps_upright_phone_videos_upright(tmp_path):
    # Phones store upright videos lying on their side, with a "turn by 90°" flag.
    lying = big_phone_video(tmp_path / "lying.mp4", "1280x720", 30)
    upright = make(tmp_path / "upright.mov", "-display_rotation", "90", "-i", str(lying),
                   "-c", "copy")  # fmt: skip
    [out] = Engine().convert(upright, "mp4", tmp_path / "o", options={"shrink": "480"}).outputs
    info = probe_video(out)
    assert (info["width"], info["height"]) == ("480", "854")  # turned, the short side 480
    assert "rotation" not in info  # really turned, not just flagged


@needs_ffmpeg
def test_make_smaller_never_enlarges_and_refuses_when_nothing_is_saved(tmp_path):
    # Tiny and already strongly compressed: a "smaller" copy would be bigger.
    src = make(tmp_path / "tiny.mp4", *VIDEO, "-c:v", "libx264", "-crf", "51")
    with pytest.raises(ConversionError, match="already small"):
        Engine().convert(src, "mp4", tmp_path / "o", options={"shrink": "1080"})
    assert not any((tmp_path / "o").glob("*"))  # nothing left behind


@needs_ffmpeg
def test_make_smaller_turns_hdr_into_normal_colours(tmp_path):
    from azoth.converters.media import has_filter

    if not has_filter(FFMPEG, "zscale"):
        pytest.skip("this FFmpeg has no zscale filter")
    src = big_phone_video(
        tmp_path / "hdr.mov", "1280x720", 30,
        "-color_primaries", "bt2020", "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc",
    )  # fmt: skip
    [out] = Engine().convert(src, "mp4", tmp_path / "o", options={"shrink": "480"}).outputs
    assert probe_video(out)["color_transfer"] == "bt709"


def test_shrink_plan():
    from azoth.converters.media import plan_shrink

    text = (
        "  Stream #0:0[0x1](und): Video: hevc (Main 10), yuv420p10le(tv, bt2020nc/bt2020/"
        "arib-std-b67), 3840x2160, 59.94 fps\n"
        "  Stream #0:1[0x2](und): Audio: pcm_s16le, 48000 Hz, stereo, s16, 1536 kb/s\n"
    )
    info = parse_info(text)
    assert info.of("video")[0].hdr
    args = plan_shrink("720", info)
    vf = args[args.index("-vf") + 1]
    assert vf.startswith("fps=30,scale=") and "min(ih,720)" in vf and "tonemap" in vf
    assert args[args.index("-c:a:0") + 1] == "aac" and "192k" in args  # PCM: re-encoded
    assert "tonemap" not in plan_shrink("720", info, tonemap=False)[args.index("-vf") + 1]
    with pytest.raises(ConversionError):
        plan_shrink("4k", info)


def test_only_videos_can_be_made_smaller(tmp_path):
    from azoth.gui import targets

    engine = Engine()
    if FFMPEG is not None:
        assert targets.choices(engine, [formats.FORMATS["mov"]]).can_shrink
        assert targets.choices(engine, [formats.FORMATS["mp4"]]).can_shrink
    for fmt in ("mp3", "jpg", "pdf"):
        assert not targets.choices(engine, [formats.FORMATS[fmt]]).can_shrink
    assert targets.job_target(targets.SHRINK_TARGET, formats.FORMATS["mov"]) == "mp4"
    song = tmp_path / "a.mp3"
    song.write_bytes(b"ID3" + bytes(200))
    with pytest.raises(ConversionError, match="only for videos"):
        engine.convert(song, "mp4", tmp_path, options={"shrink": "720"})


def test_cli_shrink_checks_its_options(tmp_path, capsys):
    from azoth.cli import main

    clip = tmp_path / "a.mov"
    clip.write_bytes(bytes(100))
    assert main(["convert", str(clip), "--to", "webm", "--shrink", "720"]) == 2
    assert "--shrink saves MP4" in capsys.readouterr().err
    assert main(["convert", str(clip), "--to", "mp4", "--shrink", "720", "--ai"]) == 2
    assert "for videos" in capsys.readouterr().err


@needs_ffmpeg
def test_cli_shrink(tmp_path):
    from azoth.cli import main

    src = big_phone_video(tmp_path / "trip.mov", "1280x720", 30)
    assert main(["convert", str(src), "--to", "mp4", "--shrink", "480", "-q"]) == 0
    assert probe_video(tmp_path / "trip (smaller).mp4")["height"] == "480"
