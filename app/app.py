import sys
import time
import os
import glob
import threading
import traceback
from datetime import datetime

# Fix encoding
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import csv
import io
import cv2
import numpy as np
import torch
from flask import Flask, render_template, jsonify, request, send_from_directory, abort, Response
from flask_socketio import SocketIO, emit
from flask_cors import CORS

_START_TIME = time.time()

def log(msg, icon=''):
    elapsed = time.time() - _START_TIME
    prefix  = f"{icon} " if icon else ""
    text = f"[{elapsed:6.1f}s] {prefix}{msg}"
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode('ascii', errors='replace').decode('ascii'))


log("Sistema de Detección de Cascos", "🚀")


# PATCH TORCH.LOAD
_orig_load = torch.load
def _patched_load(*a, **kw):
    kw.setdefault('weights_only', False)
    return _orig_load(*a, **kw)
torch.load = _patched_load

# Asegurar que el directorio de la app esté en sys.path
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from core.video_processor import VideoStream
from core.detector import MotorcycleDetector
from core.classifier import HelmetClassifier
from core.utils import load_config
from data.database import Database
from data.models import Metrics, Detection, Camera

# CONFIG
log("Cargando configuración...", "📦")
config = load_config('config/config.yaml')
log(f"  {len(config.get('cameras', []))} cámaras configuradas")

# FLASK
app = Flask(__name__, static_folder='../static', template_folder='../static')
app.config['SECRET_KEY'] = 'motorcycle-helmet-detection-secret'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

import logging as _logging
if not config.get('logging', {}).get('access_logs', False):
    _logging.getLogger('werkzeug').disabled = True
    _logging.getLogger('werkzeug').setLevel(_logging.ERROR)

# BASE DE DATOS
log("Inicializando base de datos...", "🗄️")
db_path = config.get('paths', {}).get('database', 'data/detections.db')
db = Database(db_path=db_path)
db.clear_all_data()

# Limpieza inicial de archivos (solo ocurre al levantar la app)
crops_dir = os.path.abspath(config.get('paths', {}).get('crops_dir', 'crops'))
log("Limpiando archivos de ejecuciones anteriores...", "🧹")
for pattern in [
    f'{crops_dir}/cam_*/*/*/*.jpg',
    f'{crops_dir}/cam_*/*/*.jpg',
    f'{crops_dir}/cam_*/*/*/*.txt',
    f'{crops_dir}/cam_*/*/*.txt'
]:
    for f in glob.glob(pattern):
        try: os.remove(f)
        except: pass
os.makedirs(crops_dir, exist_ok=True)

# ESTADO GLOBAL
camera_metrics  = {}
camera_threads  = {}
stop_processing = False
current_mode    = None           # 'live' | 'file' | None
active_cameras  = 0              # Contador de cámaras activas en procesamiento
active_cameras_lock = threading.Lock()
camera_error_flags  = set()
import queue
io_queue = queue.Queue()

def io_worker():
    while True:
        task = io_queue.get()
        if task is None:
            break
        try:
            task()
        except Exception as e:
            print(f"IO worker error: {e}")
        io_queue.task_done()

threading.Thread(target=io_worker, daemon=True).start()

# Setup cameras
cameras_list = []
for cam_cfg in config.get('cameras', []):
    cam = Camera(
        id=cam_cfg['id'], name=cam_cfg['name'], source=cam_cfg['source'],
        lat=cam_cfg['lat'], lng=cam_cfg['lng']
    )
    cameras_list.append(cam)

log(f"  {len(cameras_list)} cámaras")

# MODELOS
log(f"Cargando clasificador global compartido...", "🤖")
camera_detectors = {}
global_classifier = None
try:
    global_classifier = HelmetClassifier(config['models']['classification'])
    
    log(f"Cargando un detector por cada cámara...", "🤖")
    for cam in cameras_list:
        camera_detectors[cam.id] = MotorcycleDetector(config, classifier=global_classifier)
    log("Todos los modelos listos", "✅")
except Exception as e:
    log(f"Error cargando modelos: {e}", "❌")
    raise SystemExit(1)


# FUNCIONES DE CONTROL

def _cleanup_all():
    """Limpia estado volátil: métricas y detector."""
    global camera_metrics
    with active_cameras_lock:
        global active_cameras
        active_cameras = 0
    camera_error_flags.clear()
    camera_metrics = {}
    for cam in cameras_list:
        camera_metrics[cam.id] = Metrics(camera_id=cam.id)
    for d in camera_detectors.values():
        d.reset()
    log("Métricas volátiles reiniciadas", "🧹")


def _stop_cameras():
    """Detiene todos los threads de cámaras activos y espera que finalicen."""
    global stop_processing, camera_threads, active_cameras
    stop_processing = True
    for cam_id, t in camera_threads.items():
        if t.is_alive():
            t.join(timeout=5.0)
            log(f"  Thread cam {cam_id} detenido", "⏹️")
    camera_threads = {}
    with active_cameras_lock:
        active_cameras = 0
    log("Todos los threads detenidos", "⏹️")


def _start_cameras(cameras):
    """Inicia threads de procesamiento para las cámaras indicadas."""
    global stop_processing, camera_threads, active_cameras
    stop_processing = False
    with active_cameras_lock:
        active_cameras = len(cameras)
    log(f"Iniciando {len(cameras)} cámaras...", "📡")
    for camera in cameras:
        camera_metrics[camera.id] = Metrics(camera_id=camera.id)
        t_icon = "📡"
        log(f"  {t_icon} Cam {camera.id}: {camera.name}")
        t = threading.Thread(target=process_camera, args=(camera,), daemon=True)
        t.start()
        camera_threads[camera.id] = t
        time.sleep(1)


# PROCESAMIENTO POR CÁMARA

def process_camera(camera):
    global stop_processing, active_cameras
    cam_id   = camera.id
    cam_name = camera.name

    crops_dir = config.get('paths', {}).get('crops_dir', 'crops')
    os.makedirs(f"{crops_dir}/cam_{cam_id}", exist_ok=True)

    PROCESS_INTERVAL = config['detection'].get('process_interval', 1.0)

    while not stop_processing:
        if cam_id in camera_error_flags:
            log(f"Cam {cam_id} abortada por error en frontend", "🛑")
            break

        log(f"Cam {cam_id} ({cam_name}) iniciando stream...", "📹")
        stream = None
        try:
            stream = VideoStream(
                source=camera.source,
                fps=config['video']['fps'],
                buffer_size=config['video']['buffer_size']
            ).start()

            time.sleep(2.0)
            stream_is_healthy = False
            last_process_time = 0
            frame_read_count  = 0
            interval_counter  = 0
            start_playback_time = time.time()

            while not stop_processing:
                if cam_id in camera_error_flags:
                    log(f"Cam {cam_id} abortada por error en frontend", "🛑")
                    break

                # Fin de archivo
                if stream.finished:
                    if getattr(stream, 'has_error', False):
                        log(f"Cam {cam_id} ({cam_name}): el stream backend falló", "❌")
                        raise Exception("El stream backend falló (has_error=True)")
                    else:
                        log(f"Cam {cam_id} ({cam_name}): video finalizado", "🏁")
                        break

                frame = stream.read()
                if frame is None:
                    time.sleep(0.01)
                    continue

                if not stream_is_healthy:
                    stream_is_healthy = True
                    socketio.emit('camera_processing', {'cam_id': cam_id})
                    log(f"Cam {cam_id}: procesando (cada {PROCESS_INTERVAL}s)", "▶️")

                frame_read_count += 1

                # Usar intervalo de tiempo real para decidir cuándo analizar
                should_process = (time.time() - last_process_time >= PROCESS_INTERVAL)

                if not should_process:
                    continue

                last_process_time = time.time()
                interval_counter += 1
                ts = int(time.time())

                t_start = time.time()
                detections = camera_detectors[cam_id].process_frame(frame, cam_id=cam_id, interval_counter=interval_counter)
                t_end = time.time()
                latency_ms = (t_end - t_start) * 1000.0

                raw_dets          = detections['raw_detections']
                duplicate_riders  = detections['duplicate_riders']
                classified_riders = detections['classified_riders']
                riders_ready      = detections['riders_ready_to_process']
                all_tracking_crops = detections.get('all_tracking_crops', [])

                # Log if activity
                if len(raw_dets) > 0 or len(duplicate_riders) > 0 or len(classified_riders) > 0 or len(riders_ready) > 0:
                    n_motos   = sum(1 for d in raw_dets if 'moto' in d[5].lower() or 'motor' in d[5].lower())
                    n_cabezas = sum(1 for d in raw_dets if 'cabeza' in d[5].lower() or 'torso' in d[5].lower() or 'head' in d[5].lower())
                    print(f"  [Cam {cam_id}|{interval_counter}] "
                          f"Latencia modelo detección: {latency_ms:.1f}ms | "
                          f"Brutas: {len(raw_dets)} (🏍 motos: {n_motos} | 👤 cabezas: {n_cabezas}) | "
                          f"Ya trackeada: {len(duplicate_riders)} | "
                          f"Clasificadas: {len(classified_riders)}")

                # PERSISTENCIA Y ALERTAS
                crops_dir = config.get('paths', {}).get('crops_dir', 'crops')
                crops_base = f"{crops_dir}/cam_{cam_id}"
                
                save_crops_config = config.get('save_crops', {})
                save_tracking = save_crops_config.get('tracking', False)
                save_motos = save_crops_config.get('motos', True)
                save_cabezas = save_crops_config.get('cabezas', True)
                
                # Guardar crops de tracking de manera asíncrona
                tracking_dir = os.path.join(crops_base, "tracking")
                if save_tracking:
                    os.makedirs(tracking_dir, exist_ok=True)
                for tcrop in all_tracking_crops:
                    tk_id = tcrop['track_id']
                    tk_status = tcrop['status']
                    tk_img = tcrop['moto_crop']
                    if tk_img is not None and save_tracking:
                        tk_cv2 = cv2.cvtColor(np.array(tk_img), cv2.COLOR_RGB2BGR)
                        tk_filename = f"f{interval_counter}_trk{tk_id}_{tk_status}.jpg"
                        tk_path = os.path.join(tracking_dir, tk_filename)
                        io_queue.put(lambda p=tk_path, img=tk_cv2: cv2.imwrite(p, img))
                        
                    tk_report = tcrop.get('report_text')
                    if tk_report and save_tracking:
                        report_filename = f"trk{tk_id}_report.txt"
                        report_path = os.path.join(tracking_dir, report_filename)
                        io_queue.put(lambda p=report_path, txt=tk_report: open(p, 'w', encoding='utf-8').write(txt))
                
                for rd in riders_ready:
                    x1, y1, x2, y2 = rd['bbox']
                    helmet_status  = rd['helmet_status']
                    helmet_conf    = rd['helmet_confidence']
                    pseudo_id      = rd['track_id']

                    # Sync DB insert
                    db.insert_detection(Detection(
                        timestamp=time.time(),
                        bbox=[int(x1), int(y1), int(x2), int(y2)],
                        class_name='rider',
                        confidence=rd['detection_conf'],
                        helmet_status=helmet_status,
                        helmet_confidence=float(helmet_conf),
                        camera_id=cam_id
                    ))

                    crop_folder = os.path.join(crops_base, "motos", helmet_status)
                    
                    # No guardar "pendientes" en la carpeta de motos finales
                    is_pending = helmet_status.startswith('pendiente')
                    should_save_moto = save_motos and not is_pending

                    if should_save_moto:
                        os.makedirs(crop_folder, exist_ok=True)
                        
                    crop_filename = f"moto_f{interval_counter}_{pseudo_id}.jpg"
                    crop_rel_path = f"cam_{cam_id}/motos/{helmet_status}/{crop_filename}"
                    crop_path_unix = crop_rel_path.replace('\\', '/')
                    crop_url = f"/crops/{crop_path_unix}"

                    if rd.get('crop_image') is not None:
                        crop_cv2 = cv2.cvtColor(np.array(rd['crop_image']), cv2.COLOR_RGB2BGR)
                        
                        # Dibujar bounding boxes de cabezas sobre el crop de la moto
                        for cab in rd.get('cabezas', []):
                            cx1, cy1, cx2, cy2 = cab['bbox']
                            # Trasladar coordenadas al crop (mx1=x1, my1=y1)
                            cx1_local = int(cx1 - x1)
                            cy1_local = int(cy1 - y1)
                            cx2_local = int(cx2 - x1)
                            cy2_local = int(cy2 - y1)
                            
                            c_status = cab.get('helmet_status', helmet_status)
                            color = (0, 255, 0) if 'con' in c_status.lower() else (0, 0, 255)
                            cv2.rectangle(crop_cv2, (cx1_local, cy1_local), (cx2_local, cy2_local), color, 2)
                            
                        if should_save_moto:
                            crop_path = os.path.join(crop_folder, crop_filename)
                            txt_path = os.path.join(crop_folder, "debug.txt")
                            cabezas_info = " | ".join([f"{cab.get('helmet_status', helmet_status)} {cab['bbox']}" for cab in rd.get('cabezas', [])])
                            txt_line = f"{crop_filename} - Track ID: {pseudo_id} - Conf: {helmet_conf:.2f} - Cabezas: {cabezas_info}\n"
                            
                            def _save_moto_and_txt(p=crop_path, img=crop_cv2, t_p=txt_path, t_line=txt_line):
                                cv2.imwrite(p, img)
                                with open(t_p, 'a', encoding='utf-8') as f:
                                    f.write(t_line)
                            
                            io_queue.put(_save_moto_and_txt)

                    # Guardar además recortes individuales de cada cabeza asociada
                    for i_c, cab in enumerate(rd.get('cabezas', [])):
                        if cab.get('crop_image') is not None and save_cabezas:
                            c_status = cab.get('helmet_status', helmet_status)
                            c_folder = os.path.join(crops_base, "cabezas", c_status)
                            os.makedirs(c_folder, exist_ok=True)
                            cab_cv2 = cv2.cvtColor(np.array(cab['crop_image']), cv2.COLOR_RGB2BGR)
                            cab_path = os.path.join(c_folder, f"cabeza_f{interval_counter}_{pseudo_id}_{i_c}.jpg")
                            io_queue.put(lambda p=cab_path, img=cab_cv2: cv2.imwrite(p, img))

                    if 'sin' in helmet_status.lower() and not helmet_status.startswith('pendiente'):
                        db.insert_violation(
                            [x1, y1, x2, y2, rd['detection_conf'], helmet_status, helmet_conf],
                            camera_id=cam_id,
                            crop_path=crop_rel_path
                        )
                        socketio.emit('violation_detected', {
                            'type':        helmet_status,
                            'confidence':  float(helmet_conf),
                            'timestamp':   time.time(),
                            'camera_id':   cam_id,
                            'camera_name': cam_name,
                            'track_id':    pseudo_id,
                            'crop_path':   crop_rel_path,
                            'crop_url':    crop_url,
                            'bbox':        [int(x1), int(y1), int(x2), int(y2)]
                        })

                    if not helmet_status.startswith('pendiente'):
                        metrics = camera_metrics[cam_id]
                        metrics.total_riders += 1
                        if 'con' in helmet_status.lower():
                            metrics.riders_with_helmet += 1
                        else:
                            metrics.riders_without_helmet += 1
                        metrics.update_compliance()
                        socketio.emit('metrics_update', metrics.to_dict())

            if stream:
                stream.stop()
            
            # Si rompió el inner loop normalmente (ej video file terminó, o frontend lo detuvo)
            break

        except Exception as e:
            print(f"[Cam {cam_id}] ❌ ERROR: {e}")
            traceback.print_exc()
            if stream:
                stream.stop()
            
            log(f"Cam {cam_id}: reconectando en 3s...", "🔄")
            socketio.emit('camera_reconnecting', {'cam_id': cam_id})
            time.sleep(3.0)
            continue

    log(f"Cam {cam_id} ({cam_name}): stream detenido", "⏹️")
    _on_camera_finished(cam_id, cam_name, is_error=False)


def _on_camera_finished(cam_id, cam_name, is_error=False):
    """Callback cuando una cámara termina su procesamiento."""
    global active_cameras
    
    if is_error:
        socketio.emit('camera_error', {'cam_id': cam_id, 'message': 'Desconectado'})
        log(f"Cam {cam_id} ({cam_name}): notificado error al frontend", "📤")

    with active_cameras_lock:
        active_cameras -= 1
        remaining = active_cameras

    if remaining <= 0:
        log("Todas las cámaras finalizaron", "🏁")


# RUTAS HTTP

def reload_cameras():
    global config, cameras_list
    try:
        new_config = load_config('config/config.yaml')
        config.update(new_config)
    except Exception as e:
        log(f"Error recargando config: {e}", "❌")
        return
        
    new_list = []
    for cam_cfg in config.get('cameras', []):
        cam = Camera(
            id=cam_cfg['id'], name=cam_cfg['name'], source=cam_cfg['source'],
            lat=cam_cfg['lat'], lng=cam_cfg['lng']
        )
        new_list.append(cam)
    cameras_list = new_list
    
    for cam in cameras_list:
        if cam.id not in camera_detectors:
            camera_detectors[cam.id] = MotorcycleDetector(config, classifier=global_classifier)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/cameras')
def get_cameras():
    reload_cameras()
    return jsonify([cam.to_dict() for cam in cameras_list])

@app.route('/api/start', methods=['POST'])
def start_processing_endpoint():
    global current_mode
    mode = 'live'
    
    reload_cameras()
    cameras_to_start = cameras_list

    if not cameras_to_start:
        return jsonify({'error': 'No hay cámaras configuradas. Agregá cámaras en config/config.yaml.'}), 404

    # Si ya hay algo corriendo, detener primero
    if camera_threads:
        _stop_cameras()

    _cleanup_all()
    current_mode = mode
    _start_cameras(cameras_to_start)

    return jsonify({
        'status': 'ok',
        'mode': mode,
        'cameras': [c.to_dict() for c in cameras_to_start]
    })

@app.route('/api/stop', methods=['POST'])
def stop_processing_endpoint():
    global current_mode
    _stop_cameras()
    _cleanup_all()
    current_mode = None
    return jsonify({'status': 'stopped'})

@app.route('/api/shutdown', methods=['POST'])
def shutdown_endpoint():
    log("Iniciando apagado del servidor...", "🛑")
    import threading
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return jsonify({'status': 'shutting_down'})

@app.route('/api/metrics/<time_range>')
def get_metrics_by_time(time_range):
    time_map = {'5min': 5, '15min': 15, '30min': 30, '1hour': 60}
    if time_range not in time_map:
        return jsonify({'error': 'Invalid time range'}), 400
    start_time = time.time() - (time_map[time_range] * 60)
    camera_id  = request.args.get('camera_id', None, type=int)
    violations = db.get_violations_since(start_time, camera_id=camera_id)
    con   = sum(1 for v in violations if 'con' in v['helmet_status'].lower())
    sin   = sum(1 for v in violations if 'sin' in v['helmet_status'].lower())
    total = con + sin
    return jsonify({
        'time_range':            time_range,
        'riders_with_helmet':    con,
        'riders_without_helmet': sin,
        'total_riders':          total,
        'compliance_rate':       round((con / total * 100) if total > 0 else 0, 2),
        'camera_id':             camera_id
    })

@app.route('/api/map/heatmap')
def get_map_heatmap():
    minutes = {'5min': 5, '15min': 15, '30min': 30, '1hour': 60}.get(
        request.args.get('range', '1hour'), 60)
    return jsonify(db.get_heatmap_data(
        time.time() - (minutes * 60), [c.to_dict() for c in cameras_list]))

@app.route('/api/violations')
def get_violations():
    return jsonify(db.get_recent_violations(
        limit=50, camera_id=request.args.get('camera_id', None, type=int)))

@app.route('/crops/<path:filename>')
def serve_crop(filename):
    # Secure against path traversal using send_from_directory
    if filename.startswith('crops/') or filename.startswith('crops\\'):
        filename = filename[6:]
    return send_from_directory(crops_dir, filename)

@app.route('/api/stats/dashboard')
@app.route('/api/dashboard/stats')
def get_dashboard_stats():
    stats = db.get_dashboard_stats(cameras_list)
    return jsonify({
        'success': True,
        'status': 'ok',
        'summary': {
            'total_violations': stats.get('total_violations', 0),
            'total_detections': stats.get('total_detections', 0),
            'compliance_rate': stats.get('compliance_rate', 0.0)
        },
        'total_violations': stats.get('total_violations', 0),
        'total_detections': stats.get('total_detections', 0),
        'compliance_rate': stats.get('compliance_rate', 0.0),
        'by_camera': stats.get('by_camera', []),
        'by_hour': stats.get('by_hour', [])
    })

@app.route('/api/violations/export')
@app.route('/api/reports/csv')
def export_violations_csv():
    camera_id = request.args.get('camera_id', type=int)
    violations = db.get_violations_for_export(camera_id=camera_id)

    cam_map = {}
    for c in cameras_list:
        cid = c.id if hasattr(c, 'id') else c.get('id')
        cname = c.name if hasattr(c, 'name') else c.get('name', f"Cámara {cid}")
        cam_map[cid] = cname

    output = io.StringIO()
    # UTF-8 BOM (\ufeff) para compatibilidad con Microsoft Excel en Windows
    output.write('\ufeff')
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL, lineterminator='\r\n')

    writer.writerow([
        'id',
        'timestamp',
        'datetime',
        'camera_id',
        'camera_name',
        'helmet_status',
        'confidence',
        'helmet_confidence',
        'image_path'
    ])

    def sanitize(val):
        if val is None:
            return ''
        s = str(val)
        if s and (s[0] in ('=', '+', '-', '@') or (s.lstrip('\t\r ') and s.lstrip('\t\r ')[0] in ('=', '+', '-', '@'))):
            return f"'{s}"
        return s

    for v in violations:
        cid = v.get('camera_id', 0)
        cname = cam_map.get(cid, f"Cámara {cid}")
        crop = v.get('crop_path') or v.get('image_path') or ''
        status = v.get('helmet_status') or 'sin_casco'
        conf = f"{float(v.get('confidence') or 0.0):.2f}"
        h_conf = f"{float(v.get('helmet_confidence') or 0.0):.2f}"

        writer.writerow([
            sanitize(v.get('id', '')),
            sanitize(v.get('timestamp', '')),
            sanitize(v.get('datetime', '')),
            sanitize(cid),
            sanitize(cname),
            sanitize(status),
            sanitize(conf),
            sanitize(h_conf),
            sanitize(crop)
        ])

    csv_data = output.getvalue().encode('utf-8')
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"infractions_export_{timestamp_str}.csv"

    response = Response(csv_data, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response



# WEBSOCKET

@socketio.on('connect')
def handle_connect():
    emit('connected', {'status': 'ok'})

@socketio.on('disconnect')
def handle_disconnect():
    pass


# ARRANQUE
# NO se inicia procesamiento automático.
# El usuario elige el modo desde la interfaz web, que llama a POST /api/start.

if __name__ == '__main__':
    log("Servidor en modo de espera (sin procesamiento automático)", "⏳")
    log(f"Abrir http://{config['server']['host']}:{config['server']['port']}", "🌐")
    
    socketio.run(app,
                 host=config['server']['host'],
                 port=config['server']['port'],
                 debug=config['server']['debug'],
                 use_reloader=False)