"""
Screen recorder: captures the primary monitor in a background thread
and writes frames (with subtitle overlay) directly to an MP4 file.
"""

import threading
import time

import cv2
import mss
import numpy as np
from PIL import Image

from overlay import apply_subtitle, create_transition_frame


class ScreenRecorder:
    """
    Captures the primary monitor at a fixed FPS in a background thread.
    Overlays subtitle text on each frame and writes to MP4 via cv2.VideoWriter.

    Usage:
        rec = ScreenRecorder("output.mp4", fps=12)
        rec.start()
        rec.set_overlay("Step 1: doing something")
        ...
        rec.inject_transition("Scene 2", "Description", duration=2.0)
        rec.set_overlay("Step 2: doing something else")
        ...
        rec.stop()
    """

    def __init__(self, output_path: str, fps: int = 12, monitor_index: int = 1):
        self.output_path = output_path
        self.fps = fps
        self.monitor_index = monitor_index  # mss monitor index (1=primary, 2=secondary, ...)

        self._running = False
        self._overlay_text = ""
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._writer: cv2.VideoWriter | None = None
        self._width = 0
        self._height = 0
        self._frame_count = 0
        self._inject_queue: list[Image.Image] = []
        self._inject_lock = threading.Lock()

    def set_overlay(self, text: str) -> None:
        """Set the subtitle text shown on subsequent frames (thread-safe)."""
        with self._lock:
            self._overlay_text = text

    def _get_overlay(self) -> str:
        with self._lock:
            return self._overlay_text

    def inject_transition(
        self,
        title: str,
        subtitle: str = "",
        duration: float = 2.0,
    ) -> None:
        """
        Inject transition frames into the video.
        Blocks until all transition frames are written.
        """
        if self._width == 0 or self._height == 0:
            return

        frame = create_transition_frame(self._width, self._height, title, subtitle)
        num_frames = max(1, int(duration * self.fps))

        frames = [frame] * num_frames
        with self._inject_lock:
            self._inject_queue.extend(frames)

        # Wait for injection to be consumed
        while True:
            with self._inject_lock:
                if not self._inject_queue:
                    break
            time.sleep(0.05)

    def start(self) -> None:
        """Start the background capture thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop capture and finalize the video file."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        if self._writer:
            self._writer.release()
            self._writer = None
        print(f"[ScreenRecorder] Saved {self._frame_count} frames to {self.output_path}")

    def _capture_loop(self) -> None:
        interval = 1.0 / self.fps

        with mss.mss() as sct:
            monitor = sct.monitors[self.monitor_index]
            self._width = monitor["width"]
            self._height = monitor["height"]

            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self._writer = cv2.VideoWriter(
                self.output_path, fourcc, self.fps, (self._width, self._height)
            )

            while self._running:
                t0 = time.perf_counter()

                # Check for injected transition frames first
                with self._inject_lock:
                    if self._inject_queue:
                        inject_frame = self._inject_queue.pop(0)
                        bgr = cv2.cvtColor(np.array(inject_frame), cv2.COLOR_RGB2BGR)
                        self._writer.write(bgr)
                        self._frame_count += 1
                        elapsed = time.perf_counter() - t0
                        sleep_time = interval - elapsed
                        if sleep_time > 0:
                            time.sleep(sleep_time)
                        continue

                # Capture screen
                try:
                    raw = sct.grab(monitor)
                except Exception:
                    time.sleep(interval)
                    continue

                # Convert BGRA → RGB PIL Image
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

                # Apply subtitle overlay
                overlay_text = self._get_overlay()
                if overlay_text:
                    img = apply_subtitle(img, overlay_text)

                # Convert to BGR numpy for OpenCV
                bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                self._writer.write(bgr)
                self._frame_count += 1

                # Maintain target FPS
                elapsed = time.perf_counter() - t0
                sleep_time = interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        # Flush remaining injection queue
        with self._inject_lock:
            for inject_frame in self._inject_queue:
                bgr = cv2.cvtColor(np.array(inject_frame), cv2.COLOR_RGB2BGR)
                self._writer.write(bgr)
                self._frame_count += 1
            self._inject_queue.clear()
