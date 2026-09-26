"""
CELDAS PARA NOTEBOOK KAGGLE:
!apt-get update -y
!apt-get install -y nodejs
!pip install -U yt-dlp ultralytics
"""

import cv2
import time
import os
import sys
import shutil
import threading
from datetime import datetime
import yt_dlp
from ultralytics import YOLO

# Configurar encoding UTF-8 en consola para Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ==========================================
# ⚙️ CONFIGURACIÓN MULTICÁMARA
# ==========================================
CAMARAS = {
    "vivo_1": "https://www.youtube.com/watch?v=UemFRPrl1hk",
    "vivo_2": "https://www.youtube.com/watch?v=WSm_r0eNl1E",
    "vivo_3": "https://www.youtube.com/watch?v=HdaWcBamcSA",
}

BASE_OUTPUT_DIR = "/kaggle/working/dataset_multicam"
INTERVALO_SEGUNDOS = 1.0  # Guardar como máximo 1 frame por segundo por cámara
HORAS_EJECUCION = 0.1     # Límite de tiempo en horas

print("🚀 Cargando modelo YOLOv8n para filtrado y pre-anotación...")
model_filtro = YOLO("yolov8n.pt")
yolo_lock = threading.Lock() # Candado para evitar que los 3 hilos choquen al predecir

stop_event = threading.Event()

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

def calcular_solapamiento(box1, box2):
    """Calcula el porcentaje de solapamiento entre dos cajas."""
    x_left = max(box1[0], box2[0])
    y_top = max(box1[1], box2[1])
    x_right = min(box1[2], box2[2])
    y_bottom = min(box1[3], box2[3])

    if x_right < x_left or y_bottom < y_top:
        return 0.0

    intersection_area = (x_right - x_left) * (y_bottom - y_top)
    box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])
    box2_area = (box2[2] - box2[0]) * (box2[3] - box2[1])
    
    return intersection_area / min(box1_area, box2_area)

def procesar_camara(nombre_cam, url_stream):
    dir_salida = os.path.join(BASE_OUTPUT_DIR, nombre_cam)
    os.makedirs(dir_salida, exist_ok=True)
    
    frames_guardados = 0
    intentos_conexion = 0
    last_saved_time = 0
    
    print(f"🎬 Iniciando captura y pre-anotación para: {nombre_cam}")
    cap = None
    
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
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                intentos_conexion += 1
                continue 

            ret, frame = cap.read()
            if not ret:
                cap.release()
                cap = None
                continue
            
            intentos_conexion = 0
            current_time = time.time()
            
            if current_time - last_saved_time >= INTERVALO_SEGUNDOS:
                last_saved_time = current_time 
                
                # Buscamos personas (clase 0) y motos (clase 3)
                with yolo_lock:
                    results = model_filtro.predict(source=frame, conf=0.25, classes=[0, 3], verbose=False, device='cpu')
                
                boxes = results[0].boxes
                if len(boxes) == 0:
                    continue
                
                motos = []
                personas = []
                
                for box in boxes:
                    cls_id = int(box.cls[0])
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    if cls_id == 3:  # Moto
                        motos.append([x1, y1, x2, y2])
                    elif cls_id == 0:  # Persona
                        personas.append([x1, y1, x2, y2])
                
                # Si no hay motos, ignoramos el frame
                if not motos:
                    continue

                h, w = frame.shape[:2]
                annotations = []
                
                for moto in motos:
                    merged_moto = moto.copy()
                    associated_persons = []
                    
                    for p in personas:
                        # Si hay un solapamiento significativo (> 10%)
                        if calcular_solapamiento(moto, p) > 0.1:
                            # Expandir la caja de la moto para incluir a la persona
                            merged_moto[0] = min(merged_moto[0], p[0])
                            merged_moto[1] = min(merged_moto[1], p[1])
                            merged_moto[2] = max(merged_moto[2], p[2])
                            merged_moto[3] = max(merged_moto[3], p[3])
                            associated_persons.append(p)
                    
                    # Si no hay persona sobre la moto (ej: estacionada), no la anotamos
                    if not associated_persons:
                        continue
                    
                    # Convertir a formato YOLO: clase x_centro y_centro ancho alto
                    mx1, my1, mx2, my2 = merged_moto
                    mx_center = ((mx1 + mx2) / 2) / w
                    my_center = ((my1 + my2) / 2) / h
                    m_width = (mx2 - mx1) / w
                    m_height = (my2 - my1) / h
                    
                    # CLASE 0: Moto (Unificada)
                    annotations.append(f"0 {mx_center:.6f} {my_center:.6f} {m_width:.6f} {m_height:.6f}")
                    
                    for p in associated_persons:
                        px1, py1, px2, py2 = p
                        # CLASE 1: Cabeza/Torso -> El 35% superior de la caja de la persona
                        head_y2 = py1 + (py2 - py1) * 0.35
                        
                        hx_center = ((px1 + px2) / 2) / w
                        hy_center = ((py1 + head_y2) / 2) / h
                        h_width = (px2 - px1) / w
                        h_height = (head_y2 - py1) / h
                        
                        annotations.append(f"1 {hx_center:.6f} {hy_center:.6f} {h_width:.6f} {h_height:.6f}")
                
                # Si generamos anotaciones, guardamos el par JPG y TXT
                if len(annotations) > 0:
                    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                    base_filename = os.path.join(dir_salida, f"{nombre_cam}_{timestamp_str}_{frames_guardados:05d}")
                    
                    # Guardar imagen
                    cv2.imwrite(base_filename + ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                    
                    # Guardar archivo de anotaciones (Formato YOLO)
                    with open(base_filename + ".txt", "w") as f:
                        f.write("\n".join(annotations) + "\n")
                        
                    frames_guardados += 1

        except Exception as e:
            if cap is not None:
                cap.release()
                cap = None
            time.sleep(5)

    if cap is not None:
        cap.release()
    print(f"🛑 [{nombre_cam}] Finalizado. Motos capturadas: {frames_guardados}")

def comprimir_dataset(directorio_origen):
    """
    Comprime el dataset generado en un archivo ZIP listo para subir a Roboflow.
    """
    if not os.path.exists(directorio_origen):
        print(f"⚠️ El directorio '{directorio_origen}' no existe, no se generó ZIP.")
        return None

    # Generar classes.txt para que Roboflow mapee los IDs automáticamente
    classes_path = os.path.join(directorio_origen, "classes.txt")
    try:
        with open(classes_path, "w") as f:
            f.write("moto\ncabeza_torso\n")
    except Exception as e:
        print(f"⚠️ No se pudo crear classes.txt: {e}")

    total_imagenes = 0
    total_txts = 0
    for root, _, files in os.walk(directorio_origen):
        total_imagenes += sum(1 for f in files if f.endswith('.jpg'))
        total_txts += sum(1 for f in files if f.endswith('.txt'))

    if total_imagenes == 0:
        print(f"⚠️ No se encontraron imágenes en '{directorio_origen}'. Omitiendo creación de ZIP.")
        return None

    abs_origen = os.path.abspath(directorio_origen)
    dir_padre = os.path.dirname(abs_origen)
    nombre_carpeta = os.path.basename(abs_origen)
    ruta_base_zip = os.path.join(dir_padre, f"{nombre_carpeta}_pre_anotado")

    print(f"\n📦 Comprimiendo {total_imagenes} imágenes y {total_txts} anotaciones en archivo ZIP...")
    try:
        archivo_zip = shutil.make_archive(
            base_name=ruta_base_zip,
            format='zip',
            root_dir=dir_padre,
            base_dir=nombre_carpeta
        )
        tamano_mb = os.path.getsize(archivo_zip) / (1024 * 1024)
        print("🎉 Dataset comprimido con éxito. ¡Listo para arrastrar a Roboflow!")
        print(f"   📁 Archivo: {archivo_zip}")
        print(f"   📊 Tamaño: {tamano_mb:.2f} MB")
        return archivo_zip
    except Exception as e:
        print(f"⚠️ Error al comprimir el dataset a ZIP: {e}")
        return None

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 INICIANDO EXTRACCIÓN INTELIGENTE CON PRE-ANOTACIÓN")
    print("=" * 60)

    start_time = time.time()
    max_duration_sec = HORAS_EJECUCION * 3600
    hilos = []
    
    for nombre, url in CAMARAS.items():
        if not nombre or not url:
            continue
        t = threading.Thread(target=procesar_camara, args=(nombre, url))
        t.daemon = True 
        t.start()
        hilos.append(t)

    try:
        while True:
            elapsed_time = time.time() - start_time
            if elapsed_time > max_duration_sec:
                break
            
            horas_pasadas = elapsed_time / 3600
            print(f"⏳ Monitoreo: {horas_pasadas:.2f}h / {HORAS_EJECUCION}h ejecutadas...", end="\r")
            time.sleep(60)

    except KeyboardInterrupt:
        print("\n\n🛑 Ejecución interrumpida manualmente.")
        
    finally:
        print("\n🚨 Finalizando procesos...")
        stop_event.set()
        for t in hilos:
            t.join(timeout=10)
        print("✅ EXTRACCIÓN INTELIGENTE TERMINADA.")
        
        # Comprimir dataset para descarga inmediata
        comprimir_dataset(BASE_OUTPUT_DIR)
