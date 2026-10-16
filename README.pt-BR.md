# The Order: 1886 para PC — runtime experimental de compatibilidade com PS4

[English](README.md) · **Português (Brasil)** · [Español](README.es.md)

Projeto comunitário para executar o binário original de **The Order: 1886**, edição PS4 **CUSA00076**, com launcher nativo para Windows e renderização Vulkan. Reutiliza infraestrutura de carregamento PS4 e trabalho de gráficos/APIs do [shadPS4](https://github.com/shadps4-emu/shadPS4).

**Prévia de desenvolvimento: a jogabilidade ainda não foi verificada.** A introdução, a inicialização do save e sua reabertura foram observadas. Gameplay 3D representativo, progressão por checkpoints, estabilidade por 30 minutos e saída 4K a 60 FPS continuam pendentes. Não é um lançamento oficial para PC nem um port confirmado como jogável.

![Launcher Windows de The Order: 1886 com pasta do jogo, modo de exibição, FSR 1, seleção de FPS e botão Play](docs/images/order1886-launcher.png)

*Captura real do launcher em 16 de outubro de 2026. O fundo é uma ilustração gerada; não é gameplay. “30 FPS” é o limite selecionado, não uma medição.*

## Iniciar

Use sua própria cópia extraída de CUSA00076, contendo `eboot.bin`, `sce_sys` e `sce_module`. Nenhum dump, executável do jogo ou save do jogador é distribuído. Os originais são preservados; configurações, imagens preparadas, cache, logs, saves e backups ficam separados.

1. Extraia o pacote portátil completo para uma pasta com permissão de escrita.
2. Abra **The Order 1886.exe** e escolha **Game folder** na barra inferior.
3. Comece com **30 FPS**; selecione o modo de exibição e FSR 1 ou Linear.
4. Use **Play**, **View logs** e **Stop session** para iniciar, acompanhar ou encerrar a sessão.

No código-fonte, execute `Launch The Order 1886.cmd` ou `python launcher/order1886_launcher.py` após seguir as [instruções de build para Windows](docs/order1886-build.md). Usuários do pacote não precisam de Python ou MSYS2. Não há pacote Linux verificado para este alvo específico.

## Estado e desempenho

O launcher oferece modos Janela/Sem bordas/Tela cheia, VSync e overlay de desempenho (F9). **60 FPS é experimental e opcional**; conteúdo sensível ao tempo, incluindo os capítulos 6 e 9, ainda precisa de verificação. O objetivo é saída 3840 × 2160 com upscaling permitido e 60 FPS sustentados em gameplay; esse objetivo ainda não foi atingido.

Leia o [relatório completo do estado atual, em inglês](docs/STATUS.md), a [evidência de runtime](docs/order1886-runtime-status.md) e o [plano 4K/60](docs/order1886-4k60-verification.md). Um congelamento anterior do PC exigiu reinicialização manual; a causa permanece desconhecida. Testes de CPU e do launcher não comprovam estabilidade ou jogabilidade.

## Problemas e licença

Abra **View logs → Open log folder**. Ao [relatar um problema](https://github.com/JulioCacko/The-Order-1886_pc/issues), inclua os logs e `last-run.json` correspondentes de `user/order1886/logs`, SHA256 do runtime, metadados do jogo e GPU/driver. Remova dados privados; não envie arquivos do jogo ou saves.

[GPL-2.0-or-later](LICENSE). Infraestrutura reutilizada de [FelipePrado0/gow3_pc](https://github.com/FelipePrado0/gow3_pc) e [shadPS4](https://github.com/shadps4-emu/shadPS4), com atribuição e licenças preservadas. The Order usa outro motor; patches e desempenho de outro título não comprovam compatibilidade. Sem afiliação ou endosso de Ready at Dawn ou Sony.
