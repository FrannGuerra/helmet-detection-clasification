import threading
from pathlib import Path
from PIL import Image
from ultralytics import YOLO


class HelmetClassifier:
    """
    Clasificador de cascos usando YOLOv8m-cls.
    
    Recibe imágenes PIL (crops de riders) y devuelve (clase, confianza).
    Ultralytics maneja internamente el resize a imgsz=224, consistente
    con cómo fue entrenado el modelo (crop_fraction=1.0, scale=0.0).
    """

    IMGSZ = 64  # Tamaño de entrada del modelo (fijo, definido en entrenamiento)

    def __init__(self, model_path: str):
        self.lock = threading.Lock()
        self.model_path = Path(model_path)
        self.model = self._load_model()
        self._verify_classifier()

    def _load_model(self) -> YOLO:
        if not self.model_path.exists():
            raise FileNotFoundError(f"Modelo de clasificación no encontrado: {self.model_path}")
        return YOLO(str(self.model_path))

    def _verify_classifier(self) -> None:
        """Verifica que el modelo sea de clasificación (devuelve probs)."""
        dummy = Image.new('RGB', (self.IMGSZ, self.IMGSZ), (0, 0, 0))
        results = self.model(dummy, imgsz=self.IMGSZ, verbose=False)
        if not results or results[0].probs is None:
            raise RuntimeError(
                "El modelo no devuelve probabilidades. "
                "Asegurate de que sea un modelo YOLOv8-cls."
            )

    def classify(self, img: Image.Image) -> tuple[str, float]:
        """
        Clasifica un crop de rider.
        
        Args:
            img: Imagen PIL del crop (cualquier tamaño, YOLO hace resize).
        Returns:
            (clase_normalizada, confianza)
        """
        img = img.convert('RGB')
        with self.lock:
            results = self.model(img, imgsz=self.IMGSZ, verbose=False)
        if not results or results[0].probs is None:
            return 'desconocido', 0.0
        return self._extract_result(results[0])

    def classify_batch(self, images: list[Image.Image]) -> list[tuple[str, float]]:
        """
        Clasifica un lote de crops de riders.
        
        Args:
            images: Lista de imágenes PIL (cualquier tamaño).
        Returns:
            Lista de (clase_normalizada, confianza)
        """
        if not images:
            return []

        pil_images = [img.convert('RGB') for img in images]
        with self.lock:
            results = self.model(pil_images, imgsz=self.IMGSZ, verbose=False)

        return [
            self._extract_result(r) if r.probs is not None else ('desconocido', 0.0)
            for r in results
        ]

    def _extract_result(self, result) -> tuple[str, float]:
        """Extrae clase y confianza de un resultado de clasificación."""
        probs = result.probs
        top1_idx = int(probs.top1)
        top1_conf = float(probs.top1conf)
        class_name = self.model.names.get(top1_idx, 'desconocido')
        return self._normalize_class_name(class_name), top1_conf

    @staticmethod
    def _normalize_class_name(class_name: str) -> str:
        lower = class_name.lower()
        if 'con_casco' in lower or 'con casco' in lower:
            return 'con_casco'
        if 'sin_casco' in lower or 'sin casco' in lower:
            return 'sin_casco'
        return class_name