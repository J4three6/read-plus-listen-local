# Read & Listen Sync Engine 3

## Español

Ejecuta `iniciar.bat`, carga un EPUB y su audio, elige CPU o una GPU disponible y pulsa **Sincronizar**. Puedes cambiar entre español e inglés durante el proceso. **Mostrar consola** abre el registro dentro de la ventana.

El motor procesa el libro completo con Whisper base y detección automática del idioma del audio. El idioma de la interfaz es independiente. Junto al EPUB guarda `*.sync-v2.json`, compatible con Studio. Si ya existe un archivo con ese nombre, renómbralo antes de iniciar otra ejecución.

Se requieren FFmpeg y ffprobe en el PATH. El lanzador usa el entorno virtual de esta carpeta. Ejecuta `instalar.bat` para instalar el entorno local. Las GPU disponibles son las NVIDIA visibles para CUDA y CTranslate2.

## English

Run `iniciar.bat`, select an EPUB and its audio, select the CPU or an available GPU, and click **Synchronize**. You can switch between English and Spanish while processing. **Show console** opens the log inside the window.

The engine processes the entire book with Whisper base and automatic speech language detection. The interface language is independent. It saves a Studio-compatible `*.sync-v2.json` next to the EPUB. Rename any existing export with that name before running again.

FFmpeg and ffprobe must be on PATH. The launcher uses the virtual environment in this folder. Run `instalar.bat` to install a local environment. GPU options are the NVIDIA devices visible to CUDA and CTranslate2.
