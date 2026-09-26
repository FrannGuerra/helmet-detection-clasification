# 🧠 Guía de Entrenamiento de los Modelos

Cómo entrenar y re-entrenar los modelos de detección y clasificación.

---

## 📋 Resumen

El sistema usa **dos modelos** de IA:

| Modelo | Archivo | Base | Propósito | Notebook |
|--------|---------|------|-----------|----------|
| **Detección** | `rider_detector.pt` | YOLOv8m | Detectar riders (moto+persona) | `externos/modelo-detector-rider.ipynb` |
| **Clasificación** | `clasificador.pt` | YOLOv8m-cls | Clasificar `con_casco` / `sin_casco` | `externos/modelo-clasificador.ipynb` |

---

## 🏍️ Modelo de Detección (`rider_detector.pt`)

### Datos de Entrenamiento

| Fuente | Imágenes |
|--------|----------|
| COCO 2017 (auto-generadas: moto+persona → rider) | ~3,659 |
| Roboflow (3 datasets de riders) | ~9,034 |
| Dataset propio (cámaras CCTV) | ~665 |
| **Total** | **~12,400** |

### Parámetros

| Parámetro | Valor |
|-----------|-------|
| Modelo base | `yolov8m.pt` |
| Épocas | 300 (con early stopping patience=50) |
| Imagen de entrada | 640×640 |
| Batch size | 16 |
| Clases | 1 (`motorcycle_rider`) |

### Cómo Re-entrenar

1. Abrir `externos/modelo-detector-rider.ipynb` en Kaggle/Colab con GPU
2. Configurar API keys (Roboflow, Kaggle)
3. Ejecutar todas las celdas en orden
4. El modelo se guarda como `best.pt` → renombrar a `rider_detector.pt`

---

## 🪖 Modelo de Clasificación (`clasificador.pt`)

### Datos de Entrenamiento

| Split | Imágenes |
|-------|----------|
| Train | 9,272 |
| Val | 1,987 |
| Test | 1,989 |
| **Total** | **~13,248** |

Clases: `0_sin_casco`, `1_con_casco`

### Parámetros

| Parámetro | Valor |
|-----------|-------|
| Modelo base | `yolov8m-cls.pt` |
| Épocas | 100 (early stopping patience=15) |
| Imagen de entrada | 224×224 |
| Batch size | 128 |
| Optimizer | AdamW |
| Dropout | 0.1 |
| Augmentaciones | Solo flip horizontal (0.5) y erasing (0.2) |
| **Accuracy (test)** | **96%** |

> [!IMPORTANT]
> El modelo fue entrenado con `scale=0.0` y `crop_fraction=1.0`. Esto significa que NO se usa random crop ni random resize. Las imágenes se ven completas. El código del clasificador pasa las imágenes PIL directo a Ultralytics, que las redimensiona a 224×224 de forma consistente.

### Cómo Re-entrenar

1. Abrir `externos/modelo-clasificador.ipynb` en Kaggle con GPU
2. Apuntar al dataset de clasificación (carpetas `con_casco` / `sin_casco`)
3. Ejecutar
4. El modelo se guarda como `best.pt` → renombrar a `clasificador.pt`

---

## 🔄 Re-entrenamiento con Datos Propios

### Recolectar datos desde la app

La app guarda automáticamente crops clasificados en:
```
crops/
├── cam_1/
│   ├── con_casco/
│   │   ├── crop_t1234_5.jpg
│   │   └── ...
│   └── sin_casco/
│       ├── crop_t1234_6.jpg
│       └── ...
```

Estos crops se pueden usar directamente para re-entrenar el clasificador:
1. Revisar manualmente los crops (corregir clasificaciones incorrectas)
2. Agregar al dataset de entrenamiento
3. Re-ejecutar el notebook

---

## ⚠️ Notas Importantes

> [!CAUTION]
> Al reemplazar un modelo, siempre hacer un **backup** del anterior.

> [!IMPORTANT]
> Si cambiás el `imgsz` del clasificador en el entrenamiento, también debés cambiarlo en `config/config.yaml` bajo `classification.imgsz`.

> [!TIP]
> Para mejorar la precisión en tus cámaras específicas, lo ideal es grabar video de esas cámaras, extraer crops, clasificarlos manualmente, y re-entrenar con esos datos del mismo dominio.
