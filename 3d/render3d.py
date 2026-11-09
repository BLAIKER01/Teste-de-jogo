"""
Renderizador 3D em primeira pessoa (raycasting estilo Wolfenstein) para o jogo Mansão: Fuga Sombria.

Só usa Pygame. Desenha o mundo numa superfície pequena (640x360), amplia para a tela
e depois o jogo desenha HUD, mensagens e telas por cima.
  • Paredes texturizadas (mesmos tiles do jogo) com névoa por distância
  • Sprites "billboard" para drones, itens, chave, bilhete, console, saída e pontinhos
  • Minimapa com névoa de exploração (F2 liga/desliga)
"""
import math
import pygame

RED = (255, 65, 80)
WHITE = (245, 248, 255)
GOLD = (255, 180, 45)
GREEN = (70, 235, 125)
CYAN = (50, 235, 235)


class Renderer:
    IW, IH, RW = 640, 360, 2          # resolução interna e largura de cada raio (px)
    N_SHADE = 12                      # níveis de escurecimento por distância
    TEX = 32                          # tamanho do tile de parede

    def __init__(self, assets):
        self.a = assets
        self.tile = assets["TILE"]
        self.view = pygame.Surface((self.IW, self.IH)).convert()
        self.n_rays = self.IW // self.RW
        self.zbuf = [1e9] * self.n_rays
        self.fov = 66.0
        self.bg_cache = {}
        self.shade_cache = {}
        self.size_cache = {}
        self.door_tex = self._make_door()
        self.shield_vig = None

    # ---------- recursos ----------
    def _make_door(self):
        s = pygame.Surface((32, 32))
        s.fill((120, 34, 44))
        pygame.draw.rect(s, (70, 16, 26), (0, 0, 32, 32), 3)
        pygame.draw.rect(s, (170, 60, 70), (5, 5, 22, 22), 2)
        pygame.draw.circle(s, (255, 200, 60), (16, 16), 4)
        pygame.draw.circle(s, (40, 10, 16), (16, 16), 2)
        return s

    def background(self, dark):
        s = self.bg_cache.get(dark)
        if s is None:
            s = pygame.Surface((self.IW, self.IH)).convert()
            half = self.IH // 2
            k = 0.4 if dark else 1.0
            for y in range(half):                       # teto
                f = y / half
                c = (int((3 + 10 * f) * k), int((4 + 16 * f) * k), int((14 + 40 * f) * k))
                pygame.draw.line(s, c, (0, y), (self.IW, y))
            for y in range(half, self.IH):              # chão
                f = (y - half) / half
                c = (int((6 + 26 * f) * k), int((8 + 30 * f) * k), int((22 + 62 * f) * k))
                pygame.draw.line(s, c, (0, y), (self.IW, y))
            self.bg_cache[dark] = s
        return s

    def columns(self, key, tex, side, level):
        ck = (key, side, level)
        cols = self.shade_cache.get(ck)
        if cols is None:
            k = (1.0 - level / self.N_SHADE) * (1.0 if side == 0 else 0.72)
            k = max(0.05, k)
            surf = pygame.Surface((32, 32))
            surf.fill((10, 16, 40))
            surf.blit(tex, (0, 0))
            surf.fill((int(255 * k * 0.92), int(255 * k * 0.96), int(255 * k)),
                      special_flags=pygame.BLEND_RGB_MULT)
            cols = [surf.subsurface((i, 0, 1, 32)) for i in range(32)]
            self.shade_cache[ck] = cols
        return cols

    def scaled_sprite(self, img, size):
        key = (id(img), size)
        s = self.size_cache.get(key)
        if s is None:
            if len(self.size_cache) > 700:
                self.size_cache.clear()
            s = pygame.transform.scale(img, (size, size))
            self.size_cache[key] = s
        return s

    # ---------- desenho principal ----------
    def render(self, g, target):
        a, T = self.a, self.tile
        IW, IH, RW, n = self.IW, self.IH, self.RW, self.n_rays
        view, zbuf = self.view, self.zbuf
        p = g.player
        px, py = (p.x + T / 2) / T, (p.y + T / 2) / T
        ang = getattr(p, "angle", 0.0)
        dx, dy = math.cos(ang), math.sin(ang)
        rxv, ryv = -dy, dx                              # vetor "direita" da câmera
        fov = self.fov + (10 if g.boost_t > 0 else 0)   # aceleração: campo de visão abre
        tt = math.tan(math.radians(fov / 2))
        blackout = g.blackout
        fog = float(g.diff["blackout_r"]) if blackout else 13.0
        view.blit(self.background(blackout), (0, 0))

        grid, has_key = g.grid, g.has_key
        rows, cols_n = len(grid), len(grid[0])
        tiles = a["WALL_TILES"][(g.level - 1) % len(a["WALL_TILES"])]
        wall_tex = tiles["face"]
        style = (g.level - 1) % len(a["WALL_TILES"])
        N = self.N_SHADE
        scale = pygame.transform.scale

        # ---- paredes (DDA) ----
        for i in range(n):
            cam = 2.0 * (i + 0.5) / n - 1.0
            rdx = dx + rxv * tt * cam
            rdy = dy + ryv * tt * cam
            mx, my = int(px), int(py)
            ddx = abs(1.0 / rdx) if rdx else 1e30
            ddy = abs(1.0 / rdy) if rdy else 1e30
            if rdx < 0:
                sx, sdx = -1, (px - mx) * ddx
            else:
                sx, sdx = 1, (mx + 1.0 - px) * ddx
            if rdy < 0:
                sy, sdy = -1, (py - my) * ddy
            else:
                sy, sdy = 1, (my + 1.0 - py) * ddy
            side, kind = 0, 1
            for _ in range(70):
                if sdx < sdy:
                    sdx += ddx
                    mx += sx
                    side = 0
                else:
                    sdy += ddy
                    my += sy
                    side = 1
                if mx < 0 or my < 0 or mx >= cols_n or my >= rows:
                    kind = 1
                    break
                ch = grid[my][mx]
                if ch == '#':
                    kind = 1
                    break
                if ch == 'D' and not has_key:
                    kind = 2
                    break
            else:
                zbuf[i] = 1e9
                continue
            perp = (sdx - ddx) if side == 0 else (sdy - ddy)
            if perp < 0.02:
                perp = 0.02
            zbuf[i] = perp
            wx = (py + perp * rdy) if side == 0 else (px + perp * rdx)
            wx -= math.floor(wx)
            tx = int(wx * 32)
            if (side == 0 and rdx > 0) or (side == 1 and rdy < 0):
                tx = 31 - tx
            lvl = min(N - 1, int(perp / fog * N))
            col = self.columns(("door", 0) if kind == 2 else ("wall", style),
                               self.door_tex if kind == 2 else wall_tex, side, lvl)[tx]
            lh = int(IH / perp)
            if lh <= IH:
                lh = max(1, lh)
                view.blit(scale(col, (RW, lh)), (i * RW, (IH - lh) // 2))
            else:
                sh = max(1, int(32 * IH / lh))
                sub = col.subsurface((0, (32 - sh) // 2, 1, sh))
                view.blit(scale(sub, (RW, IH)), (i * RW, 0))

        # ---- sprites ----
        items = []
        anim = g.anim
        t = anim / 60.0

        def add(img, wx_, wy_, scl, z, extra=None, far=False):
            rx, ry = wx_ - px, wy_ - py
            depth = rx * dx + ry * dy
            if depth < 0.35 or (depth > fog + 1.5 and not far):
                return
            items.append((depth, rx, ry, img, scl, z, extra))

        for (x, y) in g.dots:
            if abs(x + 0.5 - px) < 12 and abs(y + 0.5 - py) < 12:
                add(a["DOT"], x + 0.5, y + 0.5, 0.26, 0.10 + 0.02 * math.sin(t * 3 + x))
        if not g.has_key:
            x, y = g.key_pos
            add(a["KEY"], x + 0.5, y + 0.5, 0.5, 0.42 + 0.06 * math.sin(t * 3))
        if not g.has_note:
            x, y = g.note_pos
            add(a["NOTE"], x + 0.5, y + 0.5, 0.45, 0.30 + 0.04 * math.sin(t * 2.5 + 1))
        x, y = g.console_pos
        add(a["CONSOLE_ON"] if g.console_open else a["CONSOLE"], x + 0.5, y + 0.5, 0.7, 0.38)
        x, y = g.exit_pos
        add(a["EXIT_OPEN"] if g.exit_open else a["EXIT_LOCKED"], x + 0.5, y + 0.5, 1.0, 0.5, far=True)
        if g.heal_pos != (-99, -99):
            x, y = g.heal_pos
            add(a["HEAL"], x + 0.5, y + 0.5, 0.5, 0.32 + 0.05 * math.sin(t * 3))
        for pk in g.pickups:
            x, y = pk["pos"]
            img = a["item_imgs"].get(pk["kind"]) or a["ORB_FRAMES"][(anim // 8) % 4]
            add(img, x + 0.5, y + 0.5, 0.5, 0.36 + 0.05 * math.sin(t * 3 + x))
        for d in g.drones:
            eye = d.EYE[d.state]
            if d.state == "NOTICE" and (d.pulse // 4) % 2:
                eye = RED
            if d.stun > 0:
                eye = WHITE if (anim // 5) % 2 else (120, 150, 255)
            frames = a["drone_frames"](d.color, eye)
            img = frames[(anim // 7 + d.anim_off) % 4] if d.stun <= 0 else frames[0]
            mark = {"NOTICE": ("!", WHITE), "CHASE": ("!", RED),
                    "INVESTIGATE": ("?", GOLD), "SEARCH": ("?", GOLD)}.get(d.state)
            if d.stun > 0:
                mark = ("zZ", (150, 190, 255))
            add(img, (d.x + T / 2) / T, (d.y + T / 2) / T, 0.8,
                0.55 + 0.04 * math.sin(t * 4 + d.anim_off), extra=("drone", eye, mark), far=True)

        items.sort(key=lambda it: -it[0])
        small = a["small_font"]
        for depth, rx, ry, img, scl, z, extra in items:
            lat = rx * rxv + ry * ryv
            sxp = IW / 2 * (1 + lat / (depth * tt))
            unit = IH / depth
            size = int(unit * scl)
            yc = IH / 2 + unit * (0.5 - z)
            ci = int(sxp) // RW
            center_visible = 0 <= ci < n and zbuf[ci] > depth
            if blackout and extra is not None and depth > fog:
                if center_visible:                      # no escuro só se vêem os olhos
                    r = max(2, int(unit * 0.05))
                    pygame.draw.circle(view, extra[1], (int(sxp), int(yc)), r)
                continue
            if size < 2:
                continue
            size = min(size, IH * 2)
            x0, y0 = int(sxp - size / 2), int(yc - size / 2)
            x1 = x0 + size
            if x1 < 0 or x0 >= IW:
                continue
            spr = self.scaled_sprite(img, size)
            alpha = 255
            if depth > fog * 0.65:
                alpha = int(255 * max(0.0, (fog - depth) / (fog * 0.35)))
                if alpha <= 8:
                    continue
            spr.set_alpha(alpha)
            r0, r1 = max(0, x0) // RW, (min(IW, x1) - 1) // RW
            run = None
            for r in range(r0, r1 + 2):
                vis = r <= r1 and zbuf[r] > depth
                if vis and run is None:
                    run = r
                elif not vis and run is not None:
                    ax0, ax1 = max(x0, run * RW), min(x1, r * RW)
                    if ax1 > ax0:
                        view.blit(spr, (ax0, y0), pygame.Rect(ax0 - x0, 0, ax1 - ax0, size))
                    run = None
            if extra is not None and center_visible and extra[2]:
                label = small.render(extra[2][0], True, extra[2][1])
                view.blit(label, (int(sxp) - label.get_width() // 2, y0 - label.get_height()))

        # ---- partículas (projetadas no mundo 3D) ----
        for q in g.particles.items:
            wx_, wy_ = q[0] / T, q[1] / T
            rx, ry = wx_ - px, wy_ - py
            depth = rx * dx + ry * dy
            if depth < 0.3:
                continue
            lat = rx * rxv + ry * ryv
            sxp = int(IW / 2 * (1 + lat / (depth * tt)))
            ci = sxp // RW
            if not (0 <= ci < n) or zbuf[ci] <= depth:
                continue
            unit = IH / depth
            s = max(1, int(q[7] * (q[4] / q[5]) / T * unit * 1.2))
            pygame.draw.rect(view, q[6], (sxp - s // 2, int(IH / 2 - s / 2), s, s))

        # ---- para a tela ----
        target.blit(scale(view, target.get_size()), (0, 0))
        if g.shield_t > 0 and (g.shield_t > 120 or (g.shield_t // 6) % 2 == 0):
            if self.shield_vig is None or self.shield_vig.get_size() != target.get_size():
                w, h = target.get_size()
                v = pygame.Surface((w, h), pygame.SRCALPHA)
                for k in range(40):
                    al = int(150 * (1 - k / 40.0) ** 2)
                    pygame.draw.rect(v, (90, 210, 255, al), (k, k, w - 2 * k, h - 2 * k), 1)
                self.shield_vig = v
            target.blit(self.shield_vig, (0, 0))
        self.minimap(g, target)

    # ---------- minimapa ----------
    def minimap(self, g, target):
        if not getattr(g, "show_map", True):
            return
        ms = 5
        grid = g.grid
        rows, cols = len(grid), len(grid[0])
        w, h = cols * ms, rows * ms
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        surf.fill((0, 0, 8, 150))
        ex = g.explored
        for (x, y) in ex:
            if 0 <= x < cols and 0 <= y < rows:
                ch = grid[y][x]
                if ch == '#':
                    c = (50, 90, 200, 230)
                elif ch == 'D' and not g.has_key:
                    c = (220, 70, 80, 255)
                else:
                    c = (24, 34, 80, 230)
                pygame.draw.rect(surf, c, (x * ms, y * ms, ms, ms))

        def dot(tile, color, r=2):
            pygame.draw.circle(surf, color, (tile[0] * ms + ms // 2, tile[1] * ms + ms // 2), r)

        if not g.has_key and g.key_pos in ex:
            dot(g.key_pos, GOLD)
        if not g.has_note and g.note_pos in ex:
            dot(g.note_pos, WHITE, 1)
        if g.console_pos in ex:
            dot(g.console_pos, GREEN if g.console_open else CYAN)
        if g.exit_pos in ex:
            dot(g.exit_pos, GREEN if g.exit_open else RED)
        if g.diff["arrow"] and (g.anim // 20) % 2 == 0:       # modo fácil: pisca o objetivo
            dot(g.current_objective(), GOLD, 3)
        if g.debug_ai:
            for d in g.drones:
                dot(d.current_tile(), d.color)
        T = self.tile
        ang = getattr(g.player, "angle", 0.0)
        cx, cy = (g.player.x + T / 2) / T * ms, (g.player.y + T / 2) / T * ms
        ca, sa = math.cos(ang), math.sin(ang)
        pts = [(cx + ca * 5, cy + sa * 5),
               (cx - ca * 3 - sa * 3, cy - sa * 3 + ca * 3),
               (cx - ca * 3 + sa * 3, cy - sa * 3 - ca * 3)]
        pygame.draw.polygon(surf, (255, 220, 40), pts)
        x0 = target.get_width() - w - 10
        target.blit(surf, (x0, 38))
        pygame.draw.rect(target, (60, 190, 255), (x0 - 1, 37, w + 2, h + 2), 1)
