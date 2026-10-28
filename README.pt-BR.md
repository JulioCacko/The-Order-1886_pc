# The Order: 1886 para PC — runtime experimental de compatibilidade com PS4

<p align="center"><img src="launcher/order1886/logo-horizontal.png" width="720" alt="Logo oficial de The Order: 1886"></p>

[English](README.md) · **Português (Brasil)** · [Español](README.es.md)

Projeto comunitário para executar o binário original de **The Order: 1886**, atualização 1.02 em qualquer edição PS4 (**CUSA00076**, testada; CUSA00035, CUSA00070, CUSA00100, CUSA00670 e CUSA00785, experimentais), com launcher nativo para Windows e renderização Vulkan. Reutiliza infraestrutura de carregamento PS4 e trabalho de gráficos/APIs do [shadPS4](https://github.com/shadps4-emu/shadPS4).

**Em desenvolvimento — 18 de outubro de 2026.** Cinemáticas são renderizadas e uma rota de rua foi exercitada, mas o desempenho continua baixo. Progressão, saves por checkpoint, estabilidade e 4K/60 ainda não foram aceitos. O run de Capítulo 2 com cópias dos saves chegou ao timeout sem a asserção de 8.029 camadas; erros SRT permanecem e a issue #5 continua aberta.

![Launcher Windows de The Order: 1886 com navegação lateral e barra de início permanente](docs/images/preview9/launcher-home.jpg)

*Captura real do launcher atual em 18 de outubro, 1240 × 800, com configurações isoladas. Não é gameplay; 30 FPS é a configuração selecionada.*

## Demonstração em vídeo

[![Assista a The Order: 1886 rodando no PC](https://i.ytimg.com/vi/wpNkwih0cxI/hqdefault.jpg)](https://youtu.be/wpNkwih0cxI)

[**Assista à demonstração no YouTube**](https://youtu.be/wpNkwih0cxI) — registro do projeto rodando no PC, publicado por **Julio Cacko**. Clique na miniatura para assistir.

## Baixar

**Download publicado: preview 9, de 21 de outubro.** Pacotes para Windows e Linux x86-64, ambos compilados a partir da revisão `b19c604`. A jogabilidade roda a cerca de 53 FPS no pátio noturno numa RTX 3070. Preserve a pasta `user` ao atualizar.

**[Baixar o pacote para Windows](https://github.com/JulioCacko/The-Order-1886_pc/releases/download/v0.2.2/order1886-go-windows.zip)** · **[Baixar o pacote para Linux](https://github.com/JulioCacko/The-Order-1886_pc/releases/download/v0.2.2/order1886-linux-x86_64.tar.gz)** · [Notas da versão](https://github.com/JulioCacko/The-Order-1886_pc/releases/tag/v0.1.0-go-preview.9) · [Manual de instalação](https://github.com/JulioCacko/The-Order-1886_pc/releases/download/v0.2.2/QUICKSTART.txt)

Extraia o ZIP inteiro e leia **QUICKSTART.txt**, incluído no pacote. Não precisa de Python, MSYS2 ou compilador. Baixe `order1886-go-windows.zip`; os arquivos “Source code” são para desenvolvedores. O jogo não está incluído: use seu próprio dump (qualquer uma das seis edições). Esta prévia mantém as limitações de compatibilidade descritas acima.

## Novidades no código-fonte — 18 de outubro

- Mouse look por emulação do stick, sensibilidade e inversão Y; início direto por **Play The Order 1886.exe**, atalho de desktop e **Game → Add to Steam** (feche o Steam antes).
- Backups com ordenação numérica, mods de assets `_data` reversíveis com ordem/conflitos, limpeza segura do cache e 13 idiomas de interface com fallback inglês. Validação visual de árabe/CJK continua pendente.
- Correções de shaders NaN/atomics, cópia de chaves de pipeline, memória e mutex; suporte a dumps ELF x86-64 validados.
- **340 testes Python no Windows sem skips; Linux: 340 executados, 21 skips; Windows: 41 checks nativos, Linux: subconjunto nativo aprovado; Windows 15 e Linux 10 checks portáteis.** [Evidência](docs/verification/2026-10-18-preview4-release.md) · [Estado das issues](docs/order1886-issue-status.md).

![Utilitários atuais: atalho, Steam e saves](docs/images/preview9/launcher-game.jpg)

No jogo, **Esc** libera o cursor e **F6** alterna a captura. Ajuste o mouse em **Game → Controls** e salve. Remapeamento, câmera direta 1:1, idiomas de texto/voz independentes, conquistas ao vivo e atualizador automático continuam pendentes. [Guia de entrada e início direto](docs/order1886-input.md).

Em **Game**, selecione um backup e pressione **Play** para confirmar a restauração antes de iniciar, ou use **Restore selected backup**. O save atual é copiado primeiro; depois escolha Continue/Load no jogo. Backups antigos podem não conter Profile/progresso. Em **Advanced**, o idioma salvo também é solicitado ao jogo no próximo início; exige os assets de idioma instalados. Reinicie o launcher para traduzir sua interface.

## O launcher

Estrutura adaptada de [mateussmeneses/theorder1886-port](https://github.com/mateussmeneses/theorder1886-port), preservando nosso backend e os saves de CUSA00076. A apresentação do README segue a organização de [HayatoG/iss_pc](https://github.com/HayatoG/iss_pc).

| Página | Função |
| --- | --- |
| Home | Pasta do jogo, opções rápidas e Play/Stop |
| Graphics | Tela, proporção, FSR 1/Linear e VSync |
| Performance | 30 FPS, 60/90 FPS e Unlocked experimentais, e overlay F9 |
| Game | Arquivos, atalhos de desktop/Steam, saves, mods de assets e controles do mouse |
| Advanced | Idioma do launcher, runtime, logs, cache de shaders e releases manuais |

Use **Save settings** para gravar as opções. Iniciar por uma página de opções também grava os valores antes de abrir o jogo. A restauração pede confirmação e cria um backup do save substituído; fica bloqueada durante uma sessão. A janela Tk que servia de launcher alternativo foi removida: o launcher em Go é o único. Mods de assets estão disponíveis; patches executáveis externos, recursos temporais e atualizador automático continuam pendentes; veja a [análise de reaproveitamento](docs/order1886-reference-reuse.md).

## Iniciar

Use sua própria cópia extraída de qualquer uma das seis edições, contendo `eboot.bin`, `sce_sys` e `sce_module`. Nenhum dump, executável do jogo ou save do jogador é distribuído. Os originais são preservados; configurações, imagens preparadas, cache, logs, saves e backups ficam separados.

1. Extraia o pacote portátil completo para uma pasta com permissão de escrita.
2. Abra **The Order 1886.exe** e escolha **Game folder** na barra inferior.
3. Comece com **30 FPS**; selecione o modo de exibição e FSR 1 ou Linear.
4. Use **Play**, **Advanced → View session log** e **Stop session** para iniciar, acompanhar ou encerrar a sessão.

No código-fonte, execute `Launch The Order 1886.cmd` ou o launcher em Go compilado após seguir as [instruções de build para Windows](docs/order1886-build.md). Usuários do pacote não precisam de Python ou MSYS2. **Linux x86-64 volta a ser compilado** como `tar.gz` portátil com o launcher em Go, o runtime nativo e o worker em Python. Não está qualificado: nada disso executou o jogo, e o teste automático cobre o pacote, não o jogo. Requer um driver com Vulkan e um desktop com GTK 3 e WebKitGTK 4.1. Veja o [guia de build](docs/order1886-build.md).

## Estado e desempenho

O launcher oferece modos Janela/Sem bordas/Tela cheia, VSync e overlay de desempenho (F9). **60 FPS, 90 FPS e Unlocked são experimentais e opcionais**; conteúdo sensível ao tempo, incluindo os capítulos 6 e 9, ainda precisa de verificação. O objetivo é saída 3840 × 2160 com upscaling permitido e 60 FPS sustentados em gameplay; esse objetivo ainda não foi atingido.

Leia o [relatório completo do estado atual, em inglês](docs/STATUS.md), a [evidência de runtime](docs/order1886-runtime-status.md) e o [plano 4K/60](docs/order1886-4k60-verification.md). Um congelamento anterior do PC exigiu reinicialização manual; a causa permanece desconhecida. Testes de CPU e do launcher não comprovam estabilidade ou jogabilidade.

## Problemas e licença

Abra **Advanced → Open log folder**. Ao [relatar um problema](https://github.com/JulioCacko/The-Order-1886_pc/issues), inclua os logs e `last-run.json` correspondentes de `user/order1886/logs`, SHA256 do runtime, metadados do jogo e GPU/driver. Remova dados privados; não envie arquivos do jogo ou saves.

[GPL-2.0-or-later](LICENSE). Infraestrutura reutilizada de [FelipePrado0/gow3_pc](https://github.com/FelipePrado0/gow3_pc) e [shadPS4](https://github.com/shadps4-emu/shadPS4), com atribuição e licenças preservadas. The Order usa outro motor; patches e desempenho de outro título não comprovam compatibilidade. Sem afiliação ou endosso de Ready at Dawn ou Sony.
