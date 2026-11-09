"""
Carregador de recursos de terceiros (sprites e sons) com fallback para os embutidos.

Como funciona: se existir assets/sprites/<nome>.png, ele substitui o sprite embutido de mesmo nome.
Se não existir, o jogo usa o sprite embutido (base64) como sempre. Assim dá para trocar a arte
aos poucos, com pacotes gratuitos (Kenney, OpenGameArt, itch.io...), sem quebrar nada.

Nomes aceitos em assets/sprites/ (PNG):
  walls          atlas 4x4 de paredes (linhas = estilos; colunas = top, face, cap_left, cap_right)
  key, portal, chip, battery, pilot, shield, vial, spark   (um quadro cada)
  drone_strip, orb_strip                                    (faixa horizontal com 4 quadros)
  player_idle, player_walk, player_hurt, player_death       (opcionais; faixa horizontal, quadros quadrados)
Sons em assets/audio/<nome>.ogg ou .wav, com o nome do efeito (ex.: key, hit, win, pickup).
"""
import os
import sys

import pygame

SPRITE_EXTS = (".png",)
SOUND_EXTS = (".ogg", ".wav")
_IMG_CACHE = {}
_EXTERNAL = set()


def _base_dir():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


ASSET_DIR = os.environ.get("MANSAO_ASSET_DIR") or os.path.join(_base_dir(), "assets")


def external_image(name):
    """Devolve a imagem de assets/sprites/<name>.png (ou None se não existir ou for inválida)."""
    if name in _IMG_CACHE:
        return _IMG_CACHE[name]
    img = None
    for ext in SPRITE_EXTS:
        path = os.path.join(ASSET_DIR, "sprites", name + ext)
        if os.path.isfile(path):
            try:
                img = pygame.image.load(path).convert_alpha()
                _EXTERNAL.add(name)
            except pygame.error:
                img = None
            break
    _IMG_CACHE[name] = img
    return img


def is_external(name):
    external_image(name)
    return name in _EXTERNAL


def load_embedded(b64, name):
    """Sprite externo se existir; senão o embutido em base64."""
    import base64
    import io
    ext = external_image(name)
    if ext is not None:
        return ext
    return pygame.image.load(io.BytesIO(base64.b64decode(b64)), name + ".png").convert_alpha()


def split_strip(strip, count=4):
    """Divide uma faixa horizontal em 'count' quadros (qualquer resolução)."""
    fw = max(1, strip.get_width() // count)
    return [strip.subsurface((i * fw, 0, fw, strip.get_height())) for i in range(count)]


def split_square_strip(strip):
    """Faixa com quadros quadrados (largura = n * altura)."""
    fh = strip.get_height()
    n = max(1, strip.get_width() // max(1, fh))
    return [strip.subsurface((i * fh, 0, fh, fh)) for i in range(n)]


def fit(img, max_side):
    """Escala mantendo a proporção até o maior lado = max_side (pixel art nítida ao ampliar)."""
    w, h = img.get_size()
    k = max_side / float(max(w, h))
    size = (max(1, round(w * k)), max(1, round(h * k)))
    if k >= 1:
        return pygame.transform.scale(img, size)
    return pygame.transform.smoothscale(img, size)


def external_sound(name):
    """Som de assets/audio/<name>.ogg|wav, ou None."""
    for ext in SOUND_EXTS:
        path = os.path.join(ASSET_DIR, "audio", name + ext)
        if os.path.isfile(path):
            try:
                return pygame.mixer.Sound(path)
            except pygame.error:
                return None
    return None
