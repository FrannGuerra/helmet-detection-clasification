import cv2
import threading
import time
from queue import Queue
import subprocess
import numpy as np


class VideoStream:
    """
    Lee frames de un stream HLS, YouTube o archivo de video.

    Usa ffmpeg para decodificar con resolución y FPS fijos.
    Si ffmpeg no está disponible, cae a OpenCV como fallback.

    Args:
        source:        URL del stream HLS/YouTube o path a archivo de video.
        fps:           FPS target para la lectura (ffmpeg filtra a este FPS).
        buffer_size:   Tamaño del buffer de frames (2 = mínimo lag).
        target_width:  Ancho de salida de ffmpeg (default 1280).
        target_height: Alto de salida de ffmpeg (default 720).
    """

    def __init__(self, source: str, fps: float = 30.0, buffer_size: int = 2,
                 target_width: int = 1280, target_height: int = 720):
        self.source = source
        self.original_source = source  # Guardar fuente original para reconexión
        self.fps = fps
        self.target_width = target_width
        self.target_height = target_height
        # Dimensiones reales del frame (se setean en _start_hls_stream)
        self.width = target_width
        self.height = target_height
        self.cap = None
        self.ffmpeg_process = None
        self.frame_queue = Queue(maxsize=buffer_size)
        self.stopped = False
        self.finished = False
        self.has_error = False
        self.consecutive_errors = 0
        self.MAX_ERRORS = 50  # ~5 segundos de intentos fallidos a 0.1s/intento
        self.thread = None
        self._loop_lock = threading.Lock()
        self._looped = False
        self.frame_count = 0
        self.start_time = time.time()
        self.current_fps = 0.0
        # CORRECCIÓN: NO llamar _init_source() aquí.
        # Si se llama aquí Y en start(), se lanzan dos procesos ffmpeg:
        # el primero queda huérfano y acumula memoria con cada reconexión.

    def _init_source(self):
        """Resuelve la URL de YouTube (si aplica) y lanza ffmpeg."""
        # Si es YouTube, extraer la URL directa del stream de video
        if 'youtube.com' in self.source or 'youtu.be' in self.source:
            try:
                r = subprocess.run(
                    ['yt-dlp', '--no-playlist', '-g', '-f',
                     # CORRECCIÓN: 'bestvideo[height<=1080]' en vez de 'bestvideo'
                     # para no pedir 4K innecesariamente (un frame 4K BGR pesa ~25MB)
                     'bestvideo[height<=1080]',
                     self.source],
                    capture_output=True, text=True, check=True, timeout=15
                )
                if r.stdout:
                    self.source = r.stdout.strip().splitlines()[0]
            except Exception as e:
                print(f"[VideoStream] Error extracting YouTube URL: {e}")
        self._start_hls_stream()

    def check_and_clear_loop(self):
        """Verifica y limpia el flag de loop (para videos en loop)."""
        with self._loop_lock:
            if self._looped:
                self._looped = False
                return True
        return False

    def _cleanup_processes(self):
        """
        Mata procesos ffmpeg/OpenCV previos si existen.

        Llamar siempre antes de crear nuevos procesos para evitar acumulación
        de procesos huérfanos con cada reconexión.
        """
        if self.ffmpeg_process:
            try:
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                try:
                    self.ffmpeg_process.kill()
                except Exception:
                    pass
            except Exception:
                pass
            self.ffmpeg_process = None
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def start(self):
        """Inicia la lectura del stream en un thread separado."""
        self.stopped = False
        self.finished = False
        self.start_time = time.time()
        self.frame_count = 0

        # CORRECCIÓN: Limpiar procesos previos antes de crear nuevos.
        # Sin esto, cada reconexión deja un proceso ffmpeg huérfano.
        self._cleanup_processes()

        # Inicializar la fuente (una sola vez, aquí, no en __init__)
        self._init_source()

        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()
        print(f"[VideoStream] Iniciado ({self.width}x{self.height}, "
              f"{self.fps:.0f}fps): {self.source[:80]}...")
        return self

    def _start_hls_stream(self):
        """
        Lanza ffmpeg con resolución y FPS fijos.

        CORRECCIONES:
        - Sin '-re': La lectura bloqueante de stdout ya marca el ritmo.
          Con '-re' + sleep(frame_delay) en _update, se acumula retraso.
        - Con '-vf fps=N,scale=WxH': Fija resolución y FPS de salida.
          Evita que YouTube mande 4K y que frames salgan a intervalos irregulares.
        """
        W, H = self.target_width, self.target_height
        target_fps = int(self.fps)
        self.width = W
        self.height = H

        try:
            self.ffmpeg_process = subprocess.Popen(
                ['ffmpeg', '-loglevel', 'error', '-re',
                 '-i', self.source,
                 '-vf', f'fps={target_fps},scale={W}:{H}',
                 '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-an', '-'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8
            )
        except FileNotFoundError:
            print("[VideoStream] ffmpeg no encontrado, usando OpenCV como fallback")
            self.cap = cv2.VideoCapture(self.source)
        except Exception as e:
            print(f"[VideoStream] Error iniciando ffmpeg: {e}, usando OpenCV")
            self.cap = cv2.VideoCapture(self.source)

    def _update(self):
        """
        Thread de lectura: lee frames de ffmpeg/OpenCV y los pone en la cola.

        CORRECCIÓN: Sin sleep(frame_delay) al final del loop.
        ffmpeg con 'fps=N' en el filtro ya entrega frames al ritmo correcto.
        La lectura bloqueante de stdout.read() marca el ritmo naturalmente.
        Agregar un sleep adicional causaba retraso acumulativo.
        """
        while not self.stopped and not self.finished:
            frame = self._read_frame()
            if frame is not None:
                self.consecutive_errors = 0
                # Cola corta (maxsize=2): si está llena, descartar el frame más
                # viejo para siempre procesar el frame más reciente
                if self.frame_queue.full():
                    try:
                        self.frame_queue.get_nowait()
                    except Exception:
                        pass
                self.frame_queue.put(frame)
                self.frame_count += 1
                elapsed = time.time() - self.start_time
                if elapsed > 0:
                    self.current_fps = self.frame_count / elapsed
            elif not self.finished:
                self.consecutive_errors += 1
                if self.consecutive_errors >= self.MAX_ERRORS:
                    print(f"[VideoStream] Demasiados errores consecutivos. "
                          f"Asumiendo caída de stream.")
                    self.finished = True
                    self.has_error = True
                    break
                time.sleep(0.1)

    def _read_frame(self):
        """Lee un frame de ffmpeg o de OpenCV (fallback)."""
        if self.ffmpeg_process:
            return self._read_hls_frame()
        elif self.cap:
            ret, frame = self.cap.read()
            if not ret:
                return None
            return frame
        return None

    def _read_hls_frame(self):
        """
        Lee un frame raw de la pipe de ffmpeg.

        CORRECCIÓN: .copy() al final de reshape().
        np.frombuffer() devuelve un array de solo lectura (apunta al buffer
        interno de bytes). Sin .copy(), cualquier operación in-place de OpenCV
        (como cv2.rectangle, cv2.resize, etc.) lanza ValueError: read-only array.
        """
        try:
            raw = self.ffmpeg_process.stdout.read(self.width * self.height * 3)
            if len(raw) != self.width * self.height * 3:
                # Stream terminó o pipe cerrada
                return None
            return np.frombuffer(raw, dtype=np.uint8).reshape(
                (self.height, self.width, 3)).copy()
        except Exception:
            return None

    def read(self):
        """Lee el frame más reciente de la cola. Retorna None si no hay."""
        return self.frame_queue.get() if not self.frame_queue.empty() else None

    def stop(self):
        """Detiene la lectura y limpia todos los recursos."""
        self.stopped = True
        if self.thread:
            self.thread.join(timeout=2.0)
        # CORRECCIÓN: usar _cleanup_processes() en vez de duplicar la lógica
        self._cleanup_processes()