"""
Efeitos visuais e atmosfera (iluminação aditiva, névoa, poeira, vinheta, fade e animação do jogador).

Tudo é pré-renderizado uma vez e reaproveitado (sem alocar superfícies por quadro), e o movimento
depende só do relógio do jogo (game.anim): quando o jogo pausa, os efeitos congelam junto.
F9 liga/desliga os efeitos; --sem-efeitos abre com eles desligados.
"""
import math
import random
import sys

import pygame

ENABLED = "--sem-efeitos" not in sys.argv


def toggle():
    global ENABLED
    ENABLED = not ENABLED
    return ENABLED


def _radial_light(radius, peak, color):
    """Superfície RGB com brilho que cai suavemente do centro (para BLEND_RGB_ADD)."""
    s = pygame.Surface((radius * 2, radius * 2))
    s.fill((0, 0, 0))
    for r in range(radius, 0, -2):
        k = (1.0 - r / radius) ** 2 * peak
        c = tuple(min(255, int(ch * k)) for ch in color)
        pygame.draw.circle(s, c, (radius, radius), r)
    return s.convert()


class FX:
    FADE_FRAMES = 24

    def __init__(self, tile, size):
        self.tile = tile
        self.w, self.h = size
        rng = random.Random(11)
        # Poeira: (x0, y0, vx, vy, fase, tamanho)
        self.motes = [(rng.uniform(0, self.w), rng.uniform(0, self.h), rng.uniform(-5, 5),
                       rng.uniform(-4, -0.5), rng.uniform(0, 6.28), rng.choice((1, 1, 2)))
                      for _ in range(46)]
        self._mote_surf = {}
        for s in (1, 2):
            surf = pygame.Surface((s * 4 + 2, s * 4 + 2), pygame.SRCALPHA)
            pygame.draw.circle(surf, (210, 220, 255, 255), (surf.get_width() // 2, surf.get_height() // 2), s + 1)
            self._mote_surf[s] = surf.convert_alpha()
        self.fog = [self._make_fog(rng, 24, (120, 140, 190)), self._make_fog(rng, 16, (150, 120, 170))]
        self.vignette = self._make_vignette()
        self.fade_surf = pygame.Surface((self.w, self.h)).convert()
        self.fade_surf.fill((6, 8, 18))
        # Luzes: 3 níveis de intensidade para dar tremulação sem alocar nada por quadro.
        self.player_light = [_radial_light(int(tile * 3.2), p, (255, 214, 150)) for p in (0.22, 0.30, 0.38)]
        self.eye_light = {}
        self.steps = []              # poeira dos passos: [x, y, idade_inicial]
        self._last_anim = -1
        self._squash = {}
        self._death_start = None
        self._sheets = {}
        self._face_left = False

    # ---------- construção ----------
    def _make_fog(self, rng, blobs, color):
        sw, sh = 64, 36
        small = pygame.Surface((sw, sh), pygame.SRCALPHA)
        for _ in range(blobs):
            x, y, r = rng.randrange(sw), rng.randrange(sh), rng.randrange(5, 12)
            for dx in (-sw, 0, sw):               # repete nas bordas: rola sem emenda
                pygame.draw.circle(small, (*color, rng.randrange(10, 26)), (x + dx, y), r)
        return pygame.transform.smoothscale(small, (self.w, self.h)).convert_alpha()

    def _make_vignette(self):
        sw, sh = 48, 27
        small = pygame.Surface((sw, sh), pygame.SRCALPHA)
        for y in range(sh):
            for x in range(sw):
                dx = (x + 0.5) / sw * 2 - 1
                dy = (y + 0.5) / sh * 2 - 1
                d = min(1.0, math.hypot(dx, dy) / 1.25)
                small.set_at((x, y), (0, 0, 8, int(165 * max(0.0, d - 0.35) / 0.65)))
        return pygame.transform.smoothscale(small, (self.w, self.h)).convert_alpha()

    # ---------- desenho ----------
    def draw_lights(self, surf, game):
        """Poças de luz aditivas: calor em volta do jogador e brilho dos olhos dos drones."""
        if not ENABLED:
            return
        t = game.anim
        level = (int(t / 5) + int(math.sin(t / 9.0) * 1.4)) % 3 if game.blackout is False else 1
        px = int(game.player.x + self.tile // 2)
        py = int(game.player.y + self.tile // 2)
        img = self.player_light[level]
        surf.blit(img, img.get_rect(center=(px, py)), special_flags=pygame.BLEND_RGB_ADD)
        for d in game.drones:
            if d.delay > 0:
                continue
            col = d.EYE.get(d.state) if hasattr(d, "EYE") else None
            if not col:
                continue
            light = self.eye_light.get(col)
            if light is None:
                light = self.eye_light[col] = _radial_light(int(self.tile * 1.6), 0.30, col)
            surf.blit(light, light.get_rect(center=(int(d.x + self.tile // 2), int(d.y + self.tile // 2))),
                      special_flags=pygame.BLEND_RGB_ADD)

    def draw_atmosphere(self, surf, game, step_cb=None):
        """Névoa rolando devagar, poeira flutuando e poeira dos passos."""
        if not ENABLED:
            return
        t = game.anim / 60.0
        for i, fog in enumerate(self.fog):
            off = int((t * (6 + 5 * i)) % self.w)
            fog.set_alpha(150 if not game.blackout else 90)
            surf.blit(fog, (-off, 0))
            surf.blit(fog, (self.w - off, 0))
        for x0, y0, vx, vy, ph, size in self.motes:
            x = (x0 + vx * t) % self.w
            y = (y0 + vy * t + 3 * math.sin(t + ph)) % self.h
            img = self._mote_surf[size]
            img.set_alpha(int(60 + 50 * math.sin(t * 1.7 + ph)))
            surf.blit(img, (x, y))
        # Passos: nasce uma nuvenzinha a cada 8 quadros de caminhada.
        moving = tuple(game.player.direction) != (0, 0) and not (game.game_over or game.won)
        if game.anim != self._last_anim:
            self._last_anim = game.anim
            if moving and game.anim % 8 == 0:
                self.steps.append([game.player.x + self.tile // 2 + random.randint(-3, 3),
                                   game.player.y + self.tile - 6, game.anim])
                if step_cb:
                    step_cb()
            self.steps = [s for s in self.steps if game.anim - s[2] < 22]
        for x, y, born in self.steps:
            age = (game.anim - born) / 22.0
            r = 2 + int(5 * age)
            img = self._puff(r)
            img.set_alpha(int(110 * (1 - age)))
            surf.blit(img, img.get_rect(center=(int(x), int(y - 6 * age))))

    def _puff(self, r):
        key = ("puff", r)
        img = self._squash.get(key)
        if img is None:
            img = pygame.Surface((r * 2 + 2, r * 2 + 2), pygame.SRCALPHA)
            pygame.draw.circle(img, (170, 180, 210, 255), (r + 1, r + 1), r)
            img = self._squash[key] = img.convert_alpha()
        return img

    def draw_vignette(self, surf, game):
        if ENABLED:
            surf.blit(self.vignette, (0, 0))

    def draw_fade(self, surf, game):
        """Entrada suave no começo de cada fase."""
        if ENABLED and game.anim < self.FADE_FRAMES:
            self.fade_surf.set_alpha(int(255 * (1 - game.anim / self.FADE_FRAMES)))
            surf.blit(self.fade_surf, (0, 0))

    # ---------- jogador ----------
    def _frames(self, name):
        if name not in self._sheets:
            import asset_loader as AL
            img = AL.external_image(name)
            self._sheets[name] = AL.split_square_strip(img) if img is not None else None
        return self._sheets[name]

    def draw_player(self, surf, game, base_img, px, py):
        """Jogador: usa as faixas player_* de terceiros se existirem; senão anima o sprite base
        (inclinação ao andar, 'squash' suave e espelhamento conforme a direção)."""
        dx, dy = game.player.direction
        moving = (dx, dy) != (0, 0)
        if game.game_over and self._death_start is None:
            self._death_start = game.anim
        if not game.game_over:
            self._death_start = None
        state = ("player_death" if game.game_over else
                 "player_hurt" if game.invincible > 0 else
                 "player_walk" if moving else "player_idle")
        frames = self._frames(state) if ENABLED else None
        if frames:
            if state == "player_death":
                i = min(len(frames) - 1, (game.anim - (self._death_start or game.anim)) // 8)
            else:
                i = (game.anim // 6) % len(frames)
            img = pygame.transform.scale(frames[i], base_img.get_size())
        else:
            img = base_img
            if ENABLED:
                phase = (game.anim // 3) % 6 if moving else 0
                k = math.sin(phase / 6.0 * 6.283) * 0.07 if moving else 0.015 * math.sin(game.anim / 20.0)
                size = (int(img.get_width() * (1 + k)), int(img.get_height() * (1 - k)))
                key = (id(base_img), size)
                cached = self._squash.get(key)
                if cached is None:
                    cached = self._squash[key] = pygame.transform.scale(base_img, size)
                img = cached
        if dx:
            self._face_left = dx < 0
        if self._face_left:
            img = pygame.transform.flip(img, True, False)
        surf.blit(img, img.get_rect(center=(px, py)))
