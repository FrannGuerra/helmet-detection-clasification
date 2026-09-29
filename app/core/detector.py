import os
import time
import yaml
from typing import Any, Dict, List

import cv2
import numpy as np
from PIL import Image
from ultralytics import YOLO
from ultralytics.trackers.byte_tracker import BYTETracker
from ultralytics.utils import IterableSimpleNamespace

from .classifier import HelmetClassifier


class MotorcycleDetector:
    """
    Pipeline de detección Híbrido:

    1. Detecta 'moto' y 'cabeza' con YOLOv8m a 1280px usando predict() (sin tracker interno).
    2. Pasa SOLO las motos al BYTETracker manual para obtener IDs estables.
       Las cabezas no necesitan ID de tracking — se asocian geométricamente.
    3. Asigna cada cabeza a UNA SOLA moto (la de mayor solapamiento).
       Evita contar la misma cabeza en dos motos superpuestas.
    4. Acumula los mejores K frames por calidad (conf × tamaño cabeza, descartando bordes).
       No los primeros K — los primeros suelen ser los peores (moto pequeña, lejana).
    5. Vota por mayoría de frames y decide cuando llega a max_frames o al doble de frames vistos.
    6. Aplica la regla del acompañante: si al menos 1 cabeza sin casco → infracción.
    """

    def __init__(self, config: dict, classifier: HelmetClassifier = None):
        # --- Parámetros de configuración ---
        det_cfg = config.get('detection', {})
        cls_cfg = config.get('classification', {})

        self.det_conf = det_cfg.get('confidence_threshold', 0.15)
        self.head_conf = det_cfg.get('head_confidence', 0.25)
        self.cls_conf = cls_cfg.get('confidence_threshold', 0.60)
        self.min_frames = det_cfg.get('frames_to_classify', 3)
        self.max_frames = det_cfg.get('max_frames_to_collect', 10)
        self.inside_threshold = det_cfg.get('inside_threshold', 0.75)
        self.min_head_size = det_cfg.get('min_head_size', 16)
        self.imgsz = det_cfg.get('imgsz', 1280)
        self.effective_fps = det_cfg.get('effective_fps', 10)

        # --- Estado interno ---
        self.track_history = {}

        # --- Cargar modelo detector ---
        print("[Detector] Cargando YOLO detección (Medium a 1280px)...")
        self.detection_model = YOLO(config['models']['detection'])

        # --- Determinar IDs de clase del modelo ---
        self._setup_class_mapping()

        # --- Inicializar BYTETracker manual ---
        self._init_tracker()

        # --- Clasificador (compartido entre detectores de distintas cámaras) ---
        if classifier is not None:
            print("[Detector] Usando clasificador cascos compartido...")
            self.classifier = classifier
        else:
            print("[Detector] Cargando clasificador cascos...")
            self.classifier = HelmetClassifier(config['models']['classification'])

        print("[Detector] Listo")

    def _setup_class_mapping(self):
        """
        Determina qué IDs de clase del modelo corresponden a motos y cabezas.
        Mapea por keywords en el nombre de clase para ser robusto a distintos
        nombres de entrenamiento ('moto', 'motorcycle', 'cabeza_torso', etc.).
        Fallback: si hay exactamente 2 clases, asume 0=moto, 1=cabeza.
        """
        names = self.detection_model.names  # {0: 'moto', 1: 'cabeza_torso', ...}
        self.moto_ids = set()
        self.head_ids = set()
        moto_keywords = ['moto', 'motorcycle', 'rider']
        head_keywords = ['cabeza', 'head', 'torso', 'person']

        for cls_id, name in names.items():
            lower = name.lower()
            if any(kw in lower for kw in moto_keywords):
                self.moto_ids.add(cls_id)
            elif any(kw in lower for kw in head_keywords):
                self.head_ids.add(cls_id)

        # Fallback: si no encontró nada y hay exactamente 2 clases
        if not self.moto_ids and not self.head_ids and len(names) == 2:
            self.moto_ids = {0}
            self.head_ids = {1}

        print(f"[Detector] Clases moto IDs: {self.moto_ids}, cabeza IDs: {self.head_ids}")

    def _init_tracker(self):
        """
        Inicializa BYTETracker manual leyendo config/tracker.yaml.

        Usa ruta absoluta construida desde __file__ para que funcione
        independientemente del directorio de trabajo (CWD).
        """
        # __file__ = d:\final_img\app\core\detector.py
        # app\core → app → d:\final_img
        core_dir = os.path.dirname(os.path.abspath(__file__))   # app/core/
        app_dir = os.path.dirname(core_dir)                      # app/
        project_dir = os.path.dirname(app_dir)                   # d:\final_img\
        yaml_path = os.path.join(project_dir, 'config', 'tracker.yaml')

        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                cfg_dict = yaml.safe_load(f)
            cfg = IterableSimpleNamespace(**cfg_dict)
            self.tracker = BYTETracker(cfg)
            print(f"[Detector] BYTETracker manual inicializado "
                  f"(fps={self.effective_fps}, "
                  f"buffer={cfg_dict.get('track_buffer', 30)}, "
                  f"match_thresh={cfg_dict.get('match_thresh', 0.8)})")
        except Exception as e:
            print(f"[Detector] ERROR inicializando BYTETracker: {e}")
            print("[Detector] WARN: tracker = None. Las motos no tendrán IDs estables.")
            self.tracker = None

    def reset(self):
        """
        Limpia el historial de track IDs Y el tracker interno.

        IMPORTANTE: Llamar en stop→start Y en reconexión de cámara.
        Sin esto, el BYTETracker mantiene tracks de la sesión anterior y puede
        asignar IDs viejos a motos nuevas, causando clasificaciones incorrectas.
        """
        self.track_history = {}
        if self.tracker is not None:
            self.tracker.reset()
            print("[Detector] Tracker reseteado (historial y Kalman filter limpios)")

    def _overlap_ratio(self, inner_box, outer_box):
        """
        Calcula qué fracción del área de inner_box está contenida en outer_box.

        Retorna un float entre 0.0 y 1.0.
        Ejemplo: 0.75 = el 75% del área de inner_box está dentro de outer_box.
        Usado para verificar si una cabeza está dentro de la bbox de una moto.
        """
        ix1 = max(inner_box[0], outer_box[0])
        iy1 = max(inner_box[1], outer_box[1])
        ix2 = min(inner_box[2], outer_box[2])
        iy2 = min(inner_box[3], outer_box[3])

        inter_area = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter_area == 0:
            return 0.0

        inner_area = (inner_box[2] - inner_box[0]) * (inner_box[3] - inner_box[1])
        return (inter_area / float(inner_area)) if inner_area > 0 else 0.0

    def _assign_heads_exclusive(self, cabezas: list, motos: list) -> dict:
        """
        Asigna cada cabeza a UNA SOLA moto (la de mayor solapamiento).

        Evita que una cabeza entre dos motos superpuestas se clasifique y cuente
        para ambas motos (doble infracción falsa).

        Args:
            cabezas: Lista de dicts {'bbox': (x1,y1,x2,y2), 'conf': float}
            motos:   Lista de dicts {'bbox': (x1,y1,x2,y2), 'track_id': str, 'conf': float}

        Returns:
            Dict[track_id → lista de cabezas asignadas exclusivamente]
        """
        assignments = {m['track_id']: [] for m in motos}

        for cabeza in cabezas:
            best_moto_id = None
            best_overlap = 0.0

            for moto in motos:
                overlap = self._overlap_ratio(cabeza['bbox'], moto['bbox'])
                # Solo asignar si supera el umbral mínimo Y es la moto con mayor solapamiento
                if overlap >= self.inside_threshold and overlap > best_overlap:
                    best_overlap = overlap
                    best_moto_id = moto['track_id']

            if best_moto_id is not None:
                assignments[best_moto_id].append(cabeza)

        return assignments

    def _compute_frame_quality(self, cabezas: list, frame_shape: tuple) -> float:
        """
        Calcula un score de calidad del frame para seleccionar los mejores frames.

        Fórmula: promedio de (confianza × tamaño_lado_menor_cabeza),
        descartando cabezas pegadas al borde del frame (a menos de 10px del borde).

        Un frame con cabezas grandes, centradas y de alta confianza tiene mayor
        calidad que uno con cabezas chicas al borde o de baja confianza.

        Retorna 0.0 si todas las cabezas están en el borde (frame no útil).
        """
        h, w = frame_shape[:2]
        margin = 10  # px — cabezas a menos de margin px del borde se descartan

        qualities = []
        for cab in cabezas:
            cx1, cy1, cx2, cy2 = cab['bbox']
            # Descartar cabezas pegadas al borde del frame
            if cx1 <= margin or cy1 <= margin or cx2 >= w - margin or cy2 >= h - margin:
                continue
            cab_w = cx2 - cx1
            cab_h = cy2 - cy1
            size = min(cab_w, cab_h)
            qualities.append(cab['conf'] * size)

        return sum(qualities) / max(1, len(qualities)) if qualities else 0.0

    def process_frame(self, frame: Any, cam_id: int, interval_counter: int = 0) -> Dict[str, Any]:
        """
        Procesa un frame: detecta motos y cabezas, trackea motos, asocia cabezas,
        acumula frames de calidad y clasifica cuando hay suficientes.

        Args:
            frame:            Frame BGR de OpenCV.
            cam_id:           ID de la cámara (para logs).
            interval_counter: Contador de frames procesados (para nombres de archivo).

        Returns:
            Dict con:
                raw_detections:         Todas las detecciones brutas para el overlay.
                duplicate_riders:       Motos ya clasificadas anteriormente.
                classified_riders:      Motos recién clasificadas en este frame.
                riders_ready_to_process: Motos listas para persistir (solo finales, sin pendientes).
                all_tracking_crops:     Crops para debug de tracking.
        """
        # ==================================================================
        # PASO 1: Inferencia con predict() — SIN tracker interno de YOLO
        # ==================================================================
        # Usamos predict() en vez de track() para poder filtrar las clases
        # antes de pasarlas al tracker. track() mezcla todas las clases y
        # puede causar que una cabeza "robe" el ID de una moto.
        t0 = time.perf_counter()
        results = self.detection_model.predict(
            frame,
            imgsz=self.imgsz,
            conf=0.10,
            iou=0.6,
            verbose=False
        )[0]
        infer_time_ms = (time.perf_counter() - t0) * 1000

        raw_detections = []
        duplicate_riders = []
        classified_riders = []
        riders_ready = []
        all_tracking_crops = []

        if results.boxes is None or len(results.boxes) == 0:
            return {
                'raw_detections': raw_detections,
                'duplicate_riders': duplicate_riders,
                'classified_riders': classified_riders,
                'riders_ready_to_process': riders_ready,
                'all_tracking_crops': all_tracking_crops
            }

        boxes_obj = results.boxes          # Objeto Boxes de Ultralytics
        boxes = boxes_obj.xyxy.cpu().numpy()
        confidences = boxes_obj.conf.cpu().numpy()
        classes = boxes_obj.cls.cpu().numpy().astype(int)

        # ==================================================================
        # PASO 2: Separar motos y cabezas por ID de clase
        # ==================================================================
        moto_mask = np.isin(classes, list(self.moto_ids))
        head_mask = np.isin(classes, list(self.head_ids))

        # ==================================================================
        # ==================================================================
        # PASO 3: Tracker manual — SOLO motos → IDs estables sin interferencia
        # ==================================================================
        tracked_motos = []

        if self.tracker is not None:
            moto_boxes_obj = boxes_obj[moto_mask]

            if len(moto_boxes_obj) > 0:
                # BYTETracker.update() espera un objeto con .conf, .cls, .xywh
                # que soporte boolean indexing. boxes_obj[mask] lo hace correctamente.
                # Retorna np.array de shape (N, 8): [x1,y1,x2,y2,track_id,score,cls,idx]
                tracks = self.tracker.update(moto_boxes_obj.cpu(), frame)

                for t in tracks:
                    x1, y1, x2, y2 = map(int, t[:4])
                    # Clampear a los bordes del frame
                    x1 = max(0, x1)
                    y1 = max(0, y1)
                    x2 = min(frame.shape[1], x2)
                    y2 = min(frame.shape[0], y2)
                    if x2 <= x1 or y2 <= y1:
                        continue
                    tracked_motos.append({
                        'bbox': (x1, y1, x2, y2),
                        'track_id': str(int(t[4])),
                        'conf': float(t[5]),
                        'local_idx': int(t[7]) if len(t) > 7 else -1
                    })
        else:
            # Fallback: sin tracker, usar detecciones directas (IDs no estables)
            for i in range(len(boxes)):
                if not moto_mask[i]:
                    continue
                if confidences[i] < self.det_conf:
                    continue
                x1, y1, x2, y2 = map(int, boxes[i])
                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(frame.shape[1], x2)
                y2 = min(frame.shape[0], y2)
                if x2 <= x1 or y2 <= y1:
                    continue
                tracked_motos.append({
                    'bbox': (x1, y1, x2, y2),
                    'track_id': f"notrack_{i}",
                    'conf': float(confidences[i])
                })

        # ==================================================================
        # PASO 4: Filtrar cabezas (umbral propio + tamaño mínimo)
        # ==================================================================
        cabezas = []
        for i in range(len(boxes)):
            if not head_mask[i]:
                continue
            if confidences[i] < self.head_conf:
                continue
            x1, y1, x2, y2 = map(int, boxes[i])
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(frame.shape[1], x2)
            y2 = min(frame.shape[0], y2)
            if x2 <= x1 or y2 <= y1:
                continue
            # Filtro de tamaño mínimo: cabezas de <16px son ruido
            min_side = min(x2 - x1, y2 - y1)
            if min_side < self.min_head_size:
                continue
            cabezas.append({
                'bbox': (x1, y1, x2, y2),
                'conf': float(confidences[i])
            })

        # ==================================================================
        # PASO 5: Construir raw_detections para el overlay de la UI
        # ==================================================================
        for i in range(len(boxes)):
            x1, y1, x2, y2 = map(int, boxes[i])
            class_name = self.detection_model.names.get(int(classes[i]), 'desconocido').lower()
            # Buscar si esta detección de moto tiene track_id asignado
            tid_str = "untracked"
            if moto_mask[i]:
                # Índice relativo dentro del subset de motos
                local_i = int(np.sum(moto_mask[:i]))
                for tm in tracked_motos:
                    if tm.get('local_idx', -1) == local_i:
                        tid_str = tm['track_id']
                        break
                    # Fallback por cercanía
                    elif tm.get('local_idx', -1) == -1 and (abs(tm['bbox'][0] - x1) < 20 and abs(tm['bbox'][1] - y1) < 20):
                        tid_str = tm['track_id']
                        break
            raw_detections.append((x1, y1, x2, y2, float(confidences[i]), class_name, tid_str))

        # ==================================================================
        # PASO 6: Asignación exclusiva de cabezas a motos
        # ==================================================================
        # Cada cabeza se asigna a UNA SOLA moto (la de mayor solapamiento).
        cabeza_assignments = self._assign_heads_exclusive(cabezas, tracked_motos)

        # ====== DEBUG TRACKING ======
        motos_count = int(moto_mask.sum())
        confs = [round(float(c), 2) for c in confidences[moto_mask]] if motos_count > 0 else []
        ids = [m['track_id'] for m in tracked_motos]
        cab_asignadas = {k: len(v) for k, v in cabeza_assignments.items()}
        hist = {k: (len(v['frames']), v['total_frames_seen']) for k, v in self.track_history.items()}
        print(f"[Track] infer={infer_time_ms:.1f}ms | motos={motos_count} confs={confs} | "
              f"ids={ids} | cab_asign={cab_asignadas} | hist={hist}")
        # ============================

        current_time = time.time()

        # ==================================================================
        # PASO 7: Acumular frames y clasificar por moto
        # ==================================================================
        for moto in tracked_motos:
            track_id = moto['track_id']
            cabezas_asociadas = cabeza_assignments.get(track_id, [])

            # Si no hay cabeza asociada, mantener el track vivo pero no acumular
            if not cabezas_asociadas:
                if track_id in self.track_history:
                    self.track_history[track_id]['last_seen'] = current_time
                continue

            # Inicializar historial si es la primera vez que vemos este track_id
            if track_id not in self.track_history:
                self.track_history[track_id] = {
                    'frames': [],           # Frames de buena calidad acumulados
                    'final_status': None,   # Resultado final (None = aún clasificando)
                    'final_confidence': None,
                    'final_cabezas': [],
                    'last_seen': current_time,
                    'total_frames_seen': 0  # Todos los frames vistos (no solo buenos)
                }

            self.track_history[track_id]['last_seen'] = current_time
            history = self.track_history[track_id]
            history['total_frames_seen'] += 1

            # --- CASO A: Ya clasificada → reportar como duplicada ---
            if history['final_status'] is not None:
                # Lazy PIL: solo crear cuando realmente la necesitamos
                mx1, my1, mx2, my2 = moto['bbox']
                my1, my2 = max(0, my1), min(frame.shape[0], my2)
                mx1, mx2 = max(0, mx1), min(frame.shape[1], mx2)
                moto_crop_bgr = frame[my1:my2, mx1:mx2]
                moto_crop_rgb = cv2.cvtColor(moto_crop_bgr, cv2.COLOR_BGR2RGB) if moto_crop_bgr.size > 0 else np.zeros((10,10,3), dtype=np.uint8)
                moto_crop = Image.fromarray(moto_crop_rgb)

                all_tracking_crops.append({
                    'track_id': track_id,
                    'moto_crop': moto_crop,
                    'status': history['final_status']
                })
                duplicate_riders.append({
                    'track_id': track_id,
                    'bbox': moto['bbox'],
                    'detection_conf': moto['conf']
                })
                continue

            # --- CASO B: Acumular y clasificar incrementalmente ---
            quality = self._compute_frame_quality(cabezas_asociadas, frame.shape)

            if quality > 0:
                cabezas_crops = []
                crops_to_classify = []
                for cab in cabezas_asociadas:
                    cx1, cy1, cx2, cy2 = cab['bbox']
                    cy1, cy2 = max(0, cy1), min(frame.shape[0], cy2)
                    cx1, cx2 = max(0, cx1), min(frame.shape[1], cx2)
                    crop_bgr = frame[cy1:cy2, cx1:cx2]
                    crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB) if crop_bgr.size > 0 else np.zeros((10,10,3), dtype=np.uint8)
                    crops_to_classify.append(Image.fromarray(crop_rgb))
                    cabezas_crops.append({
                        'crop_bgr': crop_bgr,
                        'bbox': cab['bbox'],
                        'conf': cab['conf']
                    })

                # Clasificar este frame inmediatamente
                batch_results = []
                if crops_to_classify:
                    batch_results = self.classifier.classify_batch(crops_to_classify)

                sin_casco_confs = []
                con_casco_confs = []

                for c_idx, (helmet_status_raw, helmet_conf) in enumerate(batch_results):
                    is_sin_casco = 'sin' in helmet_status_raw.lower()
                    if is_sin_casco and helmet_conf >= self.cls_conf:
                        cabezas_crops[c_idx]['helmet_status'] = helmet_status_raw
                        cabezas_crops[c_idx]['helmet_conf'] = helmet_conf
                        sin_casco_confs.append(helmet_conf)
                    elif not is_sin_casco and helmet_conf >= self.cls_conf:
                        cabezas_crops[c_idx]['helmet_status'] = 'con_casco'
                        cabezas_crops[c_idx]['helmet_conf'] = helmet_conf
                        con_casco_confs.append(helmet_conf)
                    else:
                        cabezas_crops[c_idx]['helmet_status'] = 'indeterminado'
                        cabezas_crops[c_idx]['helmet_conf'] = helmet_conf

                # Voto del frame (acompañante mancha todo el frame)
                frame_verdict = "indeterminado"
                frame_conf = 0.0
                if sin_casco_confs:
                    frame_verdict = "sin_casco"
                    frame_conf = max(sin_casco_confs)
                elif con_casco_confs:
                    frame_verdict = "con_casco"
                    frame_conf = sum(con_casco_confs) / max(1, len(con_casco_confs))

                mx1, my1, mx2, my2 = moto['bbox']
                my1, my2 = max(0, my1), min(frame.shape[0], my2)
                mx1, mx2 = max(0, mx1), min(frame.shape[1], mx2)
                moto_crop_bgr = frame[my1:my2, mx1:mx2]

                frame_data = {
                    'moto': moto,
                    'moto_crop_bgr': moto_crop_bgr,
                    'cabezas_crops': cabezas_crops,
                    'interval_counter': interval_counter,
                    'quality': quality,
                    'verdict': frame_verdict,
                    'conf': frame_conf
                }

                history['frames'].append(frame_data)
                
                # Conservar los mejores frames en memoria
                if len(history['frames']) > self.max_frames:
                    history['frames'].sort(key=lambda f: f['quality'], reverse=True)
                    history['frames'] = history['frames'][:self.max_frames]

            num_good_frames = len(history['frames'])
            
            # Contar votos
            sin_votes = [f for f in history['frames'] if f['verdict'] == 'sin_casco']
            con_votes = [f for f in history['frames'] if f['verdict'] == 'con_casco']
            
            final_status = None
            best_frame = None
            
            # --- CASO B1: Clasificación definitiva por mayoría absoluta ---
            if len(sin_votes) >= self.min_frames:
                final_status = 'sin_casco'
                best_frame = max(sin_votes, key=lambda f: f['quality'])
            elif len(con_votes) >= self.min_frames:
                final_status = 'con_casco'
                best_frame = max(con_votes, key=lambda f: f['quality'])
            
            # --- CASO B2: Track viejo/largo, forzar resolución ---
            elif history['total_frames_seen'] >= self.max_frames * 2 and (sin_votes or con_votes):
                if len(sin_votes) >= len(con_votes):
                    final_status = 'sin_casco'
                    best_frame = max(sin_votes, key=lambda f: f['quality'])
                else:
                    final_status = 'con_casco'
                    best_frame = max(con_votes, key=lambda f: f['quality'])

            # --- CASO B3: Pendiente ---
            if final_status is None:
                status = f"pendiente_{num_good_frames}"
                if num_good_frames > 0:
                    best_f = max(history['frames'], key=lambda f: f['quality'])
                    bgr_moto = best_f['moto_crop_bgr']
                    moto_rgb = cv2.cvtColor(bgr_moto, cv2.COLOR_BGR2RGB) if bgr_moto.size > 0 else np.zeros((10,10,3), dtype=np.uint8)
                    moto_crop = Image.fromarray(moto_rgb)
                    all_tracking_crops.append({
                        'track_id': track_id,
                        'moto_crop': moto_crop,
                        'status': status
                    })
                    riders_ready.append({
                        'track_id': track_id,
                        'bbox': moto['bbox'],
                        'detection_conf': moto['conf'],
                        'helmet_status': status,
                        'helmet_confidence': 0.0,
                        'crop_image': moto_crop,
                        'cabezas': []
                    })
                continue

            # --- CASO C: Emitir veredicto final ---
            history['final_status'] = final_status
            history['final_confidence'] = best_frame['conf']

            # Armar reporte
            report_lines = [
                f"Track ID: {track_id}",
                f"Veredicto Final: {final_status.upper()} (Confianza: {best_frame['conf']:.2f})",
                f"Votos consolidados: Sin casco = {len(sin_votes)}, Con casco = {len(con_votes)}",
                f"Frames buenos: {num_good_frames} (de {history['total_frames_seen']} vistos en total)",
                "-" * 30
            ]
            for f_data in history['frames']:
                f_verdict = f_data['verdict']
                frame_ic = f_data.get('interval_counter', 0)
                report_lines.append(f"f{frame_ic}_trk{track_id}_{f_verdict}.jpg: Votó -> {f_verdict.upper()} (quality: {f_data.get('quality', 0):.1f})")
                for c_idx, cab in enumerate(f_data['cabezas_crops']):
                    report_lines.append(f"  - Cabeza {c_idx + 1}: {cab.get('helmet_status', '?')} (conf: {cab.get('helmet_conf', 0.0):.2f})")

            # Armar cabezas finales (del best frame)
            final_cabezas = []
            for c in best_frame['cabezas_crops']:
                bgr = c['crop_bgr']
                crop_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB) if bgr.size > 0 else np.zeros((10,10,3), dtype=np.uint8)
                final_cabezas.append({
                    'bbox': c['bbox'],
                    'crop_image': Image.fromarray(crop_rgb),
                    'helmet_status': c.get('helmet_status', final_status)
                })
            history['final_cabezas'] = final_cabezas
            
            bgr_moto = best_frame['moto_crop_bgr']
            moto_rgb = cv2.cvtColor(bgr_moto, cv2.COLOR_BGR2RGB) if bgr_moto.size > 0 else np.zeros((10,10,3), dtype=np.uint8)
            final_moto_pil = Image.fromarray(moto_rgb)

            all_tracking_crops.append({
                'track_id': track_id,
                'moto_crop': final_moto_pil,
                'status': final_status,
                'report_text': "\n".join(report_lines)
            })

            final_data = {
                'track_id': track_id,
                'bbox': best_frame['moto']['bbox'],
                'detection_conf': best_frame['moto']['conf'],
                'helmet_status': final_status,
                'helmet_confidence': best_frame['conf'],
                'crop_image': final_moto_pil,
                'cabezas': history['final_cabezas']
            }
            classified_riders.append(final_data)
            riders_ready.append(final_data)

        # ==================================================================
        # PASO 8: Limpiar tracks viejos (>15 segundos sin verse)
        # ==================================================================
        tracks_to_delete = [
            tid for tid, h in self.track_history.items()
            if current_time - h['last_seen'] > 15
        ]
        for tid in tracks_to_delete:
            del self.track_history[tid]

        return {
            'raw_detections': raw_detections,
            'duplicate_riders': duplicate_riders,
            'classified_riders': classified_riders,
            'riders_ready_to_process': riders_ready,
            'all_tracking_crops': all_tracking_crops,
        }