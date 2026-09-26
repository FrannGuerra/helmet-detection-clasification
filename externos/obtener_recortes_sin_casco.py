"""
CELDAS PARA NOTEBOOK KAGGLE:
!apt-get update -y
!apt-get install -y nodejs
!pip install -U yt-dlp ultralytics opencv-python pyyaml pillow
"""

import cv2
import time
import os
import sys
import threading
import yt_dlp
import yaml
from PIL import Image
from ultralytics import YOLO

# ==========================================
# ⚙️ CONFIGURACIÓN DEL SCRIPT
# ==========================================
CAMARAS = {
    "india_1": "https://www.youtube.com/watch?v=WSm_r0eNl1E",
    "india_2": "https://www.youtube.com/watch?v=UemFRPrl1hk",
}

# Detección automática del entorno (Kaggle vs Local)
ES_KAGGLE = os.path.exists('/kaggle/working')

# Configurar rutas según entorno
if ES_KAGGLE:
    BASE_OUTPUT_DIR = "/kaggle/working/dataset_sin_casco_minados"
    # IMPORTANTE: En Kaggle tenés que subir tus modelos como un dataset y poner la ruta acá:
    RUTA_DETECTOR = "/kaggle/input/mis-modelos-cascos/detector.pt"
    RUTA_CLASIFICADOR = "/kaggle/input/mis-modelos-cascos/clasificador.pt"
else:
    BASE_OUTPUT_DIR = "dataset_sin_casco_minados"
    RUTA_DETECTOR = "../detector.pt"
    RUTA_CLASIFICADOR = "../clasificador.pt"

INTERVALO_SEGUNDOS = 2.0      # Segundos entre procesamiento de frames
HORAS_EJECUCION = 1.0         # Cuántas horas dejar corriendo el minero
CONF_DETECTOR = 0.25          # Confianza mínima para detectar la cabeza
CONF_CLASIFICADOR = 0.50      # Confianza mínima para considerarlo "sin casco"

# ==========================================

stop_event = threading.Event()
clasificador = None
clasificador_lock = threading.Lock()

def obtener_url_real(url_original):
    if "youtube.com" in url_original or "youtu.be" in url_original:
        ydl_opts = {
            'format': 'bestvideo[height<=1080]/best[height<=1080]/best', 
            'quiet': True,    
            'noplaylist': True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url_original, download=False)
                return info['url']
        except Exception as e:
            print(f"⚠️ Error extrayendo link de YouTube: {e}")
            return None
    return url_original 

def normalizar_clase_casco(class_name):
    """Normaliza el nombre de la clase para que siempre sea con_casco o sin_casco"""
    lower = str(class_name).lower()
    if 'con' in lower and 'casco' in lower:
        return 'con_casco'
    if 'sin' in lower and 'casco' in lower:
        return 'sin_casco'
    return lower

def procesar_camara(nombre_cam, url_stream):
    dir_salida = os.path.join(BASE_OUTPUT_DIR, nombre_cam)
    os.makedirs(dir_salida, exist_ok=True)
    
    print(f"[{nombre_cam}] 🚀 Inicializando detector local...")
    detector_local = YOLO(RUTA_DETECTOR)
    
    HEAD_CLASS_NAMES = ['cabeza_torso', 'cabeza', 'head', 'torso', 'person']
    head_class_ids = [k for k, v in detector_local.names.items() if v.lower() in HEAD_CLASS_NAMES]
    if not head_class_ids:
        head_class_ids = [1]
    
    intentos_conexion = 0
    last_saved_time = 0
    saved_count = 0
    cap = None
    
    print(f"[{nombre_cam}] 🎬 Empezando captura de stream...")
    
    while not stop_event.is_set():
        try:
            if cap is None or not cap.isOpened():
                if intentos_conexion > 0:
                    time.sleep(5)
                
                url_real = obtener_url_real(url_stream)
                if url_real is None:
                    intentos_conexion += 1
                    time.sleep(10)
                    continue

                cap = cv2.VideoCapture(url_real)
                intentos_conexion += 1
                continue 

            ret, frame = cap.read()
            if not ret:
                cap.release()
                cap = None
                continue
            
            current_time = time.time()
            if current_time - last_saved_time >= INTERVALO_SEGUNDOS:
                last_saved_time = current_time 
                
                results = detector_local(frame, conf=CONF_DETECTOR, verbose=False)
                if not results or not results[0].boxes:
                    continue
                    
                boxes = results[0].boxes
                
                for i in range(len(boxes)):
                    cls_id = int(boxes.cls[i].item())
                    if cls_id in head_class_ids:
                        x1, y1, x2, y2 = map(int, boxes.xyxy[i].tolist())
                        
                        h, w = frame.shape[:2]
                        x1, y1 = max(0, x1), max(0, y1)
                        x2, y2 = min(w, x2), min(h, y2)
                        
                        if x2 - x1 < 10 or y2 - y1 < 10:
                            continue
                            
                        crop_bgr = frame[y1:y2, x1:x2]
                        crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
                        pil_img = Image.fromarray(crop_rgb)
                        
                        with clasificador_lock:
                            res_cls = clasificador(pil_img, imgsz=64, verbose=False)
                            if res_cls and res_cls[0].probs is not None:
                                top1_idx = int(res_cls[0].probs.top1)
                                conf = float(res_cls[0].probs.top1conf)
                                raw_name = clasificador.names.get(top1_idx, '')
                                status = normalizar_clase_casco(raw_name)
                            else:
                                status, conf = 'desconocido', 0.0
                        
                        if 'sin_casco' in status and conf >= CONF_CLASIFICADOR:
                            filename = f"minado_{int(time.time()*1000)}.jpg"
                            filepath = os.path.join(dir_salida, filename)
                            cv2.imwrite(filepath, crop_bgr)
                            saved_count += 1
                            
                print(f"[{nombre_cam}] ⛏️ Minados: {saved_count}", end='\r')

        except Exception as e:
            print(f"\n[{nombre_cam}] ⚠️ Error: {e}")
            if cap:
                cap.release()
                cap = None
            time.sleep(5)
            
    if cap:
        cap.release()
    print(f"\n[{nombre_cam}] ✅ Finalizado. Cabezas sin casco extraídas: {saved_count}")

def main():
    global clasificador
    
    print(f"📁 Los recortes se guardarán en: {os.path.abspath(BASE_OUTPUT_DIR)}")
    
    # Resolver modelo si estamos en local usando config
    global RUTA_DETECTOR, RUTA_CLASIFICADOR
    if not ES_KAGGLE:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, 'config', 'config.yaml')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
                det_model_name = cfg.get('models', {}).get('detection', 'detector.pt')
                cls_model_name = cfg.get('models', {}).get('classification', 'clasificador.pt')
                RUTA_DETECTOR = os.path.join(base_dir, det_model_name)
                RUTA_CLASIFICADOR = os.path.join(base_dir, cls_model_name)
                
    if not os.path.exists(RUTA_DETECTOR) or not os.path.exists(RUTA_CLASIFICADOR):
        print(f"❌ Error: Faltan los modelos.")
        print(f" - Detector: {RUTA_DETECTOR}")
        print(f" - Clasificador: {RUTA_CLASIFICADOR}")
        return
        
    print("🚀 Cargando Clasificador Global...")
    clasificador = YOLO(RUTA_CLASIFICADOR)
    
    hilos = []
    for nombre_cam, url in CAMARAS.items():
        hilo = threading.Thread(target=procesar_camara, args=(nombre_cam, url))
        hilo.start()
        hilos.append(hilo)
        time.sleep(1)
        
    print(f"⏳ Minando cabezas 'sin casco' durante {HORAS_EJECUCION} horas...")
    try:
        time.sleep(HORAS_EJECUCION * 3600)
    except KeyboardInterrupt:
        print("\n🛑 Interrupción manual detectada.")
        
    print("🛑 Deteniendo mineros...")
    stop_event.set()
    
    for hilo in hilos:
        hilo.join()
        
    print("✅ Minería completada con éxito.")

if __name__ == '__main__':
    main()
