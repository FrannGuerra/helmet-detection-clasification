# Sistema de Detección de Cascos 🏍️

Sistema de visión computacional diseñado para monitorear transmisiones de video en vivo (HLS), detectar motociclistas y clasificar automáticamente el uso del casco. Cuenta con una interfaz gráfica completa para ver los videos en tiempo real, visualizar alertas instantáneas, consultar estadísticas y exportar reportes de infractores.

---

## 📁 Estructura del Proyecto

El proyecto está organizado de manera modular:

```text
final_img/
├── app/               # Lógica principal del sistema (backend en Flask)
│   ├── core/          # Scripts de detección de imágenes y procesamiento de video
│   ├── data/          # Manejo de la base de datos de infracciones y generación de métricas
│   └── app.py         # Archivo que arranca el servidor web
├── config/            # Archivos de configuración (config.yaml)
├── crops/             # (Autogenerada) Se guardan las fotos recortadas de los infractores
├── data/              # Carpeta donde se aloja la base de datos (detections.db)
├── docs/              # Documentación técnica avanzada (Arquitectura y Lógica)
├── static/            # Archivos de la interfaz web (CSS, JavaScript, audios)
├── training/          # Contiene los scripts para entrenar los modelos
├── videos/            # Carpeta para colocar videos locales de prueba
└── README.md          # Esta guía
```

---

## 🚀 Guía de Instalación (Exclusivo WSL)

Este proyecto está diseñado para ejecutarse **única y exclusivamente bajo Windows Subsystem for Linux (WSL)**.

### 1. Preparar WSL y Dependencias del Sistema
Asegúrate de estar dentro de tu terminal WSL. Necesitamos instalar `ffmpeg`, la herramienta encargada de procesar los videos:

```bash
sudo apt update
sudo apt install ffmpeg
```

### 2. Clonar el repositorio
```bash
git clone https://github.com/FrannGuerra/helmet-detection-clasification.git
cd helmet-detection-clasification
```

### 3. Crear el Entorno Virtual (venv_wsl)
Para no mezclar librerías, crearemos un entorno virtual dedicado y lo activaremos:
```bash
python3 -m venv venv_wsl
source venv_wsl/bin/activate
```

### 4. Instalar dependencias
```bash
pip install -r requirements.txt
```

---

## 🧠 Entrenamiento y Obtención de Modelos

Los modelos ("pesos") no están incluidos en este repositorio debido a su tamaño. Todo el proceso de entrenamiento se realiza en Kaggle utilizando sus GPUs. Podés consultar los notebooks y los datasets acá:
* **Detector:** [entrenamiento-detector](https://www.kaggle.com/code/guerra1/entrenamiento-detector) [Dataset](https://www.kaggle.com/datasets/guerra1/dataset-detector-v2)
* **Clasificador:** [entrenamiento-clasificador](https://www.kaggle.com/code/guerra1/entrenamiento-clasificador) [Dataset](https://www.kaggle.com/datasets/guerra1/dataset-clasificador-v2)

### ¿Cómo descargo los modelos listos para usar?
1. Entrá a los enlaces de los Notebooks mencionados arriba.
2. Ve a la pestaña **Output** en la última ejecución exitosa del notebook.
3. Descargá el archivo `.zip` y extraelo.
4. Entrá a la carpeta `weights/` y copiá el archivo `best.pt` o `last.pt` (dependiendo del que haya dado mejores resultados en test, que se puede ver en los logs del notebook).
5. Colocá esos archivos en la carpeta principal de este proyecto (`final_img/`) y **renombralos** exactamente así:
   * Al modelo del detector llamalo: `detector.pt`
   * Al modelo del clasificador llamalo: `clasificador.pt`
6. *(Opcional pero recomendado)* Exportar el detector a TensorRT para mayor velocidad:
   ```bash
   yolo export model=detector.pt format=engine imgsz=960 half=True
   ```
   Esto genera `detector.engine`. Actualizá `config/config.yaml` para apuntar al `.engine`.

---

## ▶️ Ejecución del Sistema

Una vez que tengas tus dependencias instaladas y los dos archivos de modelos ubicados en la raíz del proyecto, ejecutá:

```bash
python app/app.py
```
El servidor iniciará en modo de espera. Abrí tu navegador web e ingresá a: **`http://localhost:5000`**

---

## 🎮 Guía de Uso y Configuración

Una vez que el sistema está corriendo, todo se administra desde la web o modificando el archivo de configuración.

### 1. El Dashboard (Interfaz Web)
- **Monitoreo en Vivo:** Podés ver hasta 4 cámaras en simultáneo. Si hacés clic en una cámara, el panel de métricas se filtra para mostrarte solo los datos de esa cámara.
- **Mapa de Calor:** Se ubica abajo a la izquierda e ilumina en rojo las cámaras con mayor cantidad de infracciones registradas en la última hora.
- **Alertas y Sonido:** Cada vez que pasa alguien sin casco, salta una notificación a la derecha. Si hacés clic en la alerta, se abre la foto exacta del infractor, ampliada. Hay un botón en la barra superior para mutear la campanilla.

### 2. Configurar Cámaras (`config/config.yaml`)
El archivo principal de configuración es `config/config.yaml`. Ahí definís qué cámaras vas a leer:

```yaml
cameras:
  - id: 1
    name: "Cámara Av. Corrientes"
    source: "https://url-del-stream/index.m3u8"  # Stream HLS o URL de YouTube
    lat: -34.603722
    lng: -58.381592
```
*Tipos de `source` soportados:* Links de streams HLS (`.m3u8`) o videos en vivo de YouTube.

### 3. Ajustar la Sensibilidad y Rendimiento
En el mismo `config.yaml`, podés ajustar qué tan estricto y rápido es el sistema:

```yaml
video:
  fps: 10                        # FPS de captura del stream
  resolution: [1280, 720]        # Resolución de procesamiento

detection:
  confidence_threshold: 0.30    # Sensibilidad para detectar motos
  head_confidence: 0.50         # Sensibilidad para detectar cabezas
  inside_threshold: 0.85        # % mínimo de la cabeza dentro del bbox de la moto
  frames_to_classify: 5         # Votos mínimos idénticos para veredicto rápido
  max_frames_to_collect: 10     # Máximo de frames de calidad en memoria por moto
  imgsz: 960                    # Tamaño de inferencia del detector

classification:
  confidence_threshold: 0.70    # Sensibilidad para clasificar casco

models:
  detection: "detector.engine"  # TensorRT (.engine) o PyTorch (.pt)
  classification: "clasificador.pt"
```

### 4. Archivos Generados Automáticamente
Mientras el sistema funciona, irá generando los siguientes archivos:
- **`data/detections.db`**: Base de datos SQLite. Guarda todas las métricas.
- **`crops/cam_<ID>/motos/sin_casco/`**: Fotos (`.jpg`) de la moto entera de los infractores.
- **`crops/cam_<ID>/motos/con_casco/`**: Fotos de motos con casco.
- **`crops/cam_<ID>/motos/<status>/debug.txt`**: Log de texto con detalle de cada clasificación (votos, confianzas, frames).
