# Sistema de Detección de Cascos en Motociclistas

Aplicación web para monitoreo y análisis en tiempo real de uso de casco en motociclistas mediante visión por computadora e inteligencia artificial con YOLOv8.

---

## 🎯 Características Principales

- ✅ **Detección y Tracking Persistente:** Detección de riders (motocicleta + conductor) con modelo YOLOv8m custom y seguimiento continuo con Track IDs.
- ✅ **Clasificación de Casco:** Clasificación binaria (`con_casco` / `sin_casco`) con red neuronal YOLOv8m-cls a resolución nativa de 224×224.
- ✅ **Deduplicación Inteligente:** Clasificación única por vehículo para evitar conteos redundantes durante su permanencia en cuadro.
- ✅ **Modal de Alerta Accionable (R1):** Tarjetas de alerta clickeables que abren un modal centrado con el recorte (crop) de la infracción, detalles de fecha/hora, cámara y nivel de confianza.
- ✅ **Panel de Analítica y Estadísticas SPA (R2):** Navegación fluida por pestañas ("Monitoreo en Vivo" y "Estadísticas / Analítica") con tarjetas KPI y gráficos interactivos con Chart.js (infracciones por hora y comparativa por cámara).
- ✅ **Exportación de Reportes CSV (R3):** Descarga de historial de infracciones en formato CSV estándar RFC-4180 con compatibilidad para Microsoft Excel (UTF-8 BOM) y sanitización contra inyección de fórmulas.
- ✅ **Notificaciones Sonoras y Botón Mute (R4):** Chime auditivo sutil ante nuevas infracciones con botón en cabecera para alternar silencio, con preferencia persistida en `localStorage`.
- ✅ **Mapa Geoespacial Ergonómico (R5):** Mapa de calor Leaflet con altura optimizada a 220px para visualizarse armónicamente junto a los feeds de video sin desplazar la pantalla.
- ✅ **Multi-Cámara en Tiempo Real:** Soporte para transmisiones en vivo HLS en cuadrícula 2x2.
- ✅ **Métricas en Vivo vía WebSockets:** Actualización instantánea de tasa de cumplimiento, total de motociclistas e infracciones acumuladas.

---

## 📋 Requisitos del Sistema

- **Python:** 3.9 o superior
- **FFmpeg:** Necesario para decodificar streams HLS y reproducir videos (`ffmpeg` debe estar en el PATH del sistema)
- **Modelos YOLOv8:**
  - `rider_detector.pt` (detector de riders, ~52 MB)
  - `clasificador.pt` (clasificador de casco, ~31 MB)

Ambos archivos `.pt` deben estar ubicados en la raíz del proyecto.

---

## 🚀 Instalación y Puesta en Marcha

### 1. Instalar FFmpeg

- **Windows:** Descargar desde [gyan.dev FFmpeg Builds](https://www.gyan.dev/ffmpeg/builds/) y agregar la carpeta `bin` a las Variables de Entorno (`PATH`).
- **Linux / macOS:**
  ```bash
  sudo apt install ffmpeg      # Debian/Ubuntu
  brew install ffmpeg          # macOS
  ```

### 2. Clonar / Descargar el Repositorio e Instalar Dependencias

```bash
pip install -r requirements.txt
```

### 3. Verificar Modelos de IA

Asegúrate de que los archivos `rider_detector.pt` y `clasificador.pt` estén en la raíz de `final_img/`.

### 4. Iniciar el Servidor

```bash
python app/app.py
```

### 5. Abrir la Interfaz Web

Ingresa en tu navegador a: **`http://localhost:5000`**

Al ingresar podrás seleccionar:
- **Videos en Vivo (📡):** Streams HLS configurados.

---

## 🎨 Nuevas Capacidades de la Interfaz (UI/UX)

### 🔍 Modal de Detalle de Infracción (Alert Modal)
- Cada alerta roja en la columna lateral es interactiva.
- Al hacer clic en una alerta, se despliega `#alert-modal` con fondo oscurecido y desenfocado (`backdrop-blur`).
- Carga y exhibe el recorte original de la motocicleta infractora servido directamente desde el endpoint `/crops/...`.
- Si por alguna razón la imagen fue eliminada del disco, muestra un indicador de reserva (*fallback*) elegante.
- Permite cerrarse cómodamente con el botón **X**, haciendo clic fuera del modal o presionando la tecla **Escape**.

### 🔊 Notificaciones Auditivas y Control de Silencio
- Cuando se detecta un motociclista sin casco, se reproduce una campanilla corta y no invasiva (`alert.mp3`).
- El botón **🔔 Sonido / 🔕 Silenciado** en la barra superior permite activar o silenciar las alertas en cualquier momento.
- Tu preferencia queda guardada en el navegador (`localStorage`) para futuras sesiones.
- Compatible con las políticas de autoplay de Chrome/Edge (se inicializa con la primera interacción del usuario).

### 📊 Panel de Estadísticas y Analítica
- Alterna entre la vista de **Monitoreo en Vivo** y la pestaña **Estadísticas / Analítica** sin recargar la página.
- **Tarjetas KPI:** Infracciones Totales, Total de Detecciones y Tasa de Cumplimiento Global.
- **Gráfico de Infracciones por Hora:** Gráfico de barras interactivo desarrollado con Chart.js para identificar franjas horarias de mayor incidencia.
- **Gráfico de Infracciones por Cámara:** Desglose comparativo por cámara para auditoría de zonas críticas.

### 📥 Exportación de Reportes a CSV
- Botón **Exportar CSV** en el panel de analítica.
- Descarga inmediata de un archivo `infractions_export_<timestamp>.csv`.
- Incluye cabecera **UTF-8 con BOM** para que Microsoft Excel abra los caracteres y acentos correctamente sin necesidad de importar datos manualmente.
- Sanitización de fórmulas: Cualquier campo que empiece con `=`, `+`, `-`, o `@` es neutralizado con prefijo `'` para proteger contra ataques de inyección de comandos en hojas de cálculo.

### 🗺️ Mapa Ergonómico de 220px
- El contenedor de Leaflet `#map` fue rediseñado a una altura de **220px** para permitir que toda la información relevante de video y telemetría quepa cómodamente en una pantalla de escritorio estándar sin requerir scroll vertical excesivo.

---

## 🔌 API REST y WebSockets

### Rutas REST

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `/` | Retorna la aplicación web SPA (`index.html`) |
| `GET` | `/crops/<path:filename>` | **(Nuevo)** Entrega segura de imágenes de recortes (`crops/`) con protección anti path traversal |
| `GET` | `/api/stats/dashboard` | **(Nuevo)** Retorna resumen de métricas, distribución horaria y desglose por cámara para Chart.js |
| `GET` | `/api/violations/export` | **(Nuevo)** Descarga el reporte histórico en CSV (RFC-4180, UTF-8 BOM, fórmula sanitizada) |
| `GET` | `/api/cameras` | Lista de cámaras disponibles |
| `POST` | `/api/start` | Inicia procesamiento |
| `POST` | `/api/stop` | Detiene el procesamiento de todas las cámaras |
| `GET` | `/api/metrics/<time_range>` | Métricas por rango (`5min`, `15min`, `30min`, `1hour`) |
| `GET` | `/api/map/heatmap` | Puntos para capa de calor Leaflet |
| `GET` | `/api/violations` | Lista JSON de las últimas 50 infracciones |


#### Ejemplo de Respuesta: `GET /api/stats/dashboard`
```json
{
  "success": true,
  "status": "ok",
  "summary": {
    "total_violations": 42,
    "total_detections": 150,
    "compliance_rate": 72.0
  },
  "by_camera": [
    {"camera_id": 1, "camera_name": "Av. Corrientes", "violations": 25, "detections": 90},
    {"camera_id": 2, "camera_name": "Av. 9 de Julio", "violations": 17, "detections": 60}
  ],
  "by_hour": [
    {"hour": "08:00", "violations": 5},
    {"hour": "09:00", "violations": 12}
  ]
}
```

#### Ejemplo de Parámetros: `GET /api/violations/export`
- Query params: `?camera_id=1` (opcional, filtra por ID de cámara; sin parámetro exporta todas).
- Respuesta: Archivo `text/csv; charset=utf-8` con nombre `infractions_export_<YYYYMMDD_HHMMSS>.csv`.

### Eventos de WebSocket (Flask-SocketIO)

- **`violation_detected`**: Emitido en tiempo real cuando se registra un infractor.
  ```json
  {
    "type": "sin_casco",
    "confidence": 0.89,
    "timestamp": 1725464500.12,
    "camera_id": 1,
    "camera_name": "Av. Corrientes",
    "track_id": 4,
    "crop_path": "cam_1/sin_casco/moto_t1725464500_4.jpg",
    "crop_url": "/crops/cam_1/sin_casco/moto_t1725464500_4.jpg",
    "bbox": [320, 140, 510, 480]
  }
  ```
- **`metrics_update`**: Actualización periódica de métricas de cumplimiento por cámara.
- **`camera_finished`**: Notifica cuando una cámara finaliza su stream de video.
- **`all_cameras_finished`**: Notifica cuando concluye el procesamiento de todas las cámaras.

---

## 🧪 Ejecución de Pruebas Automatizadas (E2E Test Suite)

El proyecto cuenta con una suite completa de pruebas opacas organizadas por niveles (*tiers*):

### Ejecutar todas las pruebas (Tiers 1 a 4)

```bash
python tests/run_tests.py
```

### Ejecutar un nivel específico

```bash
python tests/run_tests.py --tier 1   # Tier 1: Verificación de funcionalidades R1 a R5
python tests/run_tests.py --tier 2   # Tier 2: Condiciones de borde y robustez
python tests/run_tests.py --tier 3   # Tier 3: Combinaciones entre características
python tests/run_tests.py --tier 4   # Tier 4: Escenarios de uso en el mundo real
```

### Ejecutar con el módulo estándar `unittest`

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## 📁 Estructura del Repositorio

```
final_img/
├── app/
│   ├── core/
│   │   ├── detector.py          # Detección YOLOv8m y deduplicación con tracking
│   │   ├── classifier.py        # Clasificador YOLOv8m-cls de uso de casco
│   │   ├── video_processor.py   # Ingesta de video HLS
│   │   └── utils.py             # Carga y validación de configuración
│   ├── data/
│   │   ├── database.py          # SQLite, migraciones, KPIs y export CSV
│   │   └── models.py            # Dataclasses (Camera, Detection, Metrics)
│   └── app.py                   # Servidor Flask, SocketIO y rutas API
├── static/
│   ├── css/styles.css           # Estilos personalizados (mapa 220px, modal, pestañas)
│   ├── js/app.js                # Lógica de cliente, Leaflet, Chart.js y WebSockets
│   ├── audio/alert.mp3          # Chime sutil para notificaciones de infracción
│   └── index.html               # SPA principal con vista Monitoreo y Analítica
├── docs/
│   ├── ARQUITECTURA.md          # Arquitectura del sistema y diagramas Mermaid
│   ├── GUIA_ENTRENAMIENTO.md    # Re-entrenamiento y exportación de modelos
│   ├── DEPENDENCIAS.md          # Listado detallado de dependencias
│   └── GUIA_INSTALACION.md      # Instrucciones de configuración del entorno
├── tests/                       # Suite de pruebas E2E automatizadas
│   ├── run_tests.py             # Runner CLI con soporte por tiers
│   ├── test_tier1_features.py   # Pruebas funcionales de requisitos
│   ├── test_tier2_boundaries.py # Pruebas de límites y seguridad
│   ├── test_tier3_combinations.py # Pruebas de integración cruzada
│   └── test_tier4_scenarios.py  # Pruebas de ciclo de vida completo
├── config/
│   └── config.yaml              # Configuración general de cámaras y modelos
├── crops/                       # Almacenamiento local de recortes clasificados
├── data/detections.db           # Base de datos SQLite
├── rider_detector.pt            # Modelo YOLOv8m de detección (~52 MB)
├── clasificador.pt              # Modelo YOLOv8m-cls de clasificación (~31 MB)
├── requirements.txt             # Dependencias del proyecto
└── README.md                    # Esta guía
```

---

## 🔧 Configuración (`config/config.yaml`)

Puedes ajustar los parámetros principales directamente en `config/config.yaml`:

```yaml
# Umbrales y cadencia
detection:
  confidence_threshold: 0.40  # Confianza mínima para registrar un rider
  process_interval: 0.05      # Tiempo en segundos entre análisis de frames (20 FPS)
  inside_threshold: 0.90      # Solapamiento mínimo para asignar cabeza a moto
  frames_to_classify: 4       # Cantidad de frames a evaluar por moto

classification:
  confidence_threshold: 0.70  # Confianza mínima del clasificador de casco
  imgsz: 64                   # Tamaño de entrada para el clasificador

# Servidor Flask
server:
  host: "0.0.0.0"
  port: 5000
  debug: true
```

---

## 🧠 Principios de Arquitectura KISS

El proyecto sigue una estricta disciplina **KISS (Keep It Simple, Stupid)**:
1. **Modelos vigentes únicamente:** Se emplean exclusivamente `detector.pt` y `clasificador.pt`. No se mantienen pipelines comentados ni modelos archivados/eliminados.
2. **Cadencia equilibrada:** 20 FPS de base por cámara (`0.05` de intervalo).
3. **Pipeline unificado y eficiente:** Tracking YOLOv8 por cámara -> Acumulación de 4 frames -> Clasificación con YOLOv8m-cls **compartido globalmente en memoria** para optimizar uso de VRAM y procesamiento.

---

## 📄 Licencia

Proyecto desarrollado para monitoreo inteligente y seguridad vial.
