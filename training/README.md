# 📖 Guía de Entrenamiento — Sistema de Detección de Cascos

Este directorio contiene las herramientas y recursos para preparar los datos y entrenar el **pipeline de 2 etapas** del proyecto. 

Todo el proceso de entrenamiento pesado se realiza en **Kaggle** debido a los requerimientos de hardware. Las notebooks de Kaggle se dejan aquí como referencia.

---

## 📁 Estructura del Directorio

```text
training/
├── datasets/                 <-- Datasets procesados localmente antes de subirlos a Kaggle
├── notebooks_kaggle/         <-- Notebooks de referencia (.ipynb) para Kaggle
├── preparar_datasets.py      <-- Script para procesar los exportes de Roboflow
└── README.md                 <-- Esta guía
```

> **Nota sobre modelos y runs:** En este repositorio **no se incluyen** las carpetas `runs/` ni `models/` generadas durante el entrenamiento. Los pesos resultantes (`.pt`) y los gráficos de rendimiento quedan almacenados en Kaggle. Si se desea guardar versiones locales de los mismos, se pueden descargar y almacenar por fuera del control de versiones.

---

## 🚀 Flujo de Trabajo (Kaggle Workflow)

El proceso general consta de etiquetar en Roboflow, preparar los datos en tu computadora, y subir el dataset resultante a Kaggle para entrenar usando sus GPUs gratuitas.

### 1. Etiquetar y Exportar desde Roboflow
Anota tus imágenes utilizando estas 3 clases estrictas:
1. `moto`
2. `cabeza_con_casco`
3. `cabeza_sin_casco`

Exporta el dataset en formato **YOLOv8** y colócalo dentro de `training/datasets/roboflow_exports/<version>/` (ej: `v2`).

### 2. Preparar los Datasets (Localmente)
Ejecuta el script unificado de preparación para procesar los datos descargados. Esto debe hacerse en tu máquina local antes de ir a Kaggle.

```bash
python training/preparar_datasets.py --dataset v2
```

**¿Qué hace el script?**
- **Para el Detector:** Toma las etiquetas de Roboflow y normaliza los IDs (Clase 0 para motos, Clase 1 para cualquier cabeza). Hace un split automático de validación si es necesario.
- **Para el Clasificador:** Extrae físicamente los recortes (crops) de cada cabeza y los guarda en subcarpetas `con_casco` y `sin_casco`, listo para ser leído por YOLO-cls.

### 3. Entrenar en Kaggle
Al no realizar el entrenamiento de forma local para evitar cuellos de botella por hardware, seguimos estos pasos:

1. Ingresa a [Kaggle](https://www.kaggle.com/) y crea un **New Notebook**.
2. **Importa la notebook de referencia** desde `training/notebooks_kaggle/`:
   - Utiliza la notebook del detector para la Fase A.
   - Utiliza la notebook del clasificador para la Fase B.
3. Cambia el acelerador del notebook a **GPU T4 x2**.
4. Toma las carpetas generadas localmente por el script en el paso 2 (las que están dentro de `datasets/detector/` o `datasets/clasificador/`), comprímelas en un `.zip` y súbelas a Kaggle mediante el botón **"Upload Data"**.
5. Ejecuta las celdas de la notebook importada. Los modelos aprovecharán la configuración de las T4.
6. Al finalizar, descarga el `.zip` resultante desde la pestaña **"Output"** del notebook en Kaggle. Ahí encontrarás el archivo `best.pt` con los pesos de tu nuevo modelo.

### 4. Actualizar la Aplicación
Una vez descargados los pesos (`best.pt`) desde Kaggle:
1. Renombra los archivos para que sean fáciles de identificar (ej. `detector.pt` y `clasificador.pt`).
2. Muévelos a la carpeta raíz del proyecto o a tu carpeta de modelos locales.
3. Actualiza el archivo `config/config.yaml` para que apunte a estos nuevos modelos y ¡listo!
