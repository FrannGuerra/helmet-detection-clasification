# 🛠️ Guía Completa de Instalación

Guía paso a paso para instalar y configurar el **Sistema de Detección de Cascos en Motociclistas** en cualquier PC.

---

## 📋 Requisitos Previos

| Requisito | Mínimo | Recomendado |
|-----------|--------|-------------|
| **Python** | 3.9 | 3.10 - 3.11 |
| **RAM** | 8 GB | 16 GB |
| **Espacio en disco** | 2 GB | 5 GB |
| **GPU (opcional)** | — | NVIDIA con CUDA 11.8+ |
| **Sistema Operativo** | Windows 10 / Ubuntu 20.04 | Windows 11 / Ubuntu 22.04 |
| **Conexión a Internet** | Sí (para streams HLS y descarga de modelos) | — |

---

## 🪟 Instalación en Windows

### Paso 1: Instalar Python

1. Descargar Python 3.10 o 3.11 desde [python.org](https://www.python.org/downloads/)
2. **IMPORTANTE**: Durante la instalación, marcar la casilla **"Add Python to PATH"**
3. Verificar la instalación:
   ```powershell
   python --version
   pip --version
   ```

### Paso 2: Instalar FFmpeg

FFmpeg es necesario para procesar streams de video HLS.

1. Descargar FFmpeg desde: [https://www.gyan.dev/ffmpeg/builds/](https://www.gyan.dev/ffmpeg/builds/)
   - Elegir el archivo **"ffmpeg-release-essentials.zip"**
2. Extraer el ZIP en una ubicación permanente, por ejemplo:
   ```
   C:\ffmpeg\
   ```
3. Agregar FFmpeg al PATH del sistema:
   - Abrí **"Editar las variables de entorno del sistema"** (buscar en el menú Inicio)
   - Click en **"Variables de entorno..."**
   - En **"Variables del sistema"**, seleccionar `Path` → **Editar**
   - Click en **Nuevo** y agregar:
     ```
     C:\ffmpeg\bin
     ```
   - Aceptar todos los diálogos
4. **Reiniciar la terminal** y verificar:
   ```powershell
   ffmpeg -version
   ```

### Paso 3: Clonar o copiar el proyecto

```powershell
# Si usás Git:
git clone <URL_DEL_REPOSITORIO>
cd "prueba antigravity"

# O simplemente copiar la carpeta del proyecto a tu escritorio
```

### Paso 4: Crear el entorno virtual (venv)

```powershell
# Navegar a la carpeta del proyecto
cd "C:\ruta\al\proyecto\prueba antigravity"

# Crear el entorno virtual
python -m venv venv

# Activar el entorno virtual
.\venv\Scripts\Activate.ps1
```

> [!NOTE]
> Si te aparece un error de **"Execution Policy"** al activar el venv en PowerShell, ejecutá primero:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

> [!TIP]
> Sabés que el venv está activo cuando ves `(venv)` al inicio del prompt de la terminal.

### Paso 5: Instalar dependencias

```powershell
# Asegurar que pip esté actualizado
python -m pip install --upgrade pip

# Instalar todas las dependencias
pip install -r requirements.txt
```

> [!IMPORTANT]
> **Si tenés GPU NVIDIA y querés acelerar la detección:**
> ```powershell
> # Instalar PyTorch con soporte CUDA (en vez de la versión CPU)
> pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
> # Luego instalar el resto normalmente
> pip install -r requirements.txt
> ```
> Verificar CUDA:
> ```powershell
> python -c "import torch; print('CUDA disponible:', torch.cuda.is_available())"
> ```

### Paso 6: Verificar archivos del modelo

Asegurate de que estos archivos estén en la raíz del proyecto:

| Archivo | Descripción | ¿Se descarga automáticamente? |
|---------|-------------|-------------------------------|
| `best.pt` | Modelo de clasificación de cascos (custom) | ❌ No — debe estar incluido |
| `yolov8x.pt` | Modelo YOLOv8 de detección general | ✅ Sí — se descarga solo la primera vez |

```powershell
# Verificar que best.pt existe
dir best.pt
```

### Paso 7: Ejecutar la aplicación

```powershell
# Con el venv activo:
python app/app.py
```

Abrir el navegador en: **http://localhost:5000**

---

## 🐧 Instalación en Linux / WSL (Windows Subsystem for Linux)

### Paso 1: Instalar dependencias del sistema

```bash
# Actualizar paquetes
sudo apt update && sudo apt upgrade -y

# Instalar Python y herramientas esenciales
sudo apt install -y python3 python3-pip python3-venv python3-dev

# Instalar FFmpeg
sudo apt install -y ffmpeg

# Instalar dependencias de OpenCV (necesarias en Linux)
sudo apt install -y libgl1 libglib2.0-0 libsm6 libxrender1 libxext6

# Verificar instalaciones
python3 --version
ffmpeg -version
```

### Paso 2 (solo WSL): Habilitar WSL

Si estás en Windows y querés usar WSL:

1. Abrir PowerShell como **Administrador**:
   ```powershell
   wsl --install
   ```
2. Reiniciar la PC
3. Se abrirá Ubuntu — crear un usuario y contraseña
4. Acceder al proyecto Windows desde WSL:
   ```bash
   cd /mnt/c/Users/TU_USUARIO/OneDrive/Desktop/"prueba antigravity"
   ```

### Paso 3: Crear el entorno virtual (venv)

```bash
# Navegar al proyecto
cd /ruta/al/proyecto/"prueba antigravity"

# Crear el entorno virtual
python3 -m venv venv_linux

# Activar el entorno virtual
source venv_linux/bin/activate
```

> [!TIP]
> Sabés que el venv está activo cuando ves `(venv_linux)` al inicio del prompt.

### Paso 4: Instalar dependencias

```bash
# Actualizar pip
pip install --upgrade pip

# Instalar dependencias
pip install -r requirements.txt
```

> [!IMPORTANT]
> **Para GPU NVIDIA en Linux:**
> ```bash
> # Instalar drivers NVIDIA + CUDA Toolkit primero
> # Ver: https://developer.nvidia.com/cuda-downloads
>
> # Luego instalar PyTorch con CUDA
> pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
> pip install -r requirements.txt
> ```

### Paso 5: Instalar opencv-python-headless (recomendado en Linux/WSL)

En Linux sin interfaz gráfica, usar la versión headless de OpenCV:

```bash
pip uninstall opencv-python -y
pip install opencv-python-headless>=4.10.0
```

### Paso 6: Ejecutar la aplicación

```bash
# Con el venv activo:
python3 app/app.py
```

Abrir el navegador en: **http://localhost:5000**

> [!NOTE]
> **WSL**: El navegador debe abrirse **desde Windows**, no desde WSL. La dirección `localhost:5000` funciona automáticamente gracias al port forwarding de WSL2.

---

## 🔑 Verificación rápida post-instalación

Ejecuta estos comandos para verificar que todo está correctamente instalado:

```bash
# 1. Verificar Python
python --version
# Esperado: Python 3.9+ 

# 2. Verificar FFmpeg
ffmpeg -version
# Esperado: ffmpeg version X.X.X

# 3. Verificar que las dependencias se importan correctamente
python -c "
import flask; print(f'Flask: {flask.__version__}')
import cv2; print(f'OpenCV: {cv2.__version__}')
import torch; print(f'PyTorch: {torch.__version__}')
import ultralytics; print(f'Ultralytics: {ultralytics.__version__}')
print('CUDA disponible:', torch.cuda.is_available())
print('¡Todas las dependencias OK!')
"

# 4. Verificar que el modelo existe
# Windows:
dir best.pt
# Linux:
ls -la best.pt
```

---

## ⚠️ Problemas Comunes y Soluciones

### Error: `ffmpeg not found`
- **Causa**: FFmpeg no está instalado o no está en el PATH.
- **Solución**: Seguir los pasos de instalación de FFmpeg arriba. **Reiniciar la terminal** después de modificar el PATH.

### Error: `ModuleNotFoundError: No module named 'cv2'`
- **Causa**: OpenCV no se instaló correctamente.
- **Solución**:
  ```bash
  pip install opencv-python>=4.10.0
  # O en Linux sin GUI:
  pip install opencv-python-headless>=4.10.0
  ```

### Error: `RuntimeError: CUDA out of memory`
- **Causa**: La GPU no tiene suficiente VRAM.
- **Solución**: El sistema funciona con CPU automáticamente. Si hay problemas, forzar CPU:
  ```bash
  CUDA_VISIBLE_DEVICES="" python app/app.py
  ```

### Error: `Execution Policy` en PowerShell
- **Solución**:
  ```powershell
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
  ```

### Error: `best.pt not found`
- **Causa**: El modelo de clasificación no está en la raíz del proyecto.
- **Solución**: Copiar `best.pt` a la raíz del proyecto o actualizar la ruta en `config/config.yaml`.

### Error: Stream HLS no conecta
- **Causa**: La URL del stream no está disponible o está bloqueada.
- **Solución**: Verificar la URL en un navegador. La app intentará reconectarse automáticamente.

### Puerto 5000 en uso
- **Solución**: Cambiar el puerto en `config/config.yaml`:
  ```yaml
  server:
    port: 8080  # Usar otro puerto
  ```

---

## 🔄 Desactivar entorno virtual

```bash
# Cuando termines de usar la aplicación:
deactivate
```

---

## 📦 Resumen de Comandos Rápidos

### Windows (PowerShell)
```powershell
cd "C:\ruta\al\proyecto\prueba antigravity"
.\venv\Scripts\Activate.ps1
python app/app.py
# Abrir http://localhost:5000
```

### Linux / WSL (Bash)
```bash
cd /ruta/al/proyecto/"prueba antigravity"
source venv_linux/bin/activate
python3 app/app.py
# Abrir http://localhost:5000
```
