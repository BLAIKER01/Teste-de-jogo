# Mansão: Fuga Sombria 3D

Rode `python Teste_6_3d.py` (precisa de `render3d.py`, `assets_b64.py` e `mapas.py` na mesma pasta).
O jogo original (`Teste_6_melhorado.py`) continua intacto.

## Controles novos
- **W / S** (ou ↑ / ↓): andar para frente / para trás
- **A / D** (ou ← / →) ou **mouse**: girar a câmera
- **F2**: liga/desliga o minimapa (ele só mostra o que você já explorou)
- Resto igual: E interagir, Espaço pulso, P pausa, R reiniciar, Esc menu.

## Ajustes (no topo de `Game`, em `Teste_6_3d.py`)
`TURN_SPEED`, `MOUSE_SENS`, `PLAYER_RADIUS`; campo de visão em `render3d.py` (`self.fov`).
