# The Order: 1886 para PC — runtime experimental de compatibilidade com PS4

<p align="center"><img src="launcher/order1886/logo-horizontal.png" width="720" alt="Logo oficial de The Order: 1886"></p>

[English](README.md) · **Português (Brasil)** · [Español](README.es.md)

Projeto comunitário para executar o binário original de **The Order: 1886**, edição PS4 **CUSA00076**, com launcher nativo para Windows e renderização Vulkan. Reutiliza infraestrutura de carregamento PS4 e trabalho de gráficos/APIs do [shadPS4](https://github.com/shadps4-emu/shadPS4).

**Em desenvolvimento.** O jogo inicia e renderiza cinemáticas 3D, como mostra a gravação de 17 de outubro. A inicialização do save e sua reabertura também foram observadas. Jogabilidade interativa, progressão por checkpoints, estabilidade por 30 minutos e saída 4K a 60 FPS continuam pendentes. O log enviado termina em uma asserção Vulkan: a imagem solicita 8.029 camadas, acima do limite de 2.048. Não é um lançamento oficial para PC nem um port confirmado como jogável.

![Launcher Windows de The Order: 1886 com navegação lateral e barra de início permanente](docs/images/order1886-desktop.png)

*Captura real do launcher de cinco páginas com a imagem fornecida pelo usuário em 17 de outubro. Não é gameplay. “30 FPS” é o limite selecionado, não uma medição.*

## Demonstração em vídeo

[![Assista a The Order: 1886 rodando no PC](https://i.ytimg.com/vi/wpNkwih0cxI/hqdefault.jpg)](https://youtu.be/wpNkwih0cxI)

[**Assista à demonstração no YouTube**](https://youtu.be/wpNkwih0cxI) — registro do projeto rodando no PC, publicado por **Julio Cacko**. Clique na miniatura para assistir.

## Baixar

**[Baixar o ZIP do launcher para Windows](https://github.com/JulioCacko/The-Order-1886_pc/releases/download/v0.1.0-preview.2/order1886-windows.zip)** · [Notas da versão](https://github.com/JulioCacko/The-Order-1886_pc/releases/tag/v0.1.0-preview.2) · [Manual em português e inglês](https://github.com/JulioCacko/The-Order-1886_pc/releases/download/v0.1.0-preview.2/QUICKSTART.txt)

Extraia o ZIP inteiro e leia **QUICKSTART.txt**, incluído no pacote. Não precisa de Python, MSYS2 ou compilador. Baixe `order1886-windows.zip`; os arquivos “Source code” são para desenvolvedores. O jogo não está incluído: use seu próprio dump CUSA00076. Esta prévia mantém as limitações de compatibilidade descritas acima.

## O launcher

Estrutura adaptada de [mateussmeneses/theorder1886-port](https://github.com/mateussmeneses/theorder1886-port), preservando nosso backend e os saves de CUSA00076. A apresentação do README segue a organização de [HayatoG/iss_pc](https://github.com/HayatoG/iss_pc).

| Página | Função |
| --- | --- |
| Home | Pasta do jogo, opções rápidas e Play/Stop |
| Graphics | Tela, proporção, FSR 1/Linear e VSync |
| Performance | 30 FPS, 60 FPS experimental e overlay F9 |
| Game | Verificação de arquivos, pasta de dados, backup e restauração de saves |
| Advanced | Runtime opcional, logs, pastas, releases e suporte |

Use **Save settings** para gravar as opções. Iniciar por uma página de opções também grava os valores antes de abrir o jogo. A restauração pede confirmação e cria um backup do save substituído; fica bloqueada durante uma sessão. O launcher anterior continua disponível com `python launcher/order1886_launcher.py --classic`. Opções de GPU, mods e atualizador do projeto de referência ainda exigem adaptação; veja a [análise de reaproveitamento](docs/order1886-reference-reuse.md).

## Iniciar

Use sua própria cópia extraída de CUSA00076, contendo `eboot.bin`, `sce_sys` e `sce_module`. Nenhum dump, executável do jogo ou save do jogador é distribuído. Os originais são preservados; configurações, imagens preparadas, cache, logs, saves e backups ficam separados.

1. Extraia o pacote portátil completo para uma pasta com permissão de escrita.
2. Abra **The Order 1886.exe** e escolha **Game folder** na barra inferior.
3. Comece com **30 FPS**; selecione o modo de exibição e FSR 1 ou Linear.
4. Use **Play**, **Advanced → View session log** e **Stop session** para iniciar, acompanhar ou encerrar a sessão.

No código-fonte, execute `Launch The Order 1886.cmd` ou `python launcher/order1886_launcher.py` após seguir as [instruções de build para Windows](docs/order1886-build.md). Usuários do pacote não precisam de Python ou MSYS2. Não há pacote Linux verificado para este alvo específico.

## Estado e desempenho

O launcher oferece modos Janela/Sem bordas/Tela cheia, VSync e overlay de desempenho (F9). **60 FPS é experimental e opcional**; conteúdo sensível ao tempo, incluindo os capítulos 6 e 9, ainda precisa de verificação. O objetivo é saída 3840 × 2160 com upscaling permitido e 60 FPS sustentados em gameplay; esse objetivo ainda não foi atingido.

Leia o [relatório completo do estado atual, em inglês](docs/STATUS.md), a [evidência de runtime](docs/order1886-runtime-status.md) e o [plano 4K/60](docs/order1886-4k60-verification.md). Um congelamento anterior do PC exigiu reinicialização manual; a causa permanece desconhecida. Testes de CPU e do launcher não comprovam estabilidade ou jogabilidade.

## Problemas e licença

Abra **Advanced → Open log folder**. Ao [relatar um problema](https://github.com/JulioCacko/The-Order-1886_pc/issues), inclua os logs e `last-run.json` correspondentes de `user/order1886/logs`, SHA256 do runtime, metadados do jogo e GPU/driver. Remova dados privados; não envie arquivos do jogo ou saves.

[GPL-2.0-or-later](LICENSE). Infraestrutura reutilizada de [FelipePrado0/gow3_pc](https://github.com/FelipePrado0/gow3_pc) e [shadPS4](https://github.com/shadps4-emu/shadPS4), com atribuição e licenças preservadas. The Order usa outro motor; patches e desempenho de outro título não comprovam compatibilidade. Sem afiliação ou endosso de Ready at Dawn ou Sony.
