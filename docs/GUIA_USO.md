# 🚀 Guía de Uso

Cómo utilizar el Sistema de Detección de Cascos en Motociclistas.

---

## ▶️ Inicio Rápido

### Windows
```powershell
cd "C:\ruta\al\proyecto\prueba antigravity"
.\venv\Scripts\Activate.ps1
python app/app.py
```

### Linux / WSL
```bash
cd /ruta/al/proyecto/"prueba antigravity"
source venv_linux/bin/activate
python3 app/app.py
```

Abrir **http://localhost:5000** en el navegador.

---

## 🎮 Dashboard

### Vista General

El dashboard se compone de 3 secciones:

| Sección | Ubicación | Contenido |
|---------|-----------|-----------|
| **Cámaras en vivo** | Izquierda superior | Grid 2×2 con streams de cámaras |
| **Mapa de calor** | Izquierda inferior | Mapa Leaflet con heatmap de infracciones |
| **Panel lateral** | Derecha | Métricas, alertas, estado del sistema |

### Funcionalidades

#### 📹 Cámaras
- Se muestran en una grilla 2×2
- Cada cámara muestra su nombre e ID
- Click en una cámara para filtrar métricas solo de esa cámara

#### 📊 Métricas por Período
- Filtros: **5min**, **15min**, **30min**, **1 hora**
- Muestra:
  - **Tasa de cumplimiento** (% con casco)
  - **Riders con casco** (✅ verde)
  - **Riders sin casco** (❌ rojo)

#### 🗺️ Mapa de Calor
- Muestra la ubicación geográfica de cada cámara
- Intensidad del color indica la cantidad de infracciones
- Se actualiza automáticamente cada 30 segundos

#### 🚨 Alertas Recientes
- Notificaciones en tiempo real de infracciones
- Muestra cámara, hora y confianza de la detección
- Máximo 20 alertas visibles

---

## ⚙️ Configuración

### Cambiar fuentes de video

Editar `config/config.yaml`:

```yaml
cameras:
  - id: 1
    name: "Mi Cámara"
    source: "https://url-del-stream/index.m3u8"  # Stream HLS
    lat: -34.603722
    lng: -58.381592
    type: "hls"
    
  - id: 2
    name: "Video Local"
    source: "mi_video.mp4"    # Archivo local
    lat: -34.610000
    lng: -58.390000
    type: "file"
    
  - id: 3
    name: "Webcam"
    source: "0"               # Webcam por defecto
    lat: -34.620000
    lng: -58.400000
    type: "webcam"
```

### Tipos de fuente soportados

| Tipo | `type` | `source` |
|------|--------|----------|
| Stream HLS | `hls` | URL `.m3u8` |
| Archivo de video | `file` | Ruta al archivo `.mp4`, `.avi`, etc. |
| Webcam | `webcam` | `0` (defecto), `1`, `2`, etc. |

### Ajustar detección

```yaml
detection:
  confidence_threshold: 0.15     # ↓ Más bajo = detecta más (más falsos positivos)
  iou_threshold: 0.1             # Umbral de superposición para matching
  min_classification_confidence: 0.75  # Confianza mínima para clasificar
  similarity_threshold: 0.8      # Umbral para detectar duplicados
```

### Cambiar puerto

```yaml
server:
  host: "0.0.0.0"
  port: 8080    # Cambiar puerto aquí
  debug: true
```

---

## 📡 API REST

Todos los endpoints devuelven JSON.

### `GET /api/cameras`
Lista de cámaras configuradas.

```bash
curl http://localhost:5000/api/cameras
```
```json
[
  {"id": 1, "name": "Cámara 1", "source": "...", "lat": -22.97, "lng": -49.87, "type": "hls"},
  {"id": 2, "name": "Cámara 2", "source": "...", "lat": -23.09, "lng": -48.92, "type": "hls"}
]
```

### `GET /api/metrics/<time_range>`
Métricas filtradas por tiempo. Valores: `5min`, `15min`, `30min`, `1hour`.

```bash
curl http://localhost:5000/api/metrics/5min
curl http://localhost:5000/api/metrics/1hour?camera_id=1
```
```json
{
  "time_range": "5min",
  "riders_with_helmet": 12,
  "riders_without_helmet": 3,
  "total_riders": 15,
  "compliance_rate": 80.0,
  "camera_id": null
}
```

### `GET /api/violations`
Historial de infracciones (últimas 50).

```bash
curl http://localhost:5000/api/violations
curl http://localhost:5000/api/violations?camera_id=2
```

### `GET /api/map/heatmap`
Datos del mapa de calor.

```bash
curl http://localhost:5000/api/map/heatmap?range=1hour
```

### `GET /api/debug-frames`
Lista de frames de debug guardados.

```bash
curl http://localhost:5000/api/debug-frames?camera_id=1
```

### WebSocket Events

Conectar con Socket.IO:

```javascript
const socket = io('http://localhost:5000');

// Recibir métricas en tiempo real
socket.on('metrics_update', (data) => {
  console.log('Métricas:', data);
  // data = {total_riders, riders_with_helmet, riders_without_helmet, compliance_rate, camera_id}
});

// Recibir alertas de infracción
socket.on('violation_detected', (data) => {
  console.log('¡Infracción!', data);
  // data = {type, confidence, timestamp, camera_id, camera_name}
});
```

---

## 🗂️ Archivos Generados en Ejecución

| Ruta | Contenido |
|------|-----------|
| `data/detections.db` | Base de datos SQLite con detecciones e infracciones |
| `crops/cam_<ID>/con_casco/` | Recortes de riders con casco |
| `crops/cam_<ID>/sin_casco/` | Recortes de riders sin casco |
| `debug_frames/cam_<ID>/` | 3 etapas de debug por frame por cámara |

### Fases de Debug

Cada análisis genera 3 frames de debug:

1. **`step1_yolo`** — Detecciones crudas de YOLO (motos + personas)
2. **`step2_union`** — Union boxes (caja envolvente moto + riders)
3. **`step3_clasificacion`** — Clasificación final (con/sin casco)

> [!TIP]
> Los debug frames se limpian automáticamente, conservando solo los últimos 30 por cámara.

---

## 🛑 Detener la Aplicación

Presionar `Ctrl + C` en la terminal donde se ejecuta la app.

```bash
# Luego desactivar el entorno virtual
deactivate
```
