# The Order: 1886 para PC — runtime experimental de compatibilidad con PS4

<p align="center"><img src="launcher/order1886/logo-horizontal.png" width="720" alt="Logotipo oficial de The Order: 1886"></p>

[English](README.md) · [Português (Brasil)](README.pt-BR.md) · **Español**

Proyecto comunitario para ejecutar el binario original de **The Order: 1886**, edición PS4 **CUSA00076**, mediante un launcher nativo de Windows y un runtime Vulkan. Reutiliza infraestructura de carga PS4 y trabajo de gráficos/APIs de [shadPS4](https://github.com/shadps4-emu/shadPS4).

**En desarrollo — 18 de octubre de 2026.** Se renderizan cinemáticas y se ha recorrido una ruta de calle, pero el rendimiento sigue siendo bajo. La progresión, los guardados por checkpoint, la estabilidad y 4K/60 todavía no están aceptados. La prueba del Capítulo 2 con copias de guardados llegó al timeout sin la aserción de 8.029 capas; quedan errores SRT y la issue #5 sigue abierta.

![Launcher de The Order: 1886 para Windows con navegación lateral y barra de inicio permanente](docs/images/order1886-home-20261018.png)

*Captura real del launcher actual del 18 de octubre, 1240 × 800, con configuración aislada. No es gameplay; 30 FPS es la opción seleccionada.*

## Demostración en vídeo

[![Mira The Order: 1886 ejecutándose en PC](https://i.ytimg.com/vi/wpNkwih0cxI/hqdefault.jpg)](https://youtu.be/wpNkwih0cxI)

[**Mira la demostración en YouTube**](https://youtu.be/wpNkwih0cxI) — grabación del proyecto ejecutándose en PC, publicada por **Julio Cacko**. Haz clic en la miniatura para verla.

## Descargar

**Descarga publicada: preview.3, del 17 de octubre.** Las novedades del 18 de octubre describen el código actual de `main`; no representan una nueva release publicada. Compila desde el código fuente para utilizarlas.

**[Descargar el ZIP del launcher para Windows](https://github.com/JulioCacko/The-Order-1886_pc/releases/download/v0.1.0-preview.3/order1886-windows.zip)** · [Notas de la versión](https://github.com/JulioCacko/The-Order-1886_pc/releases/tag/v0.1.0-preview.3) · [Guía en inglés y portugués](https://github.com/JulioCacko/The-Order-1886_pc/releases/download/v0.1.0-preview.3/QUICKSTART.txt)

Extrae el ZIP completo y lee **QUICKSTART.txt**, incluido en el paquete. No requiere Python, MSYS2 ni compilador. Descarga `order1886-windows.zip`; los archivos “Source code” son para desarrolladores. El juego no está incluido: usa tu propio dump CUSA00076. Esta versión preliminar conserva las limitaciones de compatibilidad indicadas arriba.

## Novedades en el código fuente — 18 de octubre

- Mouse look mediante el stick, sensibilidad e inversión Y; inicio directo con **Play The Order 1886.exe**, acceso directo y **Game → Add to Steam** (cierra Steam primero).
- Copias de seguridad con orden numérico, mods `_data` reversibles con orden/conflictos, limpieza segura de caché y 13 idiomas de interfaz con fallback inglés. La validación visual de árabe/CJK sigue pendiente.
- Correcciones de shaders NaN/atomics, copia de claves de pipelines, memoria y mutex; aceptación de dumps ELF x86-64 validados.
- **321 pruebas Python sin omisiones, 41 checks nativos, tres módulos SPIR-V validados y 15 checks portátiles aprobados.** [Evidencia](docs/verification/2026-10-18-donor-060.md) · [Estado de issues](docs/order1886-issue-status.md).

![Utilidades actuales: acceso directo, Steam y guardados](docs/images/order1886-game-20261018.png)

En el juego, **Esc** libera el cursor y **F6** alterna la captura. Configura el ratón en **Game → Controls** y guarda. Siguen pendientes la reasignación, cámara directa 1:1, selección independiente de texto/voces, logros en vivo y actualización automática. [Guía de entrada e inicio directo](docs/order1886-input.md).

## El launcher

Estructura adaptada de [mateussmeneses/theorder1886-port](https://github.com/mateussmeneses/theorder1886-port), conservando nuestro backend y los guardados de CUSA00076. La presentación del README sigue la organización de [HayatoG/iss_pc](https://github.com/HayatoG/iss_pc).

| Página | Función |
| --- | --- |
| Home | Carpeta del juego, opciones rápidas y Play/Stop |
| Graphics | Pantalla, relación de aspecto, FSR 1/Linear y VSync |
| Performance | 30 FPS, 60 FPS experimental y overlay F9 |
| Game | Archivos, accesos directos/Steam, guardados, mods de assets y ratón |
| Advanced | Idioma del launcher, runtime, registros, caché y releases manuales |

Usa **Save settings** para guardar las opciones. Iniciar desde una página de opciones también guarda los valores antes de abrir el juego. Restaurar requiere confirmación y crea una copia del guardado reemplazado; se bloquea durante una sesión. El launcher anterior sigue disponible con `python launcher/order1886_launcher.py --classic`. Los mods de assets están disponibles; los parches ejecutables externos, funciones temporales y actualización automática siguen pendientes; consulta el [análisis de reutilización](docs/order1886-reference-reuse.md).

## Iniciar

Usa tu propia copia extraída de CUSA00076 con `eboot.bin`, `sce_sys` y `sce_module`. No se distribuyen ejecutables, dumps ni partidas guardadas del jugador. Los originales se conservan; las imágenes preparadas, configuración, cachés, registros, guardados y copias de seguridad se almacenan aparte.

1. Extrae el paquete portátil completo en una carpeta con permisos de escritura.
2. Abre **The Order 1886.exe** y selecciona **Game folder** en la barra inferior.
3. Empieza con **30 FPS** y elige el modo de pantalla y FSR 1 o Linear.
4. Usa **Play**, **Advanced → View session log** y **Stop session** para iniciar, revisar o detener la sesión.

Desde el código fuente, ejecuta `Launch The Order 1886.cmd` o `python launcher/order1886_launcher.py` después de seguir las [instrucciones de compilación para Windows](docs/order1886-build.md). El paquete no requiere Python ni MSYS2. No existe un paquete Linux verificado para este objetivo específico.

## Estado y rendimiento

El launcher ofrece Ventana/Sin bordes/Pantalla completa, VSync y overlay de rendimiento (F9). **60 FPS es opcional y experimental**: falta verificar contenido sensible al tiempo, incluidos los capítulos 6 y 9. El objetivo es salida 3840 × 2160 con reescalado permitido y 60 FPS sostenidos durante gameplay; aún no se ha alcanzado.

Consulta el [informe completo del estado actual, en inglés](docs/STATUS.md), la [evidencia del runtime](docs/order1886-runtime-status.md) y el [plan 4K/60](docs/order1886-4k60-verification.md). Un bloqueo anterior del PC requirió reinicio manual; la causa sigue siendo desconocida. Las pruebas de CPU y del launcher no demuestran estabilidad ni jugabilidad.

## Problemas y licencia

Abre **Advanced → Open log folder**. Al [informar de un problema](https://github.com/JulioCacko/The-Order-1886_pc/issues), incluye los registros y `last-run.json` correspondientes de `user/order1886/logs`, SHA256 del runtime, metadatos del juego y GPU/controlador. Elimina datos privados; no adjuntes archivos del juego ni partidas guardadas.

[GPL-2.0-or-later](LICENSE). Infraestructura reutilizada de [FelipePrado0/gow3_pc](https://github.com/FelipePrado0/gow3_pc) y [shadPS4](https://github.com/shadps4-emu/shadPS4), conservando atribución y licencias. The Order utiliza otro motor; los parches y el rendimiento de otro título no demuestran compatibilidad. Sin afiliación ni respaldo de Ready at Dawn o Sony.
