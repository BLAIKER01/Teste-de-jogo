# Jogo de fuga (Teste 6 melhorado)

## Como rodar
1. Instale o Pygame: `pip install pygame` (ou `pip install -r requirements.txt`)
2. Deixe **estes 3 arquivos na mesma pasta**: `Teste_6_melhorado.py`, `assets_b64.py`, `mapas.py`
3. `python Teste_6_melhorado.py`

Opção para testar: `python Teste_6_melhorado.py --fase 8` começa direto na fase 8.
No jogo, **F3** liga a depuração da IA e, com ela ligada, **F4** pula a fase.

## Controles
| Ação | Teclado (padrão) | Controle |
|---|---|---|
| Mover | Setas / WASD | D-pad ou analógico esquerdo |
| Interagir | E | A |
| Pulso | Espaço | X ou B |
| Pausar | P | Start |
| Reiniciar | R | LB |
| Próxima fase (após vencer) | N | Y |
| Menu / voltar | Esc | Back |

No menu: **O** abre as Opções (dificuldade, volume, tela cheia e **configurar teclas**).
Também: M liga/desliga o som, F5/F6 volume da música, F7/F8 volume dos efeitos, F11 tela cheia.
(O código do bilhete só pode ser digitado pelo teclado.)

## Novidades
- Dificuldades FÁCIL / NORMAL / DIFÍCIL, volumes e teclas configuráveis, suporte a controle.
- Drones novos: **fantasma** (azul, teleporta, fase 6+), **sentinela** (verde, visão longa, fase 8+),
  **chefe** (roxo, fases 5, 10, 15...). Fases de **apagão** (3, 7, 11...).
- Itens novos: **RELÓGIO** (congela drones) e **SILÊNCIO** (barulho não atrai drones).
- Combo de pontos (x2 a x4), bônus por tempo e por não ser notado, borda vermelha de perigo.
- Tutorial por dicas na primeira vez que você vê cada coisa; 6 conquistas (veja na pausa).
- Respawn seguro, buffer de curva, alcance do pulso visível, jogo com velocidade igual em qualquer FPS.

## Testes automáticos
`python test_jogo.py` — gera 43 fases e confere que todas dá para vencer, simula centenas de quadros
em todas as dificuldades e testa itens, drones, teclas, conquistas e opções. Não mexe nos seus saves.

## Gerar um .exe (Windows)
Execute `build_exe.bat`. O executável guarda config, placar, conquistas e cache de áudio em
`%APPDATA%\MansaoFugaSombria`.

## Arquivos que o jogo cria
`config.json` (opções), `recorde.json` (placar), `conquistas.json`, `ai_memoria.json` (o que a IA aprendeu
sobre você) e a pasta `audio_cache/` (sons gerados na primeira abertura).

## Remodelagem visual (v2)
- Novos arquivos na mesma pasta: `asset_loader.py` e `fx.py`, além da pasta `assets/`.
- **Sprites de terceiros:** coloque PNGs em `assets/sprites/` e sons em `assets/audio/` (veja `assets/README.md`);
  eles substituem os embutidos automaticamente. Registre os créditos em `ASSET_CREDITS.md`.
- **Efeitos:** luz aditiva em volta do jogador e dos olhos dos drones, névoa, poeira, vinheta, fade de entrada,
  poeira de passos e animação do jogador. **F9** liga/desliga; `--sem-efeitos` abre sem eles.
