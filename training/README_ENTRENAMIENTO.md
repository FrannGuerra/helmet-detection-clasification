# 📖 Guía Completa de Entrenamiento — Sistema de Detección de Cascos

Este directorio contiene las herramientas para entrenar el **pipeline híbrido de 2 etapas**, centralizado a partir de **datasets versionados de Roboflow**:
1. **Fase A (Detector YOLOv8n)**: Detecta motos y cabezas a alto FPS.
2. **Fase B (Clasificador YOLOv8m-cls)**: Determina si el recorte de cada cabeza tiene casco o no (64x64).

---

## 📁 Estructura de Carpetas (Versionada)

El sistema ahora soporta múltiples versiones de datasets (ej. `v1`, `v2`, `v3`) para evitar perder los modelos viejos.

```text
d:\final_img\
├── training/
│   ├── README_ENTRENAMIENTO.md               <-- Esta guía
│   ├── preparar_datasets.py                  
│   ├── entrenar_detector.py                  
│   ├── entrenar_clasificador.py              
│   │
│   ├── datasets/
│   │   ├── roboflow_exports/                 
│   │   │   └── v2/                           <-- [ZIP DESCOMPRIMIDO AQUÍ]
│   │   ├── detector/                         
│   │   │   └── v2/                           <-- (Generado auto por el script 1)
│   │   └── clasificador/                     
│   │       └── v2/                           <-- (Generado auto por el script 1)
│   │
│   ├── runs/
│   │   ├── detector/
│   │   │   └── v2/                           <-- (Gráficos, logs y checkpoints del Detector)
│   │   └── clasificador/
│   │       └── v2/                           <-- (Gráficos, logs y checkpoints del Clasif.)
│   │
│   └── models/
│       └── v2/                               <-- (Modelos .pt FINALES generados aquí)
│           ├── rider_detector.pt
│           └── clasificador.pt
```

---

## 🚀 Flujo de Trabajo Paso a Paso (Ejemplo usando 'v2')

### 1. Etiquetar 3 clases en Roboflow

Anotá todas las imágenes de tu proyecto en Roboflow usando estrictamente estas 3 clases:
1. `moto`
2. `cabeza_con_casco`
3. `cabeza_sin_casco`

**Exportá el dataset** usando el formato **YOLOv8** y descomprimí el contenido del `.zip` directamente en la carpeta correspondiente a tu nueva versión (por ejemplo `v2`):  
`training/datasets/roboflow_exports/v2/`

---

### 2. Preparar los Datasets (Clonación y Crops)

Ejecutá el script de preparación unificado especificando la versión. 

```bash
python training/preparar_datasets.py --dataset v2
```
*¿Qué hace por detrás?*
- En `datasets/detector/v2/` clona los labels pero fusiona las clases de cabezas.
- En `datasets/clasificador/v2/` recorta cada cuadradito de cabeza y lo guarda como un JPG individual separado en carpetas `con_casco` y `sin_casco`.

---

### 3. Fase A: Entrenar el Detector (`rider_detector.pt`)

```bash
python training/entrenar_detector.py --dataset v2
```
*Opciones útiles:*
- `--dry-run`: Verifica el dataset sin iniciar el entrenamiento.
- `--resume`: Reanuda si la sesión se interrumpió.
- `--batch 16`: Ajusta el batch size (8 es el valor por defecto seguro para GTX 1650).

> Al finalizar, exportará automáticamente el mejor modelo a: `training/models/v2/rider_detector.pt`.

---

### 4. Fase B: Entrenar el Clasificador (`clasificador.pt`)

```bash
python training/entrenar_clasificador.py --dataset v2
```
*Opciones útiles:*
- `--dry-run`: Revisa la cantidad de imágenes recortadas.
- `--small`: Usa `yolov8s-cls.pt` en vez de `yolov8m-cls.pt` para mayor velocidad de entrenamiento.

> Exportará el mejor modelo automáticamente a: `training/models/v2/clasificador.pt`.

---

### 5. Entrenamiento en Kaggle (Altamente Recomendado)

Si tu placa de video local se queda sin memoria para resoluciones altas (ej: `1024x1024`), puedes usar la nube de forma gratuita:

1. Ingresa a [Kaggle](https://www.kaggle.com/) y crea un **New Notebook**.
2. **Importa la notebook correcta** usando el botón **File -> Import Notebook**:
   - Para Fase A: `training/notebooks_kaggle/entrenamiento_detector_v2.ipynb`
   - Para Fase B: `training/notebooks_kaggle/entrenamiento_clasificador_v2.ipynb`
3. En las opciones a la derecha, cambia el acelerador a **GPU T4 x2**.
4. Primero ejecuta `python training/preparar_datasets.py --dataset v2` en tu máquina local.
5. Ve a la carpeta `training/datasets/.../v2/` (elige `detector` o `clasificador` según corresponda), comprímela en un `.zip` y súbela a Kaggle usando el botón **"Upload Data"** (panel derecho).
6. Ejecuta las celdas de la notebook. Buscará tu dataset automáticamente y lo entrenará con la configuración máxima (DDP en ambas T4, Tensor Cores, etc) sin crashear.
7. Al finalizar, descarga el `.zip` resultante desde la pestaña "Output" y extrae el archivo `best.pt`.

---

### 6. Activar los Nuevos Modelos en la Aplicación

Tus modelos están protegidos en la carpeta de su versión (`training/models/v2/`). Cuando quieras ponerlos en producción:

1. Copiá `rider_detector.pt` y `clasificador.pt` desde `training/models/v2/` hacia la raíz de tu app (`d:\final_img\`).
2. Modificá `config/config.yaml` para asegurar que apunte a los modelos que acabas de copiar:

```yaml
models:
  detection: "rider_detector.pt"
  classification: "clasificador.pt"
```

---

## 🧠 Notas Técnicas (IDs de Clases y Auto-Splits)

No te preocupes por cómo exporta las cosas Roboflow, los scripts manejan toda la complejidad:

### 1. Manejo de IDs de Clases
- **Detector**: En Roboflow tu clase "moto" podría tener el ID 4 y "casco" el ID 7. No importa. El script `preparar_datasets.py` lee los nombres de tu viejo `data.yaml`, entra a todos los archivos `.txt` y reescribe los números a la fuerza (Clase `0` para motos y Clase `1` para cualquier cabeza). Finalmente te crea un `data.yaml` limpio.
- **Clasificador**: El modelo clasificador de YOLO (`yolov8-cls`) no usa archivos `.yaml` ni `.txt`. Simplemente lee los nombres de las carpetas donde metimos los recortes (`con_casco` y `sin_casco`) y las usa directamente como clases. ¡Tú solo etiqueta con los textos correctos!

### 2. Auto-Splits (Train / Valid)
- **Para el Detector**: Si descargas imágenes filtradas de Roboflow y te bajan todas juntas en la carpeta `train/`, el script detectará que la carpeta `valid/` está vacía y hará un auto-split aleatorio (moviendo el 20% de tus imágenes y labels a `valid/`).
- **Para el Clasificador**: El script de entrenamiento (`entrenar_clasificador.py`) junta todas las cabezas y hace un **split estratificado perfecto del 85/15** justo antes de entrenar. Si tienes 100 fotos sin casco, moverá exactamente 15 a validación. Así nos aseguramos de que las clases minoritarias siempre se balanceen correctamente.

### 3. La carpeta "Runs" (Resultados del entrenamiento)
Durante el entrenamiento (Fase A y B), Ultralytics (YOLO) genera muchos archivos de diagnóstico. Ahora todos estos se guardan ordenados por versión en:
- `training/runs/detector/v2/detector_[fecha]`
- `training/runs/clasificador/v2/clasificador_[fecha]`

**¿Qué encuentras dentro de cada run?**
- `results.png`: Un gráfico que te muestra si el modelo fue aprendiendo o si se estancó (curva de pérdida y precisión).
- `confusion_matrix.png`: Te muestra qué clases se están confundiendo entre sí (ej. cuántos sin casco se detectan como con casco).
- `weights/`: Aquí se guardan los checkpoints temporales (`last.pt` por si se corta la luz y quieres reanudar, y `best.pt` que es el mejor logrado).

*Nota: Al finalizar el entrenamiento con éxito, los scripts ya copian automáticamente tu `best.pt` a la carpeta `models/v2/` para tu comodidad, así que no tienes que entrar a buscarlo a mano.*
