"""
Post-processing: adds female Russian voice narration to demo video.

Reads the subtitle timeline JSON generated during recording,
generates TTS audio for each segment using edge-tts,
assembles a combined audio track, and muxes it with the video.

Uses ffmpeg (from imageio-ffmpeg) directly — no pydub/ffprobe needed.

Usage:
    python add_narration.py [--video c:\\tmp\\word_to_s1000d_demo.mp4]
                            [--voice ru-RU-SvetlanaNeural]
                            [--rate -5%]
                            [--cache-dir c:\\tmp\\tts_cache]
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import struct
import subprocess
import wave

import edge_tts


# ─── Audio constants ─────────────────────────────────────────────────────────

SAMPLE_RATE = 24000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit PCM

# Segments shorter than this are skipped (instant subtitle switches)
MIN_SEGMENT_DURATION = 0.5


# ─── ffmpeg from imageio-ffmpeg ──────────────────────────────────────────────

def get_ffmpeg_path() -> str:
    """Locate ffmpeg binary bundled by imageio-ffmpeg."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


# ─── Text replacements for natural TTS ────────────────────────────────────────

# Phrase-level replacements (applied first, order matters — longer matches first)
TTS_REPLACEMENTS = [
    # Full phrase replacements
    (r"Просмотр сгенерированных модулей данных в TG\s*Web", "Просмотр модулей данных"),
    (r"Серверы Flask и TG Web запущены", "Серверы конвертации и просмотра запущены"),
    (r"Нажимаем [«\"]Сформировать все[»\"] для генерации XML", "Запускаем генерацию"),
    (r"Нажимаем [«\"]Эталон[»\"] для создания эталонной разметки", "Создаём эталонную разметку"),
    (r"Нажимаем [«\"]Разделить[»\"] для разбиения на отдельные элементы", "Разделяем элемент на части"),
    (r"Нажимаем [«\"]Форматировать согласно эталону[»\"]", "Форматируем по эталону"),
    (r"Открываем контекстное меню элемента \(клик\)", "Открываем меню"),
    (r"Открываем режим сравнения для выбранного документа", "Открываем сравнение"),
    # Scene 6: shorten dense navigation area
    (r"Навигация по расхождениям между PDF и XML", "Навигация по расхождениям"),
    (r"Подсветка расхождений между исходным документом и XML", "Подсветка расхождений"),
    # Scene 7: shorten dense edit area
    (r"Редактирование разметки: разделение списка на параграфы", "Разделение списка на параграфы"),
    (r"Элемент разделён на отдельные части", "Элемент разделён"),
    (r"Разметка изменена: \d+ элементов списка -> параграфы", "Разметка изменена"),
    # Scene 8: shorten verification
    (r"Выполняется цикл верификации\.\.\.", "Верификация"),
    (r"Результат верификации: Цикл\.\.\.", "Результат верификации"),
    # Patterns with trailing details (.*) — replace entire match
    (r"Просмотр модуля:.*", "Просмотр модуля данных"),
    (r"Найден элемент:.*", "Найден элемент"),
    # Technical term replacements (longer first to avoid partial matches)
    (r"word_to_s1000d\.exe", "модуля конвертации"),
    (r"word_to_s1000d", "модуля конвертации"),
    (r"TG\s*Web", "просмотра документации"),
    (r"Flask", "конвертации"),
    (r"S1000D\s+XML", "XML"),
    (r"S1000D", ""),
    (r"PDF из Word", "исходный документ"),
]


def clean_text_for_tts(text: str) -> str:
    """Clean subtitle text for natural-sounding TTS narration."""
    # Apply phrase/term replacements first
    for pattern, replacement in TTS_REPLACEMENTS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # Remove Windows file paths (c:\tmp\..., c:\Users\...)
    text = re.sub(r'[a-zA-Z]:\\[\w\\]+', '', text)
    # Clean up double spaces from replacements/removals
    text = re.sub(r'\s{2,}', ' ', text).strip()
    # Remove DMC codes: DMC-S5-A-029-... or S5-A-029-...
    text = re.sub(r'(?:DMC-)?S\d+-[A-Z]-\d{3}-\d{2}-\d{2}-\d{2}[A-Z]-\d{3}[A-Z]-[A-Z](?:_\d+)?', '', text)
    # Remove trailing ":" or " :" after removal
    text = re.sub(r'\s*:\s*$', '', text)
    # Clean up marker labels like [5] or (5)
    text = re.sub(r'\s*\[\d+\]', '', text)
    # Clean "спис.1" → "список 1", "загол.1" → "заголовок 1"
    text = re.sub(r'спис\.(\d+)', r'список \1', text)
    text = re.sub(r'загол\.(\d+)', r'заголовок \1', text)
    # Final cleanup
    text = re.sub(r'\s{2,}', ' ', text).strip()
    # Fix accent: эталон → этало́н (stress on last syllable)
    text = text.replace('эталон', 'этало\u0301н')
    text = text.replace('Эталон', 'Этало\u0301н')
    return text


# ─── Low-level audio helpers (no pydub) ──────────────────────────────────────

def mp3_to_pcm(mp3_path: str) -> bytes:
    """Decode MP3 to raw PCM bytes (mono, 16-bit, 24kHz) using ffmpeg."""
    ffmpeg = get_ffmpeg_path()
    result = subprocess.run(
        [ffmpeg, "-y", "-i", mp3_path,
         "-f", "s16le", "-acodec", "pcm_s16le",
         "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS),
         "pipe:1"],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg decode failed for {mp3_path}")
    return result.stdout


def pcm_duration_sec(pcm_data: bytes) -> float:
    """Duration in seconds of raw PCM data."""
    num_samples = len(pcm_data) // (SAMPLE_WIDTH * CHANNELS)
    return num_samples / SAMPLE_RATE


def write_wav(path: str, pcm_data: bytes) -> None:
    """Write raw PCM bytes to a WAV file."""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_data)


def silence_pcm(duration_sec: float) -> bytes:
    """Generate silent PCM data for the given duration."""
    num_samples = int(duration_sec * SAMPLE_RATE)
    return b"\x00" * (num_samples * SAMPLE_WIDTH * CHANNELS)


def overlay_pcm(base: bytearray, overlay_data: bytes, offset_samples: int) -> None:
    """Mix overlay_data into base at the given sample offset (in-place, additive)."""
    overlay_samples = len(overlay_data) // SAMPLE_WIDTH
    for i in range(overlay_samples):
        pos = (offset_samples + i) * SAMPLE_WIDTH
        if pos + SAMPLE_WIDTH > len(base):
            break
        base_val = struct.unpack_from("<h", base, pos)[0]
        ovl_val = struct.unpack_from("<h", overlay_data, i * SAMPLE_WIDTH)[0]
        mixed = max(-32768, min(32767, base_val + ovl_val))
        struct.pack_into("<h", base, pos, mixed)


# ─── TTS generation ─────────────────────────────────────────────────────────

def _text_hash(text: str) -> str:
    """Stable hash for caching TTS output (based on cleaned text)."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


async def generate_tts_segment(
    text: str,
    output_path: str,
    voice: str = "ru-RU-SvetlanaNeural",
    rate: str = "-5%",
) -> float:
    """Generate TTS audio for a single text. Returns duration in seconds."""
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(output_path)
    pcm = mp3_to_pcm(output_path)
    return pcm_duration_sec(pcm)


def contextualize_segments(segments: list[dict]) -> None:
    """Apply context-aware text modifications for sequential patterns (in-place).

    Handles cases where the same subtitle repeats with different parameters
    (e.g., viewing 3 modules in a row, changing 5 list items to paragraphs).
    """
    prosmotr_count = 0
    izmenyaem_count = 0

    for seg in segments:
        text = seg.get("tts_text", "")

        # "Просмотр модуля данных" — vary for consecutive occurrences
        if "Просмотр модуля данных" in text and "модулей" not in text:
            if prosmotr_count == 0:
                seg["tts_text"] = "Просмотр модуля данных"
            elif prosmotr_count == 1:
                seg["tts_text"] = "Просмотр другого модуля данных"
            else:
                seg["tts_text"] = "Просмотр ещё одного модуля данных"
            prosmotr_count += 1

        # "Изменяем [...] на параграф" — first two get text, rest are silent
        if re.search(r'Изменяем.*на параграф', text, re.IGNORECASE):
            if izmenyaem_count == 0:
                seg["tts_text"] = "Изменение элемента списка на параграф"
            elif izmenyaem_count == 1:
                seg["tts_text"] = "Изменение других элементов списка на параграф"
            else:
                seg["tts_text"] = ""  # skip — already described
            izmenyaem_count += 1


async def generate_all_tts(
    segments: list[dict],
    cache_dir: str,
    voice: str,
    rate: str,
) -> list[dict]:
    """Generate TTS for all segments with file caching. Returns enriched segments."""
    os.makedirs(cache_dir, exist_ok=True)

    # Pass 1: clean all texts
    for seg in segments:
        seg["tts_text"] = clean_text_for_tts(seg["text"])

    # Pass 2: contextualize sequential patterns
    contextualize_segments(segments)

    # Pass 3: generate TTS audio
    results = []
    for seg in segments:
        tts_text = seg.get("tts_text", "")

        if not tts_text:
            print(f"  [skip]       #{seg['index']:02d}: empty after cleanup")
            continue

        h = _text_hash(tts_text)
        mp3_path = os.path.join(cache_dir, f"seg_{seg['index']:03d}_{h}.mp3")

        # Strip combining accents for console logging (cp1251 can't display U+0301)
        log_text = tts_text.replace('\u0301', '')[:60]

        if os.path.isfile(mp3_path):
            pcm = mp3_to_pcm(mp3_path)
            tts_dur = pcm_duration_sec(pcm)
            print(f"  [cached]     #{seg['index']:02d} ({tts_dur:.1f}s): {log_text}")
        else:
            tts_dur = await generate_tts_segment(tts_text, mp3_path, voice, rate)
            print(f"  [generated]  #{seg['index']:02d} ({tts_dur:.1f}s): {log_text}")

        results.append({
            **seg,
            "tts_text": tts_text,
            "mp3_path": mp3_path,
            "tts_duration_sec": tts_dur,
        })

    return results


# ─── Audio assembly ──────────────────────────────────────────────────────────

def assemble_audio_track(
    segments: list[dict],
    total_duration_sec: float,
) -> bytes:
    """Build a single PCM audio track from TTS segments without overlaps.

    Each segment starts no earlier than the previous one finishes (+ 200ms gap).
    If the delay from the subtitle timestamp exceeds 7s, we place it at the
    subtitle timestamp anyway (accepting a brief overlap to stay in sync).
    """
    GAP = 0.2       # pause between consecutive TTS segments (seconds)
    MAX_DELAY = 7.0  # max allowed delay from subtitle timestamp

    base = bytearray(silence_pcm(total_duration_sec))
    cursor = 0.0  # tracks when the last TTS segment ends

    for seg in segments:
        mp3_path = seg["mp3_path"]
        pcm = mp3_to_pcm(mp3_path)
        tts_dur = pcm_duration_sec(pcm)

        # Start no earlier than subtitle timestamp,
        # but also no earlier than previous TTS end + gap
        actual_start = max(seg["start_sec"], cursor + GAP)

        # If we'd be too far behind the subtitle, snap back to subtitle time
        if actual_start - seg["start_sec"] > MAX_DELAY:
            actual_start = seg["start_sec"]

        offset_samples = int(actual_start * SAMPLE_RATE)
        overlay_pcm(base, pcm, offset_samples)
        cursor = actual_start + tts_dur

        delay = actual_start - seg["start_sec"]
        if delay > 0.5:
            print(f"  [delay]  #{seg['index']:02d}: +{delay:.1f}s from subtitle")

    return bytes(base)


# ─── Video + audio muxing ────────────────────────────────────────────────────

def mux_video_audio(
    video_path: str,
    audio_path: str,
    output_path: str,
) -> None:
    """Combine video and audio into final MP4 using ffmpeg.

    Re-encodes video to H.264 for proper keyframe index and universal playback.
    """
    ffmpeg = get_ffmpeg_path()

    cmd = [
        ffmpeg, "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]

    print(f"[Narration] Running ffmpeg (H.264 re-encode)...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] ffmpeg failed:\n{result.stderr[:500]}")
        raise RuntimeError("ffmpeg mux failed")

    print(f"[Narration] Final video saved: {output_path}")


# ─── Timeline filtering ─────────────────────────────────────────────────────

def filter_segments(segments: list[dict]) -> list[dict]:
    """Remove segments too short or transition screens (step titles)."""
    filtered = []
    skipped_short = 0
    skipped_transition = 0
    for seg in segments:
        if seg.get("is_transition"):
            skipped_transition += 1
            continue
        if seg["duration_sec"] < MIN_SEGMENT_DURATION:
            skipped_short += 1
            continue
        filtered.append(seg)
    if skipped_short:
        print(f"[Narration] Skipped {skipped_short} segments shorter than {MIN_SEGMENT_DURATION}s")
    if skipped_transition:
        print(f"[Narration] Skipped {skipped_transition} transition segments (step titles)")
    return filtered


# ─── Main ────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Add narration to demo video")
    parser.add_argument("--video", default=r"c:\tmp\word_to_s1000d_demo.mp4")
    parser.add_argument("--timeline", default=None,
                        help="Timeline JSON path (default: derived from video path)")
    parser.add_argument("--output", default=None,
                        help="Output path (default: video_narrated.mp4)")
    parser.add_argument("--voice", default="ru-RU-SvetlanaNeural")
    parser.add_argument("--rate", default="-5%",
                        help="TTS speech rate (e.g., '-10%%', '+5%%')")
    parser.add_argument("--cache-dir", default=r"c:\tmp\tts_cache")
    args = parser.parse_args()

    if args.timeline is None:
        args.timeline = args.video.replace(".mp4", "_timeline.json")
    if args.output is None:
        args.output = args.video.replace(".mp4", "_narrated.mp4")

    # Load timeline
    print(f"[Narration] Loading timeline: {args.timeline}")
    with open(args.timeline, "r", encoding="utf-8") as f:
        timeline = json.load(f)

    segments = timeline["segments"]
    total_duration = timeline["total_duration_sec"]
    print(f"[Narration] {len(segments)} segments, {total_duration:.1f}s total")

    # Filter out too-short segments
    segments = filter_segments(segments)

    # Generate TTS (with text cleanup)
    print(f"[Narration] Generating TTS: voice={args.voice}, rate={args.rate}")
    segments = await generate_all_tts(segments, args.cache_dir, args.voice, args.rate)

    # Assemble audio track (normal speed, no speedup)
    print("[Narration] Assembling audio track...")
    combined_pcm = assemble_audio_track(segments, total_duration)

    audio_wav = os.path.join(args.cache_dir, "combined_narration.wav")
    write_wav(audio_wav, combined_pcm)
    dur_sec = pcm_duration_sec(combined_pcm)
    print(f"[Narration] Audio track: {audio_wav} ({dur_sec:.1f}s)")

    # Mux video + audio (H.264 re-encode for proper playback)
    print("[Narration] Muxing video + audio...")
    mux_video_audio(args.video, audio_wav, args.output)

    output_size = os.path.getsize(args.output) / (1024 * 1024)
    print(f"[Narration] Done! {args.output} ({output_size:.1f} MB)")


if __name__ == "__main__":
    asyncio.run(main())
