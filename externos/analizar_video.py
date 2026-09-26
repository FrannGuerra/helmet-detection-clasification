"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  ANALIZADOR DE VIDEO OFFLINE                                                 ║
║  Procesa un video .mp4 con el mismo pipeline que la app (Detector +          ║
║  Clasificador) y genera un resumen de resultados y crops organizados.        ║
╚══════════════════════════════════════════════════════════════════════════════╝

USO:
  python externos/analizar_video.py videos/demo.mp4
  python externos/analizar_video.py videos/demo.mp4 --intervalo 0.1   # analizar cada 100ms
  python externos/analizar_video.py videos/demo.mp4 --conf-det 0.5 --conf-cls 0.7

SALIDA:
  - Resumen en consola: totales con/sin casco, confianza promedio
  - Carpeta de crops: resultados/<nombre_video>/con_casco/ y sin_casco/
"""

import sys
import os
import time
import argparse
import subprocess
from pathlib import Path

import cv2
import numpy as np

# Asegurar encoding UTF-8 en Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Patch torch.load para PyTorch 2.6+
try:
    import torch
    _orig_load = torch.load
    def _patched_load(*a, **kw):
        kw.setdefault('weights_only', False)
        return _orig_load(*a, **kw)
    torch.load = _patched_load
except ImportError:
    pass

# Definir directorio raíz del proyecto para referencias absolutas
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Agregar app/ al path para importar los módulos del pipeline
_APP_DIR = os.path.join(_PROJECT_ROOT, 'app')
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from core.detector import MotorcycleDetector
from core.classifier import HelmetClassifier
from core.utils import load_config


# ── Configuración por defecto (se puede sobreescribir con args) ────────────────
CONFIG_PATH   = os.path.join(_PROJECT_ROOT, 'config', 'config.yaml')
OUTPUT_BASE   = Path(_PROJECT_ROOT) / 'resultados'
# ──────────────────────────────────────────────────────────────────────────────


def leer_video_ffmpeg(video_path: str):
    """
    Genera frames BGR desde un archivo de video usando FFmpeg como backend,
    igual que lo hace la app en VideoStream._read_hls_frame().
    Esto garantiza compatibilidad con cualquier formato que soporte FFmpeg.
    """
    # Detectar resolución del video con ffprobe
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height',
             '-of', 'csv=p=0', video_path],
            capture_output=True, text=True, timeout=10
        )
        partes = r.stdout.strip().split(',')
        width, height = int(partes[0]), int(partes[1])
    except Exception:
        # Fallback: usar OpenCV para detectar tamaño
        cap = cv2.VideoCapture(video_path)
        width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

    frame_size = width * height * 3

    proc = subprocess.Popen(
        ['ffmpeg', '-i', video_path,
         '-f', 'image2pipe', '-pix_fmt', 'bgr24', '-vcodec', 'rawvideo', '-an', '-'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8
    )

    while True:
        raw = proc.stdout.read(frame_size)
        if len(raw) != frame_size:
            break
        frame = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3)).copy()
        yield frame

    proc.stdout.close()
    proc.wait()


def guardar_crop(imagen_pil, output_dir: Path, nombre: str) -> None:
    """Guarda un crop PIL en disco como JPEG."""
    output_dir.mkdir(parents=True, exist_ok=True)
    import cv2
    import numpy as np
    arr = np.array(imagen_pil.convert('RGB'))
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(output_dir / nombre), bgr)


def imprimir_barra(frame_num: int, total_frames: int, start_time: float) -> None:
    """Barra de progreso simple en consola."""
    if total_frames <= 0:
        return
    pct    = frame_num / total_frames
    filled = int(40 * pct)
    bar    = '█' * filled + '░' * (40 - filled)
    elapsed = time.time() - start_time
    eta     = (elapsed / pct - elapsed) if pct > 0 else 0
    print(f'\r  [{bar}] {pct*100:.1f}%  frame {frame_num}/{total_frames}  ETA {eta:.0f}s', end='', flush=True)


def dibujar_anotaciones(frame: np.ndarray, riders: list) -> None:
    """Dibuja bounding boxes, textos y estados sobre el frame para el video de salida."""
    for rd in riders:
        x1, y1, x2, y2 = map(int, rd['bbox'])
        track_id = rd['track_id']
        status = str(rd['helmet_status'])
        conf = rd.get('helmet_confidence', 0.0)

        # Determinar color y texto principal (Motocicleta)
        if status.startswith('pendiente'):
            color = (0, 255, 255)  # Amarillo
            texto = f"[#{track_id}] Analizando..."
        elif 'con' in status.lower():
            color = (0, 255, 0)    # Verde
            texto = f"[#{track_id}] CON CASCO ({conf*100:.0f}%)"
        else:
            color = (0, 0, 255)    # Rojo
            texto = f"[#{track_id}] SIN CASCO ({conf*100:.0f}%)"

        # Dibujar caja de la motocicleta
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        # Dibujar fondo para el texto
        (w, h), _ = cv2.getTextSize(texto, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
        cv2.rectangle(frame, (x1, y1 - 25), (x1 + w, y1), color, -1)
        # Dibujar texto
        cv2.putText(frame, texto, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        # Dibujar cajitas interiores para las cabezas detectadas
        for cab in rd.get('cabezas', []):
            cx1, cy1, cx2, cy2 = map(int, cab['bbox'])
            c_status = str(cab.get('helmet_status', status))
            
            if c_status.startswith('pendiente'):
                c_color = (0, 255, 255)
            elif 'con' in c_status.lower():
                c_color = (0, 255, 0)
            else:
                c_color = (0, 0, 255)
                
            # Caja más fina para la cabeza
            cv2.rectangle(frame, (cx1, cy1), (cx2, cy2), c_color, 1)


def analizar(video_path: str, intervalo: float, conf_det: float, conf_cls: float, 
             video_salida: str = None, procesar_todo: bool = False) -> None:
    """
    Pipeline principal: lee el video frame a frame y lo pasa por el
    mismo Detector + Clasificador que usa la app en producción.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        print(f'\n  [ERROR] El archivo no existe: {video_path}')
        sys.exit(1)

    # Directorio de salida nombrado igual que el video (sin extensión)
    output_dir   = OUTPUT_BASE / video_path.stem
    dir_con      = output_dir / 'con_casco'
    dir_sin      = output_dir / 'sin_casco'
    dir_con.mkdir(parents=True, exist_ok=True)
    dir_sin.mkdir(parents=True, exist_ok=True)

    # Cargar configuración base y sobreescribir umbrales si el usuario los pasó
    config = load_config(CONFIG_PATH)
    config['detection']['confidence_threshold']     = conf_det
    config['classification']['confidence_threshold'] = conf_cls

    # Forzar procesar todo si hay video de salida, para que no salte frames
    if video_salida:
        procesar_todo = True

    sep = '═' * 62
    print(f'\n╔{sep}╗')
    print(f'║  ANALIZADOR DE VIDEO OFFLINE                                 ║')
    print(f'╚{sep}╝')
    print(f'\n  Video       : {video_path}')
    print(f'  Salida      : {output_dir.resolve()}')
    if procesar_todo:
        print(f'  Intervalo   : Procesando 100% de los frames (Ignorado)')
    else:
        print(f'  Intervalo   : cada {intervalo*1000:.0f}ms ({1/intervalo:.1f} FPS de análisis)')
    print(f'  Conf Det.   : {conf_det}   |   Conf Cls.: {conf_cls}\n')

    # Inicializar pipeline (igual que la app)
    print('  Cargando modelos...')
    detector = MotorcycleDetector(config)
    print('  Modelos listos. Iniciando análisis...\n')

    # Contar frames del video para la barra de progreso
    cap_probe = cv2.VideoCapture(str(video_path))
    total_frames = int(cap_probe.get(cv2.CAP_PROP_FRAME_COUNT))
    fps_video    = cap_probe.get(cv2.CAP_PROP_FPS) or 30.0
    v_width      = int(cap_probe.get(cv2.CAP_PROP_FRAME_WIDTH))
    v_height     = int(cap_probe.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap_probe.release()
    duracion_seg = total_frames / fps_video
    
    print(f'  Duración    : {duracion_seg:.1f}s  |  {total_frames} frames a {fps_video:.1f}fps')
    if procesar_todo:
        print(f'  A analizar  : {total_frames} frames (100% de los frames)\n')
    else:
        print(f'  A analizar  : ~{int(duracion_seg / intervalo)} frames (1 cada {intervalo*1000:.0f}ms)\n')

    # Inicializar VideoWriter si se pidió video de salida
    video_writer = None
    if video_salida:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        video_writer = cv2.VideoWriter(video_salida, fourcc, fps_video, (v_width, v_height))
        print(f'  Guardando video renderizado en: {video_salida}\n')

    # Contadores de resultados
    conteo = {'con_casco': 0, 'sin_casco': 0}
    confs  = {'con_casco': [], 'sin_casco': []}
    track_ids_con = []
    track_ids_sin = []
    riders_unicos = set()   # track_ids ya clasificados (no contar duplicados)
    crops_guardados = 0

    start_time    = time.time()
    frame_num     = 0
    last_analysis = 0.0
    interval_counter = 0

    for frame in leer_video_ffmpeg(str(video_path)):
        frame_num += 1
        now = time.time() - start_time

        # Respetar el intervalo de análisis si no se forzó procesar todo
        if not procesar_todo and (now - last_analysis < intervalo):
            continue
            
        last_analysis = now
        interval_counter += 1

        # Progreso
        if interval_counter % 10 == 0:
            imprimir_barra(frame_num, total_frames, start_time)

        # Procesar frame con el pipeline completo
        detections = detector.process_frame(frame, cam_id=1, interval_counter=interval_counter)
        riders_ready = detections.get('riders_ready_to_process', [])

        # Dibujar si hay video de salida
        if video_writer:
            # Combinar nuevos/pendientes con los ya clasificados (duplicate_riders)
            riders_para_dibujar = list(riders_ready)
            for dup in detections.get('duplicate_riders', []):
                tid = dup['track_id']
                if tid in detector.track_history:
                    hist = detector.track_history[tid]
                    # Buscar cabezas en raw_detections que caigan dentro de esta moto
                    cabezas_actuales = []
                    mx1, my1, mx2, my2 = dup['bbox']
                    for rd_raw in detections.get('raw_detections', []):
                        cls_name = rd_raw[5]
                        if 'cabeza' in cls_name or 'head' in cls_name or 'torso' in cls_name:
                            cx1, cy1, cx2, cy2 = rd_raw[0:4]
                            # Verificar si la cabeza está dentro de la moto (overlap > 80%)
                            ix1, iy1 = max(cx1, mx1), max(cy1, my1)
                            ix2, iy2 = min(cx2, mx2), min(cy2, my2)
                            inter_area = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                            inner_area = (cx2 - cx1) * (cy2 - cy1)
                            if inner_area > 0 and (inter_area / inner_area) >= 0.8:
                                cabezas_actuales.append({
                                    'bbox': (cx1, cy1, cx2, cy2),
                                    'helmet_status': hist.get('final_status', 'desconocido')
                                })
                    
                    riders_para_dibujar.append({
                        'track_id': tid,
                        'bbox': dup['bbox'],
                        'helmet_status': hist.get('final_status', 'desconocido'),
                        'helmet_confidence': hist.get('final_confidence', 0.0),
                        'cabezas': cabezas_actuales
                    })
            dibujar_anotaciones(frame, riders_para_dibujar)
            video_writer.write(frame)

        for rd in riders_ready:
            track_id     = rd['track_id']
            helmet_status = rd['helmet_status']
            helmet_conf  = rd['helmet_confidence']

            # Ignorar estados pendientes (aún no clasificados)
            if str(helmet_status).startswith('pendiente'):
                continue

            # Ignorar duplicados (moto ya clasificada en frame anterior)
            if track_id in riders_unicos:
                continue
            riders_unicos.add(track_id)

            # Contabilizar e imprimir log en vivo
            if 'con' in helmet_status.lower():
                conteo['con_casco'] += 1
                confs['con_casco'].append(float(helmet_conf))
                track_ids_con.append(track_id)
                carpeta = dir_con
                print(f'\n  [+] Nuevo veredicto: Track #{track_id} -> CON CASCO (Conf: {helmet_conf:.2f})')
            else:
                conteo['sin_casco'] += 1
                confs['sin_casco'].append(float(helmet_conf))
                track_ids_sin.append(track_id)
                carpeta = dir_sin
                print(f'\n  [!] Nuevo veredicto: Track #{track_id} -> SIN CASCO (Conf: {helmet_conf:.2f})')

            # Guardar crop del motociclista
            if rd.get('crop_image') is not None:
                nombre_crop = f'trk{track_id}_f{interval_counter}_{helmet_status}.jpg'
                guardar_crop(rd['crop_image'], carpeta, nombre_crop)
                crops_guardados += 1

            # Guardar también crops de cabezas individuales
            for i_c, cab in enumerate(rd.get('cabezas', [])):
                if cab.get('crop_image') is not None:
                    c_status = cab.get('helmet_status', helmet_status)
                    c_folder = output_dir / 'cabezas' / c_status
                    nombre_cab = f'trk{track_id}_f{interval_counter}_cab{i_c}.jpg'
                    guardar_crop(cab['crop_image'], c_folder, nombre_cab)

    print()  # Salto de línea tras la barra de progreso

    if video_writer:
        video_writer.release()

    # ── Resumen Final ──────────────────────────────────────────────────────────
    total    = conteo['con_casco'] + conteo['sin_casco']
    pct_con  = (conteo['con_casco'] / total * 100) if total > 0 else 0
    pct_sin  = (conteo['sin_casco'] / total * 100) if total > 0 else 0
    avg_con  = sum(confs['con_casco']) / max(1, len(confs['con_casco'])) if confs['con_casco'] else 0
    avg_sin  = sum(confs['sin_casco']) / max(1, len(confs['sin_casco'])) if confs['sin_casco'] else 0
    elapsed  = time.time() - start_time

    print(f'\n╔{sep}╗')
    print(f'║  RESULTADOS                                                  ║')
    print(f'╚{sep}╝')
    print(f'\n  Video analizado : {video_path.name}')
    print(f'  Tiempo total    : {elapsed:.1f}s  ({interval_counter} frames procesados)\n')
    print(f'  ┌──────────────────────────────────────────────────┐')
    print(f'  │  Motociclistas únicos detectados : {total:<16d}  │')
    print(f'  │                                                  │')
    print(f'  │  🟢 CON CASCO: {conteo["con_casco"]:<5d}  ({pct_con:.1f}%)  conf. prom. {avg_con:.2f}  │')
    print(f'  │  🔴 SIN CASCO: {conteo["sin_casco"]:<5d}  ({pct_sin:.1f}%)  conf. prom. {avg_sin:.2f}  │')
    print(f'  └──────────────────────────────────────────────────┘')
    
    # Mostrar el orden en el que aparecieron
    print(f'\n  Orden de aparición (Track IDs):')
    if track_ids_con:
        print(f'    🟢 Con Casco: {", ".join(str(tid) for tid in track_ids_con)}')
    if track_ids_sin:
        print(f'    🔴 Sin Casco: {", ".join(str(tid) for tid in track_ids_sin)}')

    print(f'\n  Crops guardados : {crops_guardados}')
    print(f'  Carpeta salida  : {output_dir.resolve()}\n')

    if conteo['sin_casco'] == 0:
        print('  ✅ No se detectaron infracciones en este video.')
    else:
        print(f'  ⚠️  Se detectaron {conteo["sin_casco"]} motociclista(s) sin casco.')
    print()


def main():
    parser = argparse.ArgumentParser(
        description='Analiza un video .mp4 con el pipeline de detección de cascos.'
    )
    parser.add_argument('video', help='Ruta al archivo de video (ej: videos/demo.mp4)')
    parser.add_argument(
        '--intervalo', type=float, default=None,
        help='Segundos entre análisis de frames (default: detection.process_interval de config.yaml)'
    )
    parser.add_argument(
        '--conf-det', type=float, default=None,
        help='Umbral de confianza del detector (default: detection.confidence_threshold de config.yaml)'
    )
    parser.add_argument(
        '--conf-cls', type=float, default=None,
        help='Umbral de confianza del clasificador (default: classification.confidence_threshold de config.yaml)'
    )
    parser.add_argument(
        '--video-salida', type=str, default=None,
        help='Ruta para exportar un video renderizado (ej: videos/resultado.mp4)'
    )
    parser.add_argument(
        '--procesar-todo', action='store_true',
        help='Ignora el intervalo y procesa el 100%% de los frames (se activa automáticamente si hay --video-salida)'
    )
    args = parser.parse_args()

    # Leer TODOS los defaults desde config/config.yaml — nada hardcodeado en este script.
    # El config es la fuente de verdad única, igual que en la app.
    cfg = load_config(CONFIG_PATH)
    conf_det  = args.conf_det  if args.conf_det  is not None else cfg['detection']['confidence_threshold']
    conf_cls  = args.conf_cls  if args.conf_cls  is not None else cfg['classification']['confidence_threshold']
    intervalo = args.intervalo if args.intervalo is not None else cfg['detection']['process_interval']

    analizar(args.video, intervalo, conf_det, conf_cls, args.video_salida, args.procesar_todo)


if __name__ == '__main__':
    main()
