# Como trocar a arte por sprites de terceiros

1. Baixe um pacote gratuito (Kenney.nl, OpenGameArt, itch.io...) e confira a licença.
2. Copie o PNG para `assets/sprites/` com o nome esperado (veja o topo de `asset_loader.py`):
   `pilot.png`, `key.png`, `portal.png`, `chip.png`, `battery.png`, `shield.png`, `vial.png`, `spark.png`,
   `drone_strip.png` e `orb_strip.png` (faixa horizontal de 4 quadros), `walls.png` (atlas 4x4:
   4 estilos de fase nas linhas; colunas top, face, cap_left, cap_right).
3. Opcional, jogador animado: `player_idle.png`, `player_walk.png`, `player_hurt.png`, `player_death.png`
   (faixas horizontais de quadros quadrados).
4. Sons em `assets/audio/<efeito>.ogg|wav` (ex.: `key`, `hit`, `win`, `pickup`, `step`).
5. Registre autor, link e licença em `ASSET_CREDITS.md`.

Sem o arquivo, o jogo usa o sprite embutido. Para voltar ao original, apague o PNG.
