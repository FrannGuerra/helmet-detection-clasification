# 📦 Referencia de Dependencias

Detalle de cada dependencia del proyecto y para qué se usa.

---

## Dependencias Python (`requirements.txt`)

| Paquete | Versión | Propósito |
|---------|---------|-----------|
| `flask` | 3.0.0 | Framework web para el servidor HTTP y las rutas API |
| `flask-socketio` | 5.3.5 | Comunicación WebSocket en tiempo real (métricas y alertas) |
| `flask-cors` | 4.0.0 | Permitir peticiones cross-origin al API |
| `ultralytics` | 8.1.0 | Framework YOLOv8 para detección y clasificación de objetos |
| `opencv-python` | ≥4.10.0 | Procesamiento de video e imágenes (captura, dibujo, guardado) |
| `numpy` | ≥1.24.0 | Operaciones numéricas sobre arrays de frames e imágenes |
| `torch` | ≥2.0.0 | Backend de deep learning PyTorch para inferencia de modelos |
| `torchvision` | ≥0.15.0 | Modelos pre-entrenados (MobileNetV2) y transforms de imagen |
| `pillow` | ≥10.0.0 | Manipulación de imágenes PIL (resize, letterbox, padding) |
| `pyyaml` | 6.0.1 | Lectura del archivo de configuración `config.yaml` |
| `python-socketio` | 5.11.0 | Cliente SocketIO (dependencia de `flask-socketio`) |

---

## Dependencias del Sistema

| Herramienta | Propósito | Instalación |
|-------------|-----------|-------------|
| **Python 3.9+** | Runtime del backend | [python.org](https://www.python.org) |
| **FFmpeg** | Decodificación de streams HLS | [gyan.dev/ffmpeg](https://www.gyan.dev/ffmpeg/builds/) (Win) / `apt install ffmpeg` (Linux) |
| **Git** (opcional) | Control de versiones | [git-scm.com](https://git-scm.com) |

---

## Dependencias del Frontend (CDN)

Cargadas automáticamente desde CDN, no requieren instalación:

| Librería | Versión | Propósito |
|----------|---------|-----------|
| **Tailwind CSS** | Última (CDN) | Framework CSS para el dashboard |
| **Socket.IO Client** | 4.6.0 | Comunicación WebSocket con el backend |
| **HLS.js** | Última | Reproducción de streams HLS en el navegador |
| **Leaflet.js** | 1.9.4 | Mapa interactivo |
| **Leaflet.heat** | 0.2.0 | Plugin de mapa de calor para Leaflet |
| **Inter** (Google Fonts) | — | Tipografía del dashboard |

---

## Modelos de IA

| Modelo | Archivo | Tamaño | Origen |
|--------|---------|--------|--------|
| **YOLOv8x** | `yolov8x.pt` | ~137 MB | Pre-entrenado en COCO. Se descarga automáticamente la primera vez |
| **Clasificación Cascos** | `best.pt` | ~31 MB | Entrenado custom con datasets de Roboflow + Kaggle |
| **MobileNetV2** | Descargado automáticamente | ~14 MB | Pre-entrenado en ImageNet. Usado para deduplicación por similitud |
