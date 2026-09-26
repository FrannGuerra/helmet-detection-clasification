# Arquitectura y Lógica del Sistema 🏗️

Este documento detalla el funcionamiento interno de la aplicación, las decisiones de diseño ocultas en el código y la lógica *core* del motor de visión computacional.

---

## 🧠 Lógica de Decisión y Configuraciones Clave

Para evitar falsos positivos y optimizar el rendimiento, el sistema toma decisiones basándose en reglas estrictas programadas en `app/core/detector.py` y `app/core/classifier.py`. Estas son las lógicas que hacen que el sistema sea robusto en el mundo real:

### 1. Tracking Persistente y Deduplicación
Si procesamos video a 20 FPS y una moto tarda 3 segundos en cruzar la cámara, el sistema registraría 60 fotos de la misma persona. 
- **Solución:** Se utiliza el tracker interno nativo de YOLO. Cada vehículo recibe un `track_id` único apenas entra en cuadro.
- **Lógica Oculta:** El sistema *sabe* que el objeto #45 en el frame 1 es el mismo objeto #45 en el frame 60. Por lo tanto, la infracción (o el cumplimiento) se registra **una sola vez** en la base de datos por ID. Esto evita arruinar las métricas y los gráficos con conteos duplicados.

### 2. Acumulación de Frames (`frames_to_classify`)
Una foto tomada a 60 km/h o con mala iluminación puede salir borrosa. Determinar si alguien lleva casco basándose en una sola imagen (1 frame) es estadísticamente riesgoso.
- **Solución:** El parámetro `frames_to_classify` en `config.yaml` (por defecto fijado en 3 o 4).
- **Lógica Oculta:** Cuando el tracker detecta un `track_id` nuevo, **no lo clasifica de inmediato**. El sistema recorta la cabeza y la guarda en un buffer en memoria, manteniendo su estado como `'pendiente'`. Extrae recortes de ese mismo motociclista a lo largo de 4 frames distintos a medida que avanza por la calle.

### 3. Regla de Votación Mayoritaria (Clasificación por Batch)
Una vez que el buffer del `track_id` alcanza la cantidad requerida de frames (ej. 4 recortes de la misma persona), se procesan todos juntos en *batch* (lo que además optimiza el uso de la placa de video).
- **Lógica de Decisión:** Se aplica un sistema de **votación**. Si de las 4 fotos, el clasificador dictamina que en 3 no tiene casco y en 1 sí, la votación mayoritaria resuelve el caso como **Sin Casco**. Esto elimina el ruido causado por frames donde un reflejo del sol o un ángulo tapó el casco por un milisegundo.

### 4. Heurística de Fallback (La "Pseudo-Cabeza")
El pipeline visual es de dos pasos: primero encuentra la moto (`Clase 0`), luego encuentra la cabeza/torso arriba (`Clase 1`).
- **Problema en el mundo real:** A veces la persona está tan agachada (posición *racing*), la cámara está muy lejos, o están de espaldas, provocando que YOLO detecte perfectamente la caja de la moto, pero falle en encontrar la caja de la cabeza.
- **Lógica de Decisión (Fallback):** En lugar de ignorar a esa persona y perder la métrica, el código aplica una heurística geométrica de rescate. Extrae automáticamente el **45% superior** del *bounding box* (caja) de la moto, asumiendo que el humano *debe* estar obligatoriamente en esa región. Ese recorte forzado ("pseudo-cabeza") se envía al clasificador de cascos. Esto garantiza que ningún conductor evada el sistema por tener mala postura corporal.

---

## 🎯 Arquitectura de Software

- **Procesamiento Híbrido:** Por cada cámara que se inicia, se crea una instancia del *Detector* en un thread separado (necesario porque cada tracker guarda el estado de los IDs de su respectiva calle). Sin embargo, existe un único **Clasificador Singleton** (compartido globalmente en memoria RAM/VRAM) por el que pasan las cabezas de todas las cámaras. Esto previene que la memoria colapse al conectar 4 streams HLS.
- **Disciplina KISS (Keep It Simple, Stupid):** Solo sobreviven en el código los modelos que están en producción (`detector.pt` y `clasificador.pt`).
- **Dashboard SPA Asíncrono:** La interfaz de usuario es estática pero hidratada en tiempo real mediante WebSockets (`flask-socketio`). Al cambiar entre la pestaña de "Monitoreo en vivo" y "Estadísticas", la página jamás recarga, y las métricas se actualizan sin peticiones HTTP pesadas.
