"""
Base de datos SQLite para almacenar detecciones e infracciones
"""
import sqlite3
from datetime import datetime
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
import threading



class Database:
    """Maneja persistencia de datos con SQLite"""
    
    def __init__(self, db_path='data/detections.db'):
        """
        Args:
            db_path: Path a la base de datos SQLite
        """
        self.db_path = db_path
        
        # Crear directorio si no existe
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        self.conn = None
        self.lock = threading.Lock()
        self._create_tables()
    
    def _get_connection(self):
        """Obtiene conexión a la base de datos"""
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
        return self.conn
    
    def _create_tables(self):
        """Crea las tablas necesarias"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Tabla de detecciones
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                datetime TEXT NOT NULL,
                bbox TEXT NOT NULL,
                class_name TEXT NOT NULL,
                confidence REAL NOT NULL,
                helmet_status TEXT,
                helmet_confidence REAL,
                camera_id INTEGER DEFAULT 0
            )
        ''')
        
        # Tabla de infracciones (riders sin casco)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS violations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                datetime TEXT NOT NULL,
                bbox TEXT NOT NULL,
                confidence REAL NOT NULL,
                helmet_confidence REAL,
                camera_id INTEGER DEFAULT 0,
                crop_path TEXT
            )
        ''')
        
        # Migrar tablas existentes: agregar camera_id si no existe
        try:
            cursor.execute('ALTER TABLE detections ADD COLUMN camera_id INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass  # Columna ya existe
        
        try:
            cursor.execute('ALTER TABLE violations ADD COLUMN camera_id INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass  # Columna ya existe

        try:
            cursor.execute('ALTER TABLE violations ADD COLUMN crop_path TEXT')
        except sqlite3.OperationalError:
            pass  # Columna ya existe
        
        conn.commit()
        print(f"[Database] Tablas creadas/verificadas en {self.db_path}")
    
    def insert_detection(self, detection):
        """
        Inserta una detección en la base de datos
        
        Args:
            detection: Objeto Detection
        """
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            camera_id = getattr(detection, 'camera_id', 0)
            
            cursor.execute('''
                INSERT INTO detections 
                (timestamp, datetime, bbox, class_name, confidence, helmet_status, helmet_confidence, camera_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                detection.timestamp,
                datetime.fromtimestamp(detection.timestamp).isoformat(),
                json.dumps(detection.bbox),
                detection.class_name,
                detection.confidence,
                detection.helmet_status,
                detection.helmet_confidence,
                camera_id
            ))
            
            conn.commit()
    
    def insert_violation(self, rider_detection, camera_id=0, crop_path: Optional[str] = None):
        """
        Inserta una infracción (sin casco)
        
        Args:
            rider_detection: Lista [x1,y1,x2,y2,conf,helmet_status,helmet_conf]
            camera_id: ID de la cámara
            crop_path: Ruta relativa del recorte de la infracción
        """
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            timestamp = datetime.now().timestamp()
            
            cursor.execute('''
                INSERT INTO violations 
                (timestamp, datetime, bbox, confidence, helmet_confidence, camera_id, crop_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                timestamp,
                datetime.fromtimestamp(timestamp).isoformat(),
                json.dumps(rider_detection[:4]),
                rider_detection[4],
                rider_detection[6] if len(rider_detection) > 6 else 0.0,
                camera_id,
                crop_path
            ))
            
            conn.commit()
    
    def get_recent_violations(self, limit=50, camera_id=None):
        """
        Obtiene las infracciones más recientes
        
        Args:
            limit: Número máximo de infracciones a retornar
            camera_id: Filtrar por cámara (None = todas)
        
        Returns:
            List[dict]: Lista de infracciones
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if camera_id is not None:
            cursor.execute('''
                SELECT * FROM violations 
                WHERE camera_id = ?
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (camera_id, limit))
        else:
            cursor.execute('''
                SELECT * FROM violations 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (limit,))
        
        rows = cursor.fetchall()
        
        violations = []
        for row in rows:
            v = {
                'id': row['id'],
                'timestamp': row['timestamp'],
                'datetime': row['datetime'],
                'bbox': json.loads(row['bbox']),
                'confidence': row['confidence'],
                'helmet_confidence': row['helmet_confidence']
            }
            # camera_id puede no existir en registros viejos
            try:
                v['camera_id'] = row['camera_id']
            except (IndexError, KeyError):
                v['camera_id'] = 0
            try:
                v['crop_path'] = row['crop_path']
            except (IndexError, KeyError):
                v['crop_path'] = None
            violations.append(v)
        
        return violations
    
    def get_total_counts(self):
        """
        Obtiene conteos totales
        
        Returns:
            dict: Conteos totales de detecciones y violaciones
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) as count FROM detections')
        total_detections = cursor.fetchone()['count']
        
        cursor.execute('SELECT COUNT(*) as count FROM violations')
        total_violations = cursor.fetchone()['count']
        
        cursor.execute('''
            SELECT COUNT(*) as count FROM detections 
            WHERE helmet_status = "con_casco"
        ''')
        with_helmet = cursor.fetchone()['count']
        
        return {
            'total_detections': total_detections,
            'total_violations': total_violations,
            'with_helmet': with_helmet
        }
    
    def get_violations_since(self, start_timestamp, camera_id=None):
        """
        Obtiene TODAS las detecciones (con y sin casco) desde un timestamp
        
        Args:
            start_timestamp: Timestamp de inicio
            camera_id: Filtrar por cámara (None = todas)
        
        Returns:
            List[dict]: Lista de detecciones con helmet_status
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if camera_id is not None:
            cursor.execute('''
                SELECT timestamp, helmet_status, helmet_confidence, camera_id
                FROM detections 
                WHERE timestamp >= ? AND helmet_status IS NOT NULL AND camera_id = ?
                ORDER BY timestamp DESC
            ''', (start_timestamp, camera_id))
        else:
            cursor.execute('''
                SELECT timestamp, helmet_status, helmet_confidence, camera_id
                FROM detections 
                WHERE timestamp >= ? AND helmet_status IS NOT NULL
                ORDER BY timestamp DESC
            ''', (start_timestamp,))
        
        rows = cursor.fetchall()
        
        violations = []
        for row in rows:
            v = {
                'timestamp': row['timestamp'],
                'helmet_status': row['helmet_status'],
                'helmet_confidence': row['helmet_confidence']
            }
            try:
                v['camera_id'] = row['camera_id']
            except (IndexError, KeyError):
                v['camera_id'] = 0
            violations.append(v)
        
        return violations
    
    def get_heatmap_data(self, start_timestamp, cameras_config):
        """
        Obtiene datos para el heatmap del mapa: conteo de detecciones 
        sin casco agrupadas por cámara, con lat/lng.
        
        Args:
            start_timestamp: Timestamp de inicio
            cameras_config: Lista de dicts con config de cámaras (id, lat, lng, name)
        
        Returns:
            List[dict]: [{lat, lng, count, name, camera_id, con_casco, sin_casco}, ...]
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Obtener conteos por cámara
        cursor.execute('''
            SELECT camera_id, helmet_status, COUNT(*) as count
            FROM detections
            WHERE timestamp >= ? AND helmet_status IS NOT NULL
            GROUP BY camera_id, helmet_status
        ''', (start_timestamp,))
        
        rows = cursor.fetchall()
        
        # Agrupar por camera_id
        cam_stats = {}
        for row in rows:
            cid = row['camera_id']
            if cid not in cam_stats:
                cam_stats[cid] = {'con_casco': 0, 'sin_casco': 0}
            status = row['helmet_status']
            if 'con' in status.lower():
                cam_stats[cid]['con_casco'] = row['count']
            elif 'sin' in status.lower():
                cam_stats[cid]['sin_casco'] = row['count']
        
        # Combinar con coordenadas de las cámaras
        result = []
        for cam in cameras_config:
            cid = cam['id']
            stats = cam_stats.get(cid, {'con_casco': 0, 'sin_casco': 0})
            result.append({
                'camera_id': cid,
                'name': cam['name'],
                'lat': cam['lat'],
                'lng': cam['lng'],
                'con_casco': stats['con_casco'],
                'sin_casco': stats['sin_casco'],
                'total': stats['con_casco'] + stats['sin_casco'],
                'intensity': stats['sin_casco']  # Intensidad del heatmap = sin casco
            })
        
        return result
    
    def get_dashboard_stats(self, cameras_config=None) -> Dict[str, Any]:
        """
        Obtiene métricas agregadas para el dashboard de estadísticas.
        
        Args:
            cameras_config: Opcional, lista de objetos o dicts de cámaras (id, name, etc.)
        
        Returns:
            dict: Métricas agregadas con total_violations, total_detections,
                  compliance_rate, by_camera, by_hour
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Conteos totales
        cursor.execute('SELECT COUNT(*) as count FROM violations')
        total_violations = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) as count FROM detections WHERE helmet_status NOT LIKE 'pendiente%'")
        total_detections = cursor.fetchone()['count']
        
        cursor.execute('''
            SELECT COUNT(*) as count FROM detections 
            WHERE LOWER(helmet_status) LIKE '%con%' AND helmet_status NOT LIKE 'pendiente%'
        ''')
        with_helmet = cursor.fetchone()['count']
        
        if total_detections > 0:
            compliance_rate = round((with_helmet / total_detections) * 100.0, 2)
        elif total_violations > 0:
            compliance_rate = 0.0
        else:
            compliance_rate = 0.0
        
        # Violaciones agrupadas por cámara
        cursor.execute('''
            SELECT camera_id, COUNT(*) as violations
            FROM violations
            GROUP BY camera_id
            ORDER BY camera_id ASC
        ''')
        cam_violation_rows = cursor.fetchall()
        cam_violations_map = {row['camera_id']: row['violations'] for row in cam_violation_rows}
        
        cursor.execute('''
            SELECT camera_id, COUNT(*) as detections
            FROM detections
            WHERE helmet_status NOT LIKE 'pendiente%'
            GROUP BY camera_id
        ''')
        cam_detections_map = {row['camera_id']: row['detections'] for row in cursor.fetchall()}
        
        by_camera = []
        seen_cids = set()
        
        if cameras_config:
            for cam in cameras_config:
                cid = cam.id if hasattr(cam, 'id') else cam.get('id')
                cname = cam.name if hasattr(cam, 'name') else cam.get('name', f"Cámara {cid}")
                seen_cids.add(cid)
                v_cnt = cam_violations_map.get(cid, 0)
                d_cnt = cam_detections_map.get(cid, 0)
                by_camera.append({
                    'camera_id': cid,
                    'camera_name': cname,
                    'violations': v_cnt,
                    'detections': d_cnt
                })
                
        for cid, v_cnt in cam_violations_map.items():
            if cid not in seen_cids:
                by_camera.append({
                    'camera_id': cid,
                    'camera_name': f"Cámara {cid}",
                    'violations': v_cnt,
                    'detections': cam_detections_map.get(cid, 0)
                })
        
        # Violaciones agrupadas por hora usando strftime('%H:00', datetime)
        cursor.execute('''
            SELECT strftime('%H:00', datetime) as hour, COUNT(*) as violations
            FROM violations
            WHERE datetime IS NOT NULL AND datetime != ''
            GROUP BY hour
            ORDER BY hour ASC
        ''')
        hour_rows = cursor.fetchall()
        by_hour = []
        for row in hour_rows:
            h = row['hour'] if row['hour'] is not None else "00:00"
            by_hour.append({
                'hour': h,
                'violations': row['violations']
            })
        
        return {
            'total_violations': total_violations,
            'total_detections': total_detections,
            'compliance_rate': compliance_rate,
            'by_camera': by_camera,
            'by_hour': by_hour
        }
    
    def get_violations_for_export(self, camera_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Obtiene todas las infracciones para exportación a CSV ordenadas por timestamp desc.
        
        Args:
            camera_id: Opcional, filtrar por ID de cámara
        
        Returns:
            List[dict]: Filas de infracciones con id, timestamp, datetime, camera_id,
                        confidence, helmet_confidence, crop_path, bbox
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if camera_id is not None:
            cursor.execute('''
                SELECT id, timestamp, datetime, camera_id, confidence, helmet_confidence, crop_path, bbox
                FROM violations
                WHERE camera_id = ?
                ORDER BY timestamp DESC
            ''', (camera_id,))
        else:
            cursor.execute('''
                SELECT id, timestamp, datetime, camera_id, confidence, helmet_confidence, crop_path, bbox
                FROM violations
                ORDER BY timestamp DESC
            ''')
        
        rows = cursor.fetchall()
        records = []
        for row in rows:
            rec = {
                'id': row['id'],
                'timestamp': row['timestamp'],
                'datetime': row['datetime'],
                'confidence': row['confidence'],
                'helmet_confidence': row['helmet_confidence']
            }
            try:
                rec['camera_id'] = row['camera_id']
            except (IndexError, KeyError):
                rec['camera_id'] = 0
                
            try:
                rec['crop_path'] = row['crop_path']
                rec['image_path'] = row['crop_path']
            except (IndexError, KeyError):
                rec['crop_path'] = None
                rec['image_path'] = None
                
            try:
                rec['bbox'] = row['bbox']
            except (IndexError, KeyError):
                rec['bbox'] = ''
                
            records.append(rec)
            
        return records

    def clear_all_data(self):
        """
        Limpia TODOS los datos de las tablas (detecciones e infracciones)
        Mantiene la estructura de las tablas intacta.
        """
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM detections')
            cursor.execute('DELETE FROM violations')
            conn.commit()
            print(f"[Database] Todos los datos han sido eliminados")
    
    def close(self):
        """Cierra la conexión a la base de datos"""
        if self.conn:
            self.conn.close()
            self.conn = None
