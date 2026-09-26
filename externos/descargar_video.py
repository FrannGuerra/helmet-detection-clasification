"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  DESCARGADOR DE VIDEO PARA DEMO                                              ║
║  Descarga un video de YouTube en 1080p/30fps listo para consumir con         ║
║  la app de detección de cascos (sin tocar nada del código de la app).        ║
╚══════════════════════════════════════════════════════════════════════════════╝

USO:
  # Video normal (termina solo):
  python descargar_video.py https://www.youtube.com/watch?v=XXXXXXXX --nombre demo

  # Stream en vivo — especificando minutos:
  python descargar_video.py https://www.youtube.com/watch?v=XXXXXXXX --nombre demo_vivo --duracion 10

  # Stream en vivo — especificando segundos:
  python descargar_video.py https://www.youtube.com/watch?v=XXXXXXXX --nombre demo_vivo --segundos 90

  # Stream en vivo — combinando (se suman):
  python descargar_video.py https://www.youtube.com/watch?v=XXXXXXXX --nombre demo_vivo --duracion 1 --segundos 30

LUEGO en config/config.yaml cambiar la línea source de la cámara a:
  source: "videos/nombre_del_video.mp4"
"""

import sys
import subprocess
import argparse
from pathlib import Path

# ── Configuración ──────────────────────────────────────────────────────────────
OUTPUT_DIR = Path("videos")
DEFAULT_FPS = 30
YTDLP_FORMAT = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]"
# ──────────────────────────────────────────────────────────────────────────────


def verificar_ytdlp():
    """Verifica que yt-dlp esté instalado (ya lo usa la app, así que debería estar)."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--version"],
            capture_output=True, text=True, timeout=5
        )
        print(f"  [OK] yt-dlp versión: {result.stdout.strip()}")
        return True
    except FileNotFoundError:
        print("  [ERROR] yt-dlp no está instalado.")
        print("          Instalar con: pip install yt-dlp")
        return False
    except Exception as e:
        print(f"  [ERROR] No se pudo verificar yt-dlp: {e}")
        return False


def verificar_ffmpeg():
    """Verifica que FFmpeg esté disponible (necesario para remuxing a 30fps)."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=5
        )
        version_line = result.stdout.splitlines()[0] if result.stdout else "desconocida"
        print(f"  [OK] FFmpeg: {version_line}")
        return True
    except FileNotFoundError:
        print("  [ERROR] FFmpeg no está instalado.")
        print("          Descargar de: https://ffmpeg.org/download.html")
        return False


def descargar_video(url: str, nombre_salida=None, duracion_segundos=None, es_en_vivo_infinito=False):
    """
    Descarga un video o stream en vivo y lo guarda en la carpeta videos/.

    Modos:
    1. Video Normal: yt-dlp estándar.
    2. Live con duración (--duracion): Usa ffmpeg para cortar exactamente en N segundos.
    3. Live Infinito (--live): Usa yt-dlp en modo live hasta pulsar Ctrl+C. (Soporta Twitch, m3u8, etc).
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    nombre_limpio = nombre_salida.replace(" ", "_") if nombre_salida else "video_demo"
    output_final = OUTPUT_DIR / f"{nombre_limpio}.mp4"

    def _fmt_duracion(seg):
        m, s = divmod(int(seg), 60)
        if m and s: return f"{m}m {s}s"
        elif m: return f"{m}m"
        else: return f"{s}s"

    print(f"\n  Descargando: {url}")
    print(f"  Destino:     {output_final.resolve()}")
    if duracion_segundos:
        print(f"  Duración:    {_fmt_duracion(duracion_segundos)} ({duracion_segundos}s) — stream en vivo")
    elif es_en_vivo_infinito:
        print(f"  Modo:        STREAM EN VIVO (Presiona Ctrl+C para detener y guardar)")
    print(f"  Formato:     1080p · H.264 · {DEFAULT_FPS}fps\n")

    # ── Modo STREAM EN VIVO INFINITO (HASTA CTRL+C) ────────────────────────────
    if es_en_vivo_infinito:
        cmd_live = [
            "yt-dlp", "-o", str(output_final),
            "--live-from-start", "--hls-use-mpegts",
            url
        ]
        try:
            print("  [!] Grabando en vivo... Presiona Ctrl+C para detener y guardar el archivo.")
            subprocess.run(cmd_live, check=True)
            print("\n  [OK] Descarga completada.")
        except KeyboardInterrupt:
            print("\n  [!] Grabación detenida por el usuario. El archivo parcial se guardó correctamente.")
        except Exception as e:
            print(f"  [ERROR] Fallo al grabar en vivo: {e}")
            return None
        return output_final if output_final.exists() else None

    # ── Modo STREAM EN VIVO CORTADO (CON FFmpeg) ───────────────────────────────
    if duracion_segundos:
        print("  [1/2] Extrayendo URL directa del stream con yt-dlp...")
        try:
            result = subprocess.run(
                [
                    "yt-dlp", "--no-playlist", "-g",
                    "-f", "bestvideo[height<=1080][ext=mp4]/bestvideo[height<=1080]/best[height<=1080]",
                    url
                ],
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace"
            )
            if result.returncode != 0 or not result.stdout.strip():
                print(f"  [ERROR] yt-dlp no pudo extraer la URL directa.")
                return None
            stream_url = result.stdout.strip().splitlines()[0]
            print("  [OK] URL extraída correctamente.")
        except Exception as e:
            print(f"  [ERROR] Fallo al extraer URL: {e}")
            return None

        print(f"  [2/2] Grabando {_fmt_duracion(duracion_segundos)} con FFmpeg...")
        cmd_ffmpeg = [
            "ffmpeg", "-y",
            "-i", stream_url,
            "-t", str(int(duracion_segundos)),  # Cortar exactamente en N segundos
            "-r", str(DEFAULT_FPS),              # Forzar 30 FPS constantes
            "-c:v", "libx264",                   # H.264, compatible con OpenCV y la app
            "-preset", "fast",                   # Velocidad de encoding equilibrada
            "-crf", "23",                        # Calidad visual
            "-an",                               # Sin audio
            str(output_final)
        ]
        try:
            proceso = subprocess.Popen(
                cmd_ffmpeg,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace"
            )
            for linea in proceso.stderr:
                linea = linea.rstrip()
                if "time=" in linea or "error" in linea.lower():
                    print(f"\r  {linea}", end="", flush=True)
            proceso.wait()
            print()  # Salto de línea

            if proceso.returncode != 0:
                print(f"\n  [ERROR] FFmpeg falló con código: {proceso.returncode}")
                return None
        except Exception as e:
            print(f"  [ERROR] Fallo al grabar con FFmpeg: {e}")
            return None

        return output_final if output_final.exists() else None

    # ── Modo VIDEO NORMAL ──────────────────────────────────────────────────────
    output_template = str(OUTPUT_DIR / f"{nombre_limpio}.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--format", YTDLP_FORMAT,
        "--merge-output-format", "mp4",
        "--recode-video", "mp4",
        "--postprocessor-args", f"ffmpeg:-r {DEFAULT_FPS} -vf fps={DEFAULT_FPS}",
        "--newline",
        "-o", output_template,
        url
    ]

    try:
        proceso = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace"
        )
        for linea in proceso.stdout:
            linea = linea.rstrip()
            if any(tag in linea for tag in ["[download]", "[ffmpeg]", "[Merger]", "[VideoConvertor]", "ERROR", "WARNING"]):
                print(f"  {linea}")
        proceso.wait()

        if proceso.returncode != 0:
            print(f"\n  [ERROR] yt-dlp finalizó con error.")
            return None

        return output_final if output_final.exists() else None

    except Exception as e:
        print(f"  [ERROR] Fallo inesperado: {e}")
        return None


def mostrar_instrucciones(ruta_video):
    """Muestra cómo configurar la app para usar el video descargado."""
    try:
        ruta_relativa = ruta_video.relative_to(Path.cwd())
    except ValueError:
        ruta_relativa = ruta_video

    ruta_yaml = str(ruta_relativa).replace("\\", "/")

    sep = "─" * 62
    print(f"\n╔{sep}╗")
    print(f"║  VIDEO LISTO PARA USAR EN LA APP                           ║")
    print(f"╚{sep}╝")
    print(f"\n  Archivo: {ruta_video.resolve()}")
    print(f"  Tamaño:  {ruta_video.stat().st_size / (1024**2):.1f} MB\n")
    print(f"  Para usarlo en la app, editar config/config.yaml:")
    print(f"  ─────────────────────────────────────────────────────")
    print(f"  cameras:")
    print(f"    - id: 1")
    print(f"      name: \"Demo Video\"")
    print(f"      source: \"{ruta_yaml}\"")
    print(f"      lat: 0.0")
    print(f"      lng: 0.0")
    print(f"  ─────────────────────────────────────────────────────")
    print(f"\n  Cuando el video termine, la app mostrará y se detendrá sola.\n")


def main():
    parser = argparse.ArgumentParser(
        description="Descarga un video de YouTube listo para usar con la app de detección de cascos."
    )
    parser.add_argument("url", help="URL del video de YouTube a descargar")
    parser.add_argument(
        "--nombre", "-n",
        default=None,
        help="Nombre del archivo de salida (sin extensión). Ej: --nombre demo_tailandia"
    )
    parser.add_argument(
        "--duracion", "-d",
        type=int,
        default=None,
        help="(Para streams en vivo) Cuántos MINUTOS grabar. Se puede combinar con --segundos. Ej: --duracion 10"
    )
    parser.add_argument(
        "--segundos", "-s",
        type=int,
        default=None,
        help="(Para streams en vivo) Cuántos SEGUNDOS grabar. Se puede combinar con --duracion. Ej: --segundos 90"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="(Para streams en vivo infinitos) Descarga hasta que presiones Ctrl+C. Soporta YouTube, Twitch, m3u8, etc."
    )
    args = parser.parse_args()

    # Calcular duración total en segundos (minutos + segundos extra)
    duracion_total_seg = None
    if args.duracion or args.segundos:
        duracion_total_seg = (args.duracion or 0) * 60 + (args.segundos or 0)
        if duracion_total_seg <= 0:
            print("  [ERROR] La duración debe ser mayor a 0 segundos.")
            sys.exit(1)

    sep = "─" * 62
    print(f"\n╔{sep}╗")
    print(f"║  DESCARGADOR DE VIDEO PARA DEMO DE CASCOS                   ║")
    print(f"╚{sep}╝\n")

    print("  Verificando dependencias...")
    if not verificar_ytdlp():
        sys.exit(1)
    if not verificar_ffmpeg():
        sys.exit(1)

    ruta = descargar_video(args.url, args.nombre, duracion_total_seg, args.live)

    if ruta and ruta.exists():
        mostrar_instrucciones(ruta)
    else:
        print("\n  [ERROR] La descarga falló. Verifica la URL e intenta de nuevo.")
        sys.exit(1)



if __name__ == "__main__":
    main()
