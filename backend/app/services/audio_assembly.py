"""Podcast audio assembly — turns per-segment audio files into one playable episode.

Strategy (checked against the real deployment constraints):

1. **ffmpeg (preferred, present in the deployment image)** — every segment is
   normalized to the same mono 44.1 kHz MP3 stream and then concatenated with the
   concat demuxer (``-c copy``), so headers are rebuilt exactly once and no
   duplicate-header garbage or double ID3 tags survive. Output is a single MP3.
2. **Pure-Python fallbacks (no ffmpeg)** — if every segment is a WAV, the stdlib
   :mod:`wave` module re-frames the PCM data correctly (never a naive byte concat).
   If segments are MP3, an ID3-tag-aware frame concatenation produces a playable
   stream (most decoders accept concatenated frames; the ID3 headers that would
   glitch playback are stripped).

Durations come from ``ffprobe`` when available, the wave header for WAV, or a
frame-level MP3 estimate otherwise — so the transcript timestamps are real, never
invented. No new Python dependency is introduced.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

# Conservative MP3 frame constants for duration estimates when ffprobe is absent.
_MP3_BITRATES = {
    (1, 1): 32, (1, 2): 40, (1, 3): 48, (1, 4): 56, (1, 5): 64, (1, 6): 80,
    (1, 7): 96, (1, 8): 112, (1, 9): 128, (1, 10): 160, (1, 11): 192,
    (1, 12): 224, (1, 13): 256, (1, 14): 320,
    (2, 1): 8, (2, 2): 16, (2, 3): 24, (2, 4): 32, (2, 5): 40, (2, 6): 48,
    (2, 7): 56, (2, 8): 64, (2, 9): 80, (2, 10): 96, (2, 11): 112,
    (2, 12): 128, (2, 13): 144, (2, 14): 160,
}
_MP3_RATES = {
    3: (44100, 48000, 32000),
    2: (22050, 24000, 16000),
    0: (11025, 12000, 8000),
}


def is_wav(data: bytes) -> bool:
    return data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def is_mp3(data: bytes) -> bool:
    if data[:3] == b"ID3":
        return True
    return len(data) > 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0


def run_ffmpeg(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - fixed binary path, admin-configured inputs
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def normalize_to_mp3(source: Path, target: Path) -> None:
    """Re-encode one segment to a uniform mono MP3 stream (ffmpeg)."""
    result = run_ffmpeg(
        ["-i", str(source), "-vn", "-ar", "44100", "-ac", "1", "-b:a", "96k", str(target)]
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg normalize failed: {result.stderr[:400].decode(errors='replace')}")


def assemble_with_ffmpeg(segment_paths: list[Path], output: Path, workdir: Path) -> None:
    """Normalize every segment, then concat demux with stream copy (single header)."""
    normalized: list[Path] = []
    for index, source in enumerate(segment_paths):
        target = workdir / f"norm-{index:04d}.mp3"
        normalize_to_mp3(source, target)
        normalized.append(target)
    list_file = workdir / "concat-list.txt"
    list_file.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in normalized), encoding="utf-8"
    )
    result = run_ffmpeg(
        ["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(output)]
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {result.stderr[:400].decode(errors='replace')}")


def assemble_wav_stdlib(segment_paths: list[Path], output: Path) -> float:
    """Concatenate uniform WAV files correctly (frames re-packed, one header)."""
    params = None
    duration = 0.0
    with wave.open(str(output), "wb") as out:
        for source in segment_paths:
            with wave.open(str(source), "rb") as reader:
                current = reader.getparams()
                if params is None:
                    params = current
                    out.setparams(current)
                elif (current.nchannels, current.sampwidth, current.framerate) != (
                    params.nchannels,
                    params.sampwidth,
                    params.framerate,
                ):
                    raise ValueError("WAV segments have incompatible formats for stdlib concat")
                frames = reader.readframes(reader.getnframes())
                out.writeframes(frames)
                duration += reader.getnframes() / float(current.framerate)
    return duration


def strip_id3(data: bytes) -> bytes:
    """Remove an ID3v2 header block so concatenated MP3 frames play cleanly."""
    if data[:3] != b"ID3":
        return data
    if len(data) < 10:
        return b""
    size = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) | ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
    return data[10 + size:]


def assemble_mp3_frames(segment_paths: list[Path], output: Path) -> float:
    """Fallback MP3 concatenation: strip ID3 headers, join frames."""
    duration = 0.0
    with output.open("wb") as out:
        for source in segment_paths:
            data = strip_id3(source.read_bytes())
            duration += estimate_mp3_duration(data)
            out.write(data)
    return duration


def estimate_mp3_duration(data: bytes) -> float:
    """Estimate MP3 duration from frame headers (fallback when ffprobe is absent)."""
    total = 0.0
    index = 0
    length = len(data)
    while index + 4 <= length:
        if data[index] == 0xFF and (data[index + 1] & 0xE0) == 0xE0:
            header = struct.unpack(">I", data[index:index + 4])[0]
            version = (header >> 19) & 0x03  # 3 = MPEG1
            layer = (header >> 17) & 0x03  # 1 = Layer III
            bitrate_index = (header >> 12) & 0x0F
            rate_index = (header >> 10) & 0x03
            if layer == 0x01 and bitrate_index not in (0, 15) and rate_index != 3:
                key = (1 if version == 3 else 2, bitrate_index)
                bitrate = _MP3_BITRATES.get(key, 128) * 1000
                rate = _MP3_RATES[version if version in (3, 2, 0) else 3][rate_index]
                samples = 1152 if version == 3 else 576
                frame_len = int(samples / 8 * bitrate / rate) + ((header >> 9) & 0x01)
                if frame_len <= 0:
                    index += 1
                    continue
                total += samples / rate
                index += frame_len
                continue
        index += 1
    return total


def measure_duration(path: Path) -> float:
    """Real duration of a produced file: ffprobe > wave header > frame estimate."""
    if FFPROBE:
        result = subprocess.run(  # noqa: S603 - fixed binary path
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True,
            timeout=60,
            check=False,
        )
        if result.returncode == 0:
            try:
                return max(0.0, float(result.stdout.strip()))
            except ValueError:
                pass
    data = path.read_bytes()
    if is_wav(data):
        with wave.open(str(path), "rb") as reader:
            return reader.getnframes() / float(reader.getframerate())
    return estimate_mp3_duration(data)


def assemble(
    segment_paths: list[Path], output: Path, *, workdir: Path | None = None
) -> tuple[Path, float, str]:
    """Assemble ordered segments and return ``(file, real_duration, media_type)``.

    The produced container may be MP3 (ffmpeg / frame concat) or WAV (stdlib
    fallback when every segment is WAV); the caller must persist whichever path
    is returned.
    """
    if not segment_paths:
        raise ValueError("no segments to assemble")
    output.parent.mkdir(parents=True, exist_ok=True)
    if FFMPEG:
        with tempfile.TemporaryDirectory(prefix="podcast-asm-") as tmp:
            assemble_with_ffmpeg(segment_paths, output, Path(tmp))
        return output, measure_duration(output), "audio/mpeg"
    if all(is_wav(path.read_bytes()) for path in segment_paths):
        wav_output = output.with_suffix(".wav")
        duration = assemble_wav_stdlib(segment_paths, wav_output)
        return wav_output, duration, "audio/wav"
    return output, assemble_mp3_frames(segment_paths, output), "audio/mpeg"


def is_assembler_available() -> bool:
    """True when ffmpeg is present (the preferred, quality-controlled path)."""
    return bool(FFMPEG)


__all__ = [
    "assemble",
    "assemble_mp3_frames",
    "assemble_wav_stdlib",
    "assemble_with_ffmpeg",
    "estimate_mp3_duration",
    "is_assembler_available",
    "is_mp3",
    "is_wav",
    "measure_duration",
    "strip_id3",
]
