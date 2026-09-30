# Arquitectura y Lógica del Sistema 🏗️

Este documento detalla el funcionamiento interno de la aplicación, las decisiones de diseño ocultas en el código y la lógica *core* del motor de visión computacional.

---

## 🧠 Lógica de Decisión y Configuraciones Clave

Para evitar falsos positivos y optimizar el rendimiento, el sistema toma decisiones basándose en reglas estrictas programadas en `app/core/detector.py` y `app/core/classifier.py`.

### 1. Pipeline Híbrido: predict() + BYTETracker Manual

> El detector **NO usa `model.track()`** interno de YOLO. Usa `model.predict()` y pasa **solo las motos** al BYTETracker manual (`config/tracker.yaml`). Esto evita que una cabeza dentro del bounding box de una moto "robe" el track ID de la moto.

El flujo de un frame es:

1. `model.predict()` detecta todas las clases (motos + cabezas) en un solo paso.
2. Se filtran las detecciones por clase: `moto_mask` y `head_mask` usando keywords configurables.
3. **Solo las motos** se pasan al `BYTETracker` → IDs estables.
4. Las cabezas se asignan **exclusivamente** a una sola moto, evitando que una cabeza entre dos motos superpuestas genere doble infracción.

### 2. Selección de Frames por Calidad (no por orden de llegada)

Una foto tomada a 60 km/h o con mala iluminación puede salir borrosa. El sistema **no acumula los primeros K frames** sino los **mejores K** según un score de calidad:

```
score = promedio(conf_detección × lado_menor_cabeza)
```

Las cabezas pegadas al borde del frame (< 10px del borde) se descartan del cálculo — son las más borrosas y parciales. Solo los frames con score > 0 se acumulan en el buffer. El buffer retiene los mejores `max_frames_to_collect` frames de mayor calidad.

### 3. Votación con Dos Modos de Resolución

Una vez acumulados los frames de calidad, el sistema vota:

- **Modo rápido**: en cuanto hay `frames_to_classify` votos del mismo tipo → veredicto inmediato.
- **Modo forzado**: si `total_frames_seen >= max_frames_to_collect × 2` → se fuerza el veredicto por mayoría simple (para evitar que una moto lenta quede "pendiente" para siempre).
- **Regla del acompañante**: si al menos 1 cabeza asociada vota `sin_casco` → toda la moto es infracción.

La clasificación por batch optimiza el uso de GPU.

### 4. Reset de Tracker en Reconexiones

El `BYTETracker` mantiene estado interno (filtros de Kalman, historial). Si no se resetea en un `stop`/`start`, puede asignar IDs viejos a motos nuevas causando clasificaciones incorrectas. El método `detector.reset()` limpia tanto el `track_history` propio como el estado interno del tracker.

---

## 🎯 Arquitectura de Software

- **Pipeline Híbrido:** Por cada cámara se crea una instancia de `MotorcycleDetector` en su propio thread (cada instancia tiene su propio `BYTETracker` con estado independiente). El **`HelmetClassifier` es un Singleton** compartido globalmente bajo `threading.Lock()` → previene que la VRAM colapse con múltiples streams.
- **TensorRT para el Detector:** El modelo de detección corre como `detector.engine` (compilado con TensorRT, FP16), lo que reduce la latencia de inferencia y el consumo de VRAM. El clasificador corre en PyTorch estándar (`clasificador.pt`).
