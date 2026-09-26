import cv2
import threading
import time
from queue import Queue
import subprocess
import numpy as np


class VideoStream:
    def __init__(self, source: str, fps: float = 30.0, buffer_size: int = 10):
        self.source = source
        self.fps = fps
        self.cap = None
        self.ffmpeg_process = None
        self.frame_queue = Queue(maxsize=buffer_size)
        self.stopped = False
        self.finished = False
        self.has_error = False
        self.consecutive_errors = 0
        self.MAX_ERRORS = 50  # 5 segundos de intentos fallidos
        self.thread = None
        self._loop_lock = threading.Lock()
        self._looped = False
        self.frame_count = 0
        self.start_time = time.time()
        self.current_fps = 0.0

        self._init_source()

    def _init_source(self):
        if 'youtube.com' in self.source or 'youtu.be' in self.source:
            try:
                r = subprocess.run(
                    ['yt-dlp', '--no-playlist', '-g', '-f', 'bestvideo', self.source],
                    capture_output=True, text=True, check=True, timeout=15
                )
                if r.stdout:
                    self.source = r.stdout.strip().splitlines()[0]
            except Exception as e:
                print(f"[VideoStream] Error extracting YouTube URL: {e}")
        self._start_hls_stream()

    def check_and_clear_loop(self):
        with self._loop_lock:
            if self._looped:
                self._looped = False
                return True
        return False

    def start(self):
        self.stopped  = False
        self.finished = False
        self.start_time = time.time()

        self._init_source()

        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()
        print(f"[VideoStream] Iniciado (hls, {self.fps:.1f}fps): {self.source}")
        return self

    def _start_hls_stream(self):
        try:
            def probe(field):
                r = subprocess.run(
                    ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                     '-show_entries', f'stream={field}',
                     '-of', 'default=noprint_wrappers=1:nokey=1', self.source],
                    capture_output=True, text=True, timeout=10
                )
                return int(r.stdout.strip().splitlines()[0]) if r.returncode == 0 else None
            w, h = probe('width'), probe('height')
            self.width  = w or 1280
            self.height = h or 720
        except:
            self.width, self.height = 1280, 720

        try:
            self.ffmpeg_process = subprocess.Popen(
                ['ffmpeg', '-re', '-i', self.source,
                 '-f', 'image2pipe', '-pix_fmt', 'bgr24', '-vcodec', 'rawvideo', '-an', '-'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8
            )
        except Exception as e:
            print(f"[VideoStream] Error ffmpeg: {e}, usando OpenCV")
            self.cap = cv2.VideoCapture(self.source)

    def _update(self):
        frame_delay = 1.0 / self.fps
        while not self.stopped and not self.finished:
            start = time.time()
            frame = self._read_frame()
            if frame is not None:
                self.consecutive_errors = 0
                if self.frame_queue.full():
                    try: self.frame_queue.get_nowait()
                    except: pass
                self.frame_queue.put(frame)
                self.frame_count += 1
                elapsed = time.time() - self.start_time
                if elapsed > 0:
                    self.current_fps = self.frame_count / elapsed
            elif not self.finished:
                self.consecutive_errors += 1
                if self.consecutive_errors >= self.MAX_ERRORS:
                    print(f"[VideoStream] Demasiados errores consecutivos. Asumiendo caída de stream: {self.source}")
                    self.finished = True
                    self.has_error = True
                    break
                time.sleep(0.1)
                continue

            elapsed_frame = time.time() - start
            if elapsed_frame < frame_delay:
                time.sleep(frame_delay - elapsed_frame)

    def _read_frame(self):
        if self.ffmpeg_process:
            return self._read_hls_frame()
        elif self.cap:
            ret, frame = self.cap.read()
            if not ret:
                return None
            return frame
        return None

    def _read_hls_frame(self):
        width, height = getattr(self, 'width', 1280), getattr(self, 'height', 720)
        try:
            raw = self.ffmpeg_process.stdout.read(width * height * 3)
            if len(raw) != width * height * 3:
                if self.cap is None:
                    self.cap = cv2.VideoCapture(self.source)
                ret, frame = self.cap.read() if self.cap else (False, None)
                return frame if ret else None
            return np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3))
        except:
            return None

    def read(self):
        return self.frame_queue.get() if not self.frame_queue.empty() else None

    def stop(self):
        self.stopped = True
        if self.thread: self.thread.join(timeout=2.0)
        if self.cap: self.cap.release()
        if self.ffmpeg_process:
            self.ffmpeg_process.terminate()
            try:
                self.ffmpeg_process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self.ffmpeg_process.kill()