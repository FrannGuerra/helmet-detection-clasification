"""
╔══════════════════════════════════════════════════════════════════════════════╗
║    PREPARADOR ÚNICO DE DATASETS (Detector y Clasificador)                    ║
║    Convierte el export de 3 clases de Roboflow en los 2 datasets finales     ║
╚══════════════════════════════════════════════════════════════════════════════╝

USO:
  1. Exportá tu dataset de Roboflow en formato YOLOv8.
  2. Descomprimí el .zip dentro de la carpeta: training/datasets/roboflow_exports/v1/ (o la versión que uses)
  3. Ejecutá este script:
     python training/preparar_datasets.py --dataset v1
"""

import sys
import shutil
import random
from pathlib import Path
import yaml
import cv2
import argparse

# Encoding UTF-8 para consola de Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Configurar parser de argumentos
parser = argparse.ArgumentParser(description='Preparador de datasets dinámico')
parser.add_argument('--dataset', type=str, default='v1', help='Versión del dataset (ej: v1, v2, v3)')
# Parsear argumentos conocidos para que no falle si es llamado por otro script
args, unknown = parser.parse_known_args()
DATASET_VER = args.dataset

INPUT_DIR = Path(f'training/datasets/roboflow_exports/{DATASET_VER}')
DETECTOR_DIR = Path(f'training/datasets/detector/{DATASET_VER}')
CLASSIFIER_DIR = Path(f'training/datasets/clasificador/{DATASET_VER}')

def get_all_data(input_dir: Path):
    """Recolecta todas las imágenes y labels sin importar en qué split de Roboflow estén."""
    all_data = []
    for split in ['train', 'valid', 'test']:
        img_dir = input_dir / split / 'images'
        lbl_dir = input_dir / split / 'labels'
        
        if not img_dir.exists() or not lbl_dir.exists():
            continue
            
        for img_path in img_dir.glob('*'):
            if img_path.suffix.lower() not in ['.jpg', '.jpeg', '.png']:
                continue
                
            txt_path = lbl_dir / f"{img_path.stem}.txt"
            if txt_path.exists():
                all_data.append((img_path, txt_path))
    return all_data

def split_70_20_10(data_list):
    """Divide una lista aleatoriamente en 70% Train, 20% Val, 10% Test."""
    random.shuffle(data_list)
    n = len(data_list)
    t_idx = int(n * 0.7)
    v_idx = t_idx + int(n * 0.2)
    return data_list[:t_idx], data_list[t_idx:v_idx], data_list[v_idx:]

def procesar_dataset_detector(all_data, output_dir: Path, map_clases: dict):
    print(f"\n[1/2] Preparando dataset para el DETECTOR en: {output_dir}")
    if output_dir.exists():
        shutil.rmtree(output_dir)
        
    # División aleatoria 70/20/10
    train_data, val_data, test_data = split_70_20_10(all_data)
    
    splits = [('train', train_data), ('valid', val_data), ('test', test_data)]
    
    labels_modificados = 0
    for split_name, data_list in splits:
        img_out = output_dir / split_name / 'images'
        lbl_out = output_dir / split_name / 'labels'
        img_out.mkdir(parents=True, exist_ok=True)
        lbl_out.mkdir(parents=True, exist_ok=True)
        
        for img_path, txt_path in data_list:
            # Copiar imagen
            shutil.copy(str(img_path), str(img_out / img_path.name))
            
            # Leer y reescribir label
            with open(txt_path, 'r', encoding='utf-8') as f:
                lineas = f.readlines()
                
            nuevas_lineas = []
            for linea in lineas:
                partes = linea.strip().split()
                if not partes:
                    continue
                class_id_original = int(partes[0])
                
                # Mapear el ID para fusionar cabezas y renombrar motos
                if class_id_original in map_clases:
                    partes[0] = str(map_clases[class_id_original])
                    nuevas_lineas.append(" ".join(partes))
                    labels_modificados += 1
                    
            with open(lbl_out / txt_path.name, 'w', encoding='utf-8') as f:
                f.write("\n".join(nuevas_lineas) + "\n")
                
    # Escribir data.yaml (paths relativos estándar para YOLO)
    yaml_path = output_dir / 'data.yaml'
    data_yaml_content = {
        'train': 'train/images',
        'val': 'valid/images',
        'test': 'test/images',
        'nc': 2,
        'names': ['moto', 'cabeza_torso']
    }
    with open(yaml_path, 'w', encoding='utf-8') as f:
        yaml.dump(data_yaml_content, f, sort_keys=False)
        
    print(f"  ✓ Split aleatorio completado: {len(train_data)} train | {len(val_data)} valid | {len(test_data)} test")
    print(f"  ✓ Labels procesados y {labels_modificados} cabezas unificadas a cabeza_torso (ID 1).")
    print(f"  ✓ data.yaml generado correctamente.")

def procesar_dataset_clasificador(all_data, output_dir: Path, id_con_casco: int, id_sin_casco: int):
    print(f"\n[2/2] Preparando dataset para el CLASIFICADOR en: {output_dir}")
    if output_dir.exists():
        shutil.rmtree(output_dir)
        
    crops_con = []
    crops_sin = []
    
    # 1. Recolectar todas las tareas de recorte basadas en los labels originales
    for img_path, txt_path in all_data:
        with open(txt_path, 'r', encoding='utf-8') as f:
            for linea in f:
                partes = linea.strip().split()
                if not partes:
                    continue
                class_id = int(partes[0])
                if class_id == id_con_casco:
                    crops_con.append((img_path, partes))
                elif class_id == id_sin_casco:
                    crops_sin.append((img_path, partes))

    # 2. División estratificada estricta (70/20/10 individual para CADA clase)
    train_con, val_con, test_con = split_70_20_10(crops_con)
    train_sin, val_sin, test_sin = split_70_20_10(crops_sin)
    
    splits = [
        ('train', train_con, train_sin),
        ('val', val_con, val_sin),
        ('test', test_con, test_sin)
    ]
    
    # 3. Procesar y guardar imágenes
    def guardar_recortes(lista_crops, split_name, class_name):
        out_dir = output_dir / split_name / class_name
        out_dir.mkdir(parents=True, exist_ok=True)
        
        for i, (img_path, partes) in enumerate(lista_crops):
            img = cv2.imread(str(img_path))
            if img is None: continue
            h, w = img.shape[:2]
            
            _, x_center, y_center, bbox_w, bbox_h = map(float, partes)
            
            x1 = int((x_center - bbox_w / 2) * w)
            y1 = int((y_center - bbox_h / 2) * h)
            x2 = int((x_center + bbox_w / 2) * w)
            y2 = int((y_center + bbox_h / 2) * h)
            
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            
            if (x2 - x1) < 10 or (y2 - y1) < 10:
                continue
                
            crop = img[y1:y2, x1:x2]
            out_path = out_dir / f"{img_path.stem}_{i}.jpg"
            cv2.imwrite(str(out_path), crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            
    # Guardar en disco procesando los cortes
    for split_name, c_con, c_sin in splits:
        guardar_recortes(c_con, split_name, 'con_casco')
        guardar_recortes(c_sin, split_name, 'sin_casco')
        
    print(f"  ✓ Estratificación 'con_casco' : {len(train_con)} train | {len(val_con)} val | {len(test_con)} test")
    print(f"  ✓ Estratificación 'sin_casco' : {len(train_sin)} train | {len(val_sin)} val | {len(test_sin)} test")
    print(f"  ✓ Recortes guardados con éxito con la nueva división estratificada.")

def main():
    print("═" * 70)
    print("  PREPARADOR AUTOMÁTICO DE DATASETS (SINGLE-SOURCE DINÁMICO)")
    print("═" * 70)
    
    if not INPUT_DIR.exists():
        print(f"\n[ERROR] No se encontró la carpeta: {INPUT_DIR}")
        print("  Pasos a seguir:")
        print("  1. Exportá el dataset de 3 clases desde Roboflow (formato YOLOv8).")
        print(f"  2. Descomprimí el .zip adentro de la carpeta '{INPUT_DIR}'.")
        print(f"  3. Volvé a correr este script usando: python training/preparar_datasets.py --dataset {DATASET_VER}")
        sys.exit(1)
        
    data_yaml = INPUT_DIR / 'data.yaml'
    if not data_yaml.exists():
        print(f"\n[ERROR] No se encontró 'data.yaml' en {INPUT_DIR}")
        print("  Asegurate de haber descomprimido el ZIP de Roboflow correctamente.")
        sys.exit(1)
        
    # Leer dinámicamente los IDs desde Roboflow
    with open(data_yaml, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
        
    nombres_originales = data.get('names', [])
    print(f"\n[INFO] Clases detectadas en Roboflow: {nombres_originales}")
    
    id_moto = -1
    id_con_casco = -1
    id_sin_casco = -1
    
    # Buscar por coincidencia de texto (ignorando mayúsculas)
    for i, nombre in enumerate(nombres_originales):
        n = nombre.lower()
        if 'moto' in n:
            id_moto = i
        elif 'con' in n and 'casco' in n:
            id_con_casco = i
        elif 'sin' in n and 'casco' in n:
            id_sin_casco = i
            
    if id_moto == -1 or id_con_casco == -1 or id_sin_casco == -1:
        print("\n[ERROR] No se encontraron las 3 clases necesarias (moto, cabeza_con_casco, cabeza_sin_casco).")
        print(f"  Clases actuales: {nombres_originales}")
        sys.exit(1)
        
    print(f"  [INFO] IDs asignados dinámicamente: moto={id_moto}, con_casco={id_con_casco}, sin_casco={id_sin_casco}")
        
    # Mapa de conversión: original -> nuevo ID del detector (0=moto, 1=cabeza_torso)
    map_clases = {
        id_moto: 0,
        id_con_casco: 1,
        id_sin_casco: 1
    }
        
    # 1. Lectura Unificada (Pool completo de imágenes)
    all_data = get_all_data(INPUT_DIR)
    if not all_data:
        print(f"\n[ERROR] No se encontraron imágenes en {INPUT_DIR}.")
        sys.exit(1)
        
    print(f"\n[INFO] Total de imágenes recolectadas en el lote general: {len(all_data)}")
        
    # 2. Ejecutar procesamiento y split
    procesar_dataset_detector(all_data, DETECTOR_DIR, map_clases)
    procesar_dataset_clasificador(all_data, CLASSIFIER_DIR, id_con_casco, id_sin_casco)
    
    print("\n═" * 70)
    print("  ¡TODO LISTO! 🎉")
    print("═" * 70)
    print("  1. Datasets divididos y balanceados exitosamente (70/20/10).")
    print("  2. Ya puedes subir los ZIPs a Kaggle o correr tus entrenamientos.")
    print("\n")


if __name__ == "__main__":
    main()
