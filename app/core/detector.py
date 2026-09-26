import time
from typing import Any, Dict, List
import cv2
import numpy as np
from PIL import Image
from ultralytics import YOLO
from .classifier import HelmetClassifier


class MotorcycleDetector:
    """
    Pipeline de detección Híbrido:
    
    1. Detecta y trackea 'moto' y 'cabeza' usando YOLOv8 Nano (alto FPS).
    2. Asocia geométricamente las 'cabezas' que están dentro de una 'moto'.
    3. Cuando una 'moto' es detectada por primera vez (nuevo track_id),
       se recortan todas sus 'cabezas' asociadas y se pasan al clasificador Medium.
    4. Aplica la regla del acompañante: Si al menos 1 cabeza no tiene casco, la moto está en infracción.
    """

    def __init__(self, config: dict, classifier: HelmetClassifier = None):
        self.det_conf = config['detection'].get('confidence_threshold', 0.5)
        self.cls_conf = config['classification'].get('confidence_threshold', 0.5)
        self.frames_to_classify = config.get('detection', {}).get('frames_to_classify', 3)
        self.inside_threshold = config.get('detection', {}).get('inside_threshold', 0.90)
        
        self.track_history = {}
        
        print("[Detector] Cargando YOLO detección (Nano Tracker)...")
        self.detection_model = YOLO(config['models']['detection'])
        
        if classifier is not None:
            print("[Detector] Usando clasificador cascos compartido...")
            self.classifier = classifier
        else:
            print("[Detector] Cargando clasificador cascos (Medium Classifier)...")
            self.classifier = HelmetClassifier(config['models']['classification'])
        
        # Nombres de clases esperados del modelo detector
        self.MOTO_CLASS_NAMES = ['moto', 'motorcycle', 'rider']
        self.HEAD_CLASS_NAMES = ['cabeza_torso', 'cabeza', 'head', 'torso', 'person']
        self.untracked_counter = 1
        
        print("[Detector] Listo")

    def reset(self):
        """Limpia el historial de track IDs (para nueva sesión)."""
        self.track_history = {}
        self.untracked_counter = 1
        
    def _is_inside(self, inner_box, outer_box):
        """Verifica si inner_box está dentro de outer_box (>= 95% de su area itersectada)."""
        ix1 = max(inner_box[0], outer_box[0])
        iy1 = max(inner_box[1], outer_box[1])
        ix2 = min(inner_box[2], outer_box[2])
        iy2 = min(inner_box[3], outer_box[3])
        
        inter_area = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter_area == 0:
            return False
            
        inner_area = (inner_box[2] - inner_box[0]) * (inner_box[3] - inner_box[1])
        return (inter_area / float(inner_area)) >= self.inside_threshold if inner_area > 0 else False

    def process_frame(self, frame: Any, cam_id: int, interval_counter: int = 0) -> Dict[str, Any]:
        """
        Procesa un frame usando tracking nativo y asociación geométrica.
        """
        # Ensure frame size is consistent for tracker
        if not hasattr(self, 'last_frame_shape'):
            self.last_frame_shape = frame.shape
        elif self.last_frame_shape != frame.shape:
            # Resize frame to match previous shape to avoid OpenCV tracker assertion error
            frame = cv2.resize(frame, (self.last_frame_shape[1], self.last_frame_shape[0]))

        # Tracking nativo de YOLO
        results = self.detection_model.track(
            frame, persist=True, conf=self.det_conf, verbose=False, tracker="config/tracker.yaml"
        )

        raw_detections = []
        duplicate_riders = []
        classified_riders = []
        riders_ready = []
        all_tracking_crops = []

        if not (results and results[0].boxes is not None and len(results[0].boxes)):
            return {
                'raw_detections': raw_detections,
                'duplicate_riders': duplicate_riders,
                'classified_riders': classified_riders,
                'riders_ready_to_process': riders_ready,
                'all_tracking_crops': all_tracking_crops
            }

        boxes = results[0].boxes.xyxy.cpu().numpy()
        confidences = results[0].boxes.conf.cpu().numpy()
        classes = results[0].boxes.cls.cpu().numpy()
        track_ids = (
            results[0].boxes.id.cpu().numpy()
            if results[0].boxes.id is not None
            else [None] * len(boxes)
        )

        motos = []
        cabezas = []

        # Separate detections
        for box, conf, cls, tid in zip(boxes, confidences, classes, track_ids):
            x1, y1, x2, y2 = map(int, box)
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(frame.shape[1], x2)
            y2 = min(frame.shape[0], y2)
            if x2 <= x1 or y2 <= y1:
                continue
                
            class_name = self.detection_model.names.get(int(cls), 'rider').lower()
            if tid is not None:
                track_id_str = str(int(tid))
            else:
                track_id_str = f"untracked_{self.untracked_counter}"
                self.untracked_counter += 1
            
            det_data = {
                'bbox': (x1, y1, x2, y2),
                'conf': float(conf),
                'class_name': class_name,
                'track_id': track_id_str
            }
            raw_detections.append((x1, y1, x2, y2, float(conf), class_name, track_id_str))

            if any(name in class_name for name in self.MOTO_CLASS_NAMES):
                motos.append(det_data)
            elif any(name in class_name for name in self.HEAD_CLASS_NAMES):
                cabezas.append(det_data)
            else:
                # Fallback: si solo está entrenado en una clase temporalmente
                motos.append(det_data)

        pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        current_time = time.time()

        # Geometric association
        for moto in motos:
            track_id = moto['track_id']
            moto['cabezas_asociadas'] = []
            
            for cabeza in cabezas:
                if self._is_inside(cabeza['bbox'], moto['bbox']):
                    moto['cabezas_asociadas'].append(cabeza)
            
            # Si no hay cabeza_torso real asociada, mantener el track vivo
            # pero no acumular este frame hacia el umbral de clasificación.
            # Solo frames con rider visible (cabeza detectada) cuentan.
            if not moto['cabezas_asociadas']:
                if track_id in self.track_history:
                    self.track_history[track_id]['last_seen'] = current_time
                continue
                
            # Prepare crops for this frame
            cabezas_crops = []
            for cabeza in moto['cabezas_asociadas']:
                cx1, cy1, cx2, cy2 = cabeza['bbox']
                crop_pil = pil_img.crop((int(cx1), int(cy1), int(cx2), int(cy2)))
                cabezas_crops.append({
                    'crop_pil': crop_pil,
                    'bbox': cabeza['bbox'],
                    'conf': cabeza['conf']
                })
                
            mx1, my1, mx2, my2 = moto['bbox']
            moto_crop = pil_img.crop((int(mx1), int(my1), int(mx2), int(my2)))
            
            if track_id not in self.track_history:
                self.track_history[track_id] = {
                    'frames': [],
                    'final_status': None,
                    'final_confidence': None,
                    'final_cabezas': [],
                    'last_seen': current_time
                }
                
            self.track_history[track_id]['last_seen'] = current_time
            history = self.track_history[track_id]
            
            if history['final_status'] is None:
                history['frames'].append({
                    'moto': moto,
                    'moto_crop': moto_crop,
                    'cabezas_crops': cabezas_crops,
                    'interval_counter': interval_counter
                })
                
                num_frames = len(history['frames'])
                
                if num_frames < self.frames_to_classify:
                    status = f"pendiente_{num_frames}"
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
                elif num_frames == self.frames_to_classify:
                    # Classify all frames
                    crops_to_classify = []
                    metadata_to_classify = []
                    
                    for f_idx, frame_data in enumerate(history['frames']):
                        for c_idx, cab_crop in enumerate(frame_data['cabezas_crops']):
                            crops_to_classify.append(cab_crop['crop_pil'])
                            metadata_to_classify.append({
                                'frame_idx': f_idx,
                                'cab_idx': c_idx
                            })
                            
                    batch_results = []
                    if crops_to_classify:
                        batch_results = self.classifier.classify_batch(crops_to_classify)
                        
                    frame_results = [{'sin_casco_confs': [], 'con_casco_confs': []} for _ in range(self.frames_to_classify)]
                    
                    # Guardar resultados en las estructuras
                    for (helmet_status, helmet_conf), meta in zip(batch_results, metadata_to_classify):
                        f_idx = meta['frame_idx']
                        c_idx = meta['cab_idx']
                        
                        is_sin_casco = 'sin' in helmet_status.lower() and helmet_conf >= self.cls_conf
                        
                        if is_sin_casco:
                            history['frames'][f_idx]['cabezas_crops'][c_idx]['helmet_status'] = helmet_status
                            history['frames'][f_idx]['cabezas_crops'][c_idx]['helmet_conf'] = helmet_conf
                            frame_results[f_idx]['sin_casco_confs'].append(helmet_conf)
                        else:
                            history['frames'][f_idx]['cabezas_crops'][c_idx]['helmet_status'] = 'con_casco'
                            history['frames'][f_idx]['cabezas_crops'][c_idx]['helmet_conf'] = helmet_conf
                            frame_results[f_idx]['con_casco_confs'].append(helmet_conf)
                            
                    # Determinar el voto de cada frame
                    sin_casco_votes = 0
                    con_casco_votes = 0
                    sin_casco_winning_confs = []
                    con_casco_winning_confs = []
                    frame_verdicts = []
                    
                    for f_res in frame_results:
                        if f_res['sin_casco_confs']:
                            # Si hay al menos una cabeza sin casco, el frame vota sin casco
                            conf = max(f_res['sin_casco_confs'])
                            sin_casco_votes += 1
                            sin_casco_winning_confs.append(conf)
                            frame_verdicts.append('sin_casco')
                        else:
                            # Si todas tienen casco, el frame vota con casco
                            conf = sum(f_res['con_casco_confs']) / max(1, len(f_res['con_casco_confs'])) if f_res['con_casco_confs'] else 0.0
                            con_casco_votes += 1
                            con_casco_winning_confs.append(conf)
                            frame_verdicts.append('con_casco')
                            
                    # Votación por mayoría y desempate
                    if sin_casco_votes > con_casco_votes:
                        final_status = "sin_casco"
                    elif con_casco_votes > sin_casco_votes:
                        final_status = "con_casco"
                    else:
                        # Empate, decide la confianza promedio
                        avg_sin = sum(sin_casco_winning_confs) / max(1, len(sin_casco_winning_confs)) if sin_casco_winning_confs else 0
                        avg_con = sum(con_casco_winning_confs) / max(1, len(con_casco_winning_confs)) if con_casco_winning_confs else 0
                        final_status = "sin_casco" if avg_sin > avg_con else "con_casco"
                        
                    if final_status == "sin_casco":
                        final_conf = sum(sin_casco_winning_confs) / max(1, len(sin_casco_winning_confs)) if sin_casco_winning_confs else 0
                    else:
                        final_conf = sum(con_casco_winning_confs) / max(1, len(con_casco_winning_confs)) if con_casco_winning_confs else 0
                        
                    history['final_status'] = final_status
                    history['final_confidence'] = final_conf
                    
                    # Armar reporte de votación para el log de tracking
                    report_lines = [
                        f"Track ID: {track_id}",
                        f"Veredicto Final: {final_status.upper()} (Confianza: {final_conf:.2f})",
                        f"Votos: Sin casco = {sin_casco_votes}, Con casco = {con_casco_votes}",
                        "-" * 30
                    ]
                    
                    # Seleccionar el frame de evidencia: el más grande que apoye el veredicto
                    best_frame = history['frames'][0]
                    max_area = 0
                    
                    for f_idx, (f_data, f_verdict) in enumerate(zip(history['frames'], frame_verdicts)):
                        frame_ic = f_data.get('interval_counter', 0)
                        # Reconstruir el nombre de archivo con el que se guardó o se guardará
                        if f_idx < self.frames_to_classify - 1:
                            # Los frames anteriores se guardaron como pendientes
                            filename = f"f{frame_ic}_trk{track_id}_pendiente_{f_idx + 1}.jpg"
                        else:
                            # El último frame se guarda con el status final
                            filename = f"f{frame_ic}_trk{track_id}_{final_status}.jpg"
                            
                        report_lines.append(f"{filename}: Votó -> {f_verdict.upper()}")
                        for c_idx, cab in enumerate(f_data['cabezas_crops']):
                            c_stat = cab.get('helmet_status', 'desconocido')
                            c_conf = cab.get('helmet_conf', 0.0)
                            report_lines.append(f"  - Cabeza {c_idx + 1}: {c_stat} (conf: {c_conf:.2f})")
                            
                        if f_verdict == final_status:
                            mx1, my1, mx2, my2 = f_data['moto']['bbox']
                            area = (mx2 - mx1) * (my2 - my1)
                            if area > max_area:
                                max_area = area
                                best_frame = f_data
                                
                    if max_area == 0:
                        best_frame = history['frames'][-1]
                            
                    final_cabezas = []
                    for c in best_frame['cabezas_crops']:
                        final_cabezas.append({
                            'bbox': c['bbox'],
                            'crop_image': c['crop_pil'],
                            'helmet_status': c.get('helmet_status', final_status)
                        })
                    history['final_cabezas'] = final_cabezas
                    
                    all_tracking_crops.append({
                        'track_id': track_id,
                        'moto_crop': moto_crop, # Para la carpeta de tracking mantenemos el crop actual
                        'status': final_status,
                        'report_text': "\n".join(report_lines)
                    })
                    
                    final_data = {
                        'track_id': track_id,
                        'bbox': best_frame['moto']['bbox'],
                        'detection_conf': best_frame['moto']['conf'],
                        'helmet_status': final_status,
                        'helmet_confidence': final_conf,
                        'crop_image': best_frame['moto_crop'],
                        'cabezas': history['final_cabezas']
                    }
                    classified_riders.append(final_data)
                    riders_ready.append(final_data)
                
            else:
                # Ya evaluada
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

        # Limpiar track_history
        tracks_to_delete = []
        for tid, h in self.track_history.items():
            if current_time - h['last_seen'] > 15:
                tracks_to_delete.append(tid)
        for tid in tracks_to_delete:
            del self.track_history[tid]

        return {
            'raw_detections': raw_detections,
            'duplicate_riders': duplicate_riders,
            'classified_riders': classified_riders,
            'riders_ready_to_process': riders_ready,
            'all_tracking_crops': all_tracking_crops,
        }