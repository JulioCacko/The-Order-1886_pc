<p align="center"><img src="docs/images/v0.2.5/hero.jpg" width="100%" alt="The Order: 1886 ejecutándose en PC en 4K nativo: Galahad en un tejado de Londres en el Capítulo I"></p>

# The Order: 1886 para PC — runtime experimental de compatibilidad con PS4

[English](README.md) · [Português (Brasil)](README.pt-BR.md) · **Español**

Proyecto comunitario que ejecuta el binario x86-64 original de **The Order: 1886** en PC. Las interfaces de sistema de PS4 se reimplementan y un [núcleo de vídeo derivado de shadPS4](https://github.com/shadps4-emu/shadPS4) traduce los comandos de GPU y los shaders a Vulkan. El objetivo es la actualización 1.02 en cualquier edición (**CUSA00076**, probada; CUSA00035, CUSA00070, CUSA00100, CUSA00670 y CUSA00785, experimentales), en Windows y Linux x86-64.

> **Versión preliminar de desarrollo.** Desde una partida guardada del jugador, el patio nocturno funciona a unos 53 FPS en una RTX 3070 (modo 60 FPS) y el combate en el vestíbulo del hotel promedia 38 FPS con caídas. Novedad de la v0.2.5: el juego puede renderizar de forma nativa hasta 4K, sin escalador, a 30 FPS en la misma GPU. La progresión completa, la estabilidad en sesiones largas, el tiempo de los QTE de los capítulos 6 y 9 y 4K/60 sostenido todavía no están aceptados.

> **No se incluye ningún archivo del juego.** Necesitas tu propia copia extraída. Proyecto comunitario no oficial.

## 4K nativo, sin escalador

Novedad de la v0.2.5. En Graphics → **Render resolution**, el propio juego dibuja cada pasada del tamaño de la pantalla al tamaño elegido; con 3840 de ancho son 3840×1600 (o 3840×2160 con encuadre 16:9), presentados 1:1. RTX 3070, modo 30 FPS.

<table>
  <tr>
    <td colspan="2"><img src="docs/images/v0.2.5/native-4k-rooftop-night.jpg" alt="3840x1600 nativo: Galahad en un tejado de noche junto a una grúa, capturado del paquete v0.2.5"></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/images/v0.2.5/native-4k-even-watchful.jpg" alt="Capítulo I, Even Watchful: el horizonte de Londres desde un tejado, renderizado a 3840x1600"></td>
    <td width="50%"><img src="docs/images/v0.2.5/native-4k-council.jpg" alt="Capítulo II: la escena del Consejo, renderizada a 3840x1600"></td>
  </tr>
  <tr>
    <td colspan="2"><img src="docs/images/fixes/native-4k-ch1-even-watchful-compare.jpg" alt="Detalle: la escena original de 1920x800 ampliada 2x junto a la escena nativa de 3840x1600 a 1:1"></td>
  </tr>
</table>

La imagen superior es la escena completa a 3840×1600, capturada del paquete de Windows v0.2.5 en una ventana sin bordes en una pantalla de 3840×2160. Las dos del medio se renderizaron a 3840×1600 y se capturaron desde una ventana de 1920×1080. La comparación inferior es un recorte 1:1. Medido a 3840×1600: 30 FPS en la calle y en el tejado del Capítulo I, con caídas a 27 FPS en la escena del Consejo del Capítulo II. Los mapas de sombras y el MSAA conservan sus tamaños originales, y por ahora solo se admite la actualización 1.02. [Evidencia](docs/verification/2026-10-29-native-resolution.md).

## Jugabilidad en PC

Capturado del paquete de Windows de la preview 9 en una RTX 3070 a 1920×1080, modo 60 FPS, recortado a la escena de 1920×800 que renderiza el juego.

<table>
  <tr>
    <td width="50%"><img src="docs/images/preview9/gameplay-lobby.jpg" alt="Galahad a cubierto en el vestíbulo del hotel"></td>
    <td width="50%"><img src="docs/images/preview9/gameplay-reception.jpg" alt="Corriendo junto a la recepción del hotel"></td>
  </tr>
  <tr>
    <td><img src="docs/images/preview9/title-menu.jpg" alt="Menú de título de The Order: 1886"></td>
    <td><img src="docs/images/preview9/gameplay-courtyard.jpg" alt="El patio nocturno fuera del hotel"></td>
  </tr>
</table>

### Demostración en vídeo

[![Mira The Order: 1886 ejecutándose en PC](https://i.ytimg.com/vi/wpNkwih0cxI/hqdefault.jpg)](https://youtu.be/wpNkwih0cxI)

[**Mira la demostración en YouTube**](https://youtu.be/wpNkwih0cxI), publicada por **Julio Cacko**.

## Descargar

**Descarga publicada: v0.2.5, del 29 de octubre.** Paquetes para Windows y Linux x86-64. Conserva la carpeta `user` al actualizar.

**[Descargar el paquete para Windows](https://github.com/JulioCacko/The-Order-1886_pc/releases/download/v0.2.5/order1886-go-windows.zip)** · **[Descargar el paquete para Linux](https://github.com/JulioCacko/The-Order-1886_pc/releases/download/v0.2.5/order1886-linux-x86_64.tar.gz)** · [Notas de la versión](https://github.com/JulioCacko/The-Order-1886_pc/releases/tag/v0.2.5) · [Guía de instalación](https://github.com/JulioCacko/The-Order-1886_pc/releases/download/v0.2.5/QUICKSTART.txt)

Los paquetes incluyen el launcher, el runtime dedicado y las bibliotecas necesarias. No hace falta Python, MSYS2 ni compilador. Los archivos “Source code” de GitHub son para desarrolladores.

**Windows**

1. Extrae el ZIP completo en una carpeta con permiso de escritura. Mantén juntos los ejecutables y la carpeta `bin`.
2. Lee **QUICKSTART.txt** y abre **The Order 1886.exe**.
3. Elige la carpeta del juego extraído (cualquier nombre). Debe contener `eboot.bin`, `sce_sys`, `sce_module`, `_data` y `archivemap.bin`.
4. Empieza con **30 FPS** o **60 FPS**, elige el modo de pantalla y pulsa **Play**.

**Linux x86-64**

Extrae el `tar.gz` y ejecuta `The Order 1886`. Requiere un controlador Vulkan y glibc 2.39 o posterior. La ventana del launcher también necesita GTK 3 y WebKitGTK 4.1; sin ellos, `Play The Order 1886 --game-dir /ruta/del/juego` inicia el juego directamente (SteamOS y Steam: consulta `QUICKSTART.txt`). La jugabilidad con un controlador de GPU en Linux aún no se ha probado.

Los archivos originales del juego no se modifican. Las imágenes preparadas, la configuración, la caché, los registros, las partidas y las copias de seguridad quedan en la carpeta `user/order1886` de la instalación.

## Novedades

**v0.2.5 — 29 de octubre de 2026.** **Resolución nativa hasta 4K sin escalador** (#3, #128): Graphics → Render resolution ofrece Original, 2560, 3840 o un ancho personalizado, y el juego dibuja cada pasada del tamaño de la pantalla a ese tamaño. **Sin bordes ya no se convierte en pantalla completa exclusiva** en Windows (#121, #125). **Linux ejecuta volcados con carpetas que mezclan mayúsculas y minúsculas** (#124). TOport recibe crédito por las correcciones del renderizador portadas desde su proyecto (#112, #123). [Notas de la versión](https://github.com/JulioCacko/The-Order-1886_pc/releases/tag/v0.2.5)

**v0.2.4 — 28 de octubre de 2026.** El paquete de Linux arranca sin WebKitGTK 4.1, por ejemplo en SteamOS (#114); `Play The Order 1886` inicia el juego directamente y `--game-dir` define la carpeta del juego. [Notas de la versión](https://github.com/JulioCacko/The-Order-1886_pc/releases/tag/v0.2.4)

**v0.2.3 — 28 de octubre de 2026.** 60 FPS, 16:9 y las demás opciones experimentales funcionan con la actualización 1.02, y se aceptan las seis ediciones del juego (#113). [Notas de la versión](https://github.com/JulioCacko/The-Order-1886_pc/releases/tag/v0.2.3)

## El launcher

<table>
  <tr>
    <td width="50%"><img src="docs/images/preview9/launcher-home.jpg" alt="Página Home del launcher"></td>
    <td width="50%"><img src="docs/images/preview9/launcher-graphics.jpg" alt="Página Graphics"></td>
  </tr>
  <tr>
    <td><img src="docs/images/preview9/launcher-game.jpg" alt="Página Game & Content"></td>
    <td><img src="docs/images/preview9/launcher-system.jpg" alt="Página System"></td>
  </tr>
</table>

| Página | Controles |
| --- | --- |
| **Home** | Play, la configuración de inicio y la comprobación de la instalación del juego |
| **Graphics** | Modo de pantalla, encuadre, resolución de renderizado (nativa hasta 4K), FSR 1/Linear, VSync, resolución de salida, nitidez, anisotropía y los cuatro efectos de posprocesado |
| **Performance** | 30/60/90 FPS y Unlocked, límite de presentación, menú del juego y elementos del overlay |
| **Controls** | Cámara con el ratón, sensibilidad, Y invertido y teclas |
| **Game & Content** | Carpeta del juego, idioma del juego, parches catalogados, partidas, mods, acceso directo y Add to Steam |
| **Achievements** | Trofeos obtenidos, leídos de los datos del propio juego |
| **System** | Runtime alternativo, grabación de rendimiento, idioma del launcher, actualizaciones, registros y caché |

En el juego, **Esc** libera el cursor y **F6** alterna la captura. [Guía de entrada e inicio directo](docs/order1886-input.md). Estructura de páginas adaptada de [mateussmeneses/theorder1886-port](https://github.com/mateussmeneses/theorder1886-port).

## Estado y rendimiento

**60 FPS, 90 FPS y Unlocked son experimentales.** La receta de 60 FPS advierte de posibles bloqueos en los QTE de los capítulos 6 y 9. En una pantalla de 60 Hz, VSync limita cualquier tasa a 60. El objetivo 4K/60 (salida 3840×2160, escalado permitido, 60 FPS sostenidos en juego) aún no se ha alcanzado; el renderizado nativo en 4K llega a 30 FPS.

Consulta el [estado actual completo, en inglés](docs/STATUS.md) y el [plan 4K/60](docs/order1886-4k60-verification.md).

## Problemas, créditos y licencia

Abre **System → Open logs**. Al [informar de un problema](https://github.com/JulioCacko/The-Order-1886_pc/issues), incluye `last-run.json`, el registro de sesión correspondiente, el SHA256 del runtime, los metadatos del juego, la GPU/controlador y los pasos para reproducirlo. Elimina las rutas personales; no subas archivos del juego ni partidas.

[GPL-2.0-or-later](LICENSE). Infraestructura de carga y compilación derivada de [FelipePrado0/gow3_pc](https://github.com/FelipePrado0/gow3_pc); trabajo de gráficos y APIs derivado de [shadPS4](https://github.com/shadps4-emu/shadPS4). Las correcciones del renderizador (bloqueo de la tabla de memoria, lecturas diferidas, draw pipe, sesgo de profundidad en los redibujados y el diagnóstico de HTILE) proceden de TOport, [IgorAugustoHH/The-Order-1886-PC-Port](https://github.com/IgorAugustoHH/The-Order-1886-PC-Port) (GPL-2.0). Organización del README inspirada en [HayatoG/iss_pc](https://github.com/HayatoG/iss_pc). The Order: 1886 pertenece a sus respectivos titulares, incluidos Sony Computer Entertainment y Ready at Dawn; este proyecto no está afiliado ni respaldado por ellos.
