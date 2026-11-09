"""
Testes automáticos do jogo (rodam sem abrir janela nem tocar som).

Como usar, na pasta do jogo:
    python test_jogo.py          (ou:  python -m unittest test_jogo -v)

Eles geram dezenas de fases, conferem que dá para vencer todas (chave, bilhete, itens,
console e saída alcançáveis), simulam centenas de quadros com todas as dificuldades,
fases de apagão/chefe e itens, e testam teclas, conquistas e opções.
"""
import importlib.util
import os
import sys
import tempfile
import types
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["MANSAO_DATA_DIR"] = tempfile.mkdtemp(prefix="mansao_teste_")   # não mexe nos seus saves

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
GAME_FILE = os.environ.get("MANSAO_GAME_FILE", "Teste_6_melhorado.py")
_spec = importlib.util.spec_from_file_location("jogo", os.path.join(HERE, GAME_FILE))
jogo = importlib.util.module_from_spec(_spec)
sys.modules["jogo"] = jogo
_spec.loader.exec_module(jogo)
pygame = jogo.pygame


class FakeKeys:
    def __init__(self, pressed=()):
        self.pressed = set(pressed)

    def __getitem__(self, key):
        return key in self.pressed


def ev(key):
    return types.SimpleNamespace(type=pygame.KEYDOWN, key=key, unicode="")


def new_game(level=1, diff=1):
    jogo.SETTINGS["difficulty"] = diff
    g = jogo.Game()
    g.level = level
    g.reset()
    return g


class TestFases(unittest.TestCase):
    LEVELS = list(range(1, 41)) + [60, 100, 200]

    def test_todas_as_fases_sao_vencíveis(self):
        for level in self.LEVELS:
            with self.subTest(level=level):
                g = new_game(level)
                self.assertEqual(len(g.grid), jogo.ROWS)
                self.assertTrue(all(len(r) == jogo.COLS for r in g.grid))
                g.has_key = False
                reach = jogo.Nav.flood(g, g.spawn_tile)
                self.assertIn(g.key_pos, reach, "chave inalcançável")
                self.assertIn(g.note_pos, reach, "bilhete inalcançável")
                for p in g.pickups:
                    self.assertIn(p["pos"], reach, f"item {p['kind']} inalcançável")
                g.has_key = True
                reach = jogo.Nav.flood(g, g.spawn_tile)
                self.assertIn(g.console_pos, reach, "console inalcançável")
                self.assertIn(g.exit_pos, reach, "saída inalcançável")

    def test_fases_especiais(self):
        self.assertEqual([l for l in range(1, 21) if jogo.is_blackout_level(l)], [3, 7, 11, 15, 19])
        self.assertEqual([l for l in range(1, 21) if jogo.is_boss_level(l)], [5, 10, 15, 20])

    def test_drones_por_fase(self):
        for level in (1, 3, 5, 6, 8, 10, 15):
            with self.subTest(level=level):
                g = new_game(level)
                roles = [d.role for d in g.drones]
                self.assertIn("hunter", roles)
                self.assertEqual("scout" in roles, level >= 3)
                self.assertEqual("phantom" in roles, level >= 6)
                self.assertEqual("sentinel" in roles, level >= 8)
                self.assertEqual(sum(d.boss for d in g.drones), 1 if jogo.is_boss_level(level) else 0)
                reach = jogo.Nav.flood(g, g.spawn_tile)
                for d in g.drones:
                    self.assertIn(d.current_tile(), reach)


class TestIA(unittest.TestCase):
    def test_velocidade_cresce_com_a_fase(self):
        speeds = [jogo.ai_profile(l)["speed"] for l in range(1, 30)]
        self.assertEqual(speeds, sorted(speeds))

    def test_dificuldades_em_ordem(self):
        f, n, d = (jogo.ai_profile(5, x) for x in jogo.DIFFICULTIES)
        self.assertLess(f["speed"], n["speed"])
        self.assertLess(n["speed"], d["speed"])
        self.assertLessEqual(f["vision"], n["vision"])
        self.assertLessEqual(n["vision"], d["vision"])
        self.assertGreaterEqual(f["react"], n["react"])
        self.assertGreaterEqual(n["react"], d["react"])


class TestSimulacao(unittest.TestCase):
    def rodar(self, g, frames=400, draw_every=25):
        dirs = [(1, 0), (0, 1), (-1, 0), (0, -1)]
        for i in range(frames):
            if i % 20 == 0:
                g.player.next_direction = dirs[(i // 20) % 4]
                g.player.buffer = jogo.INPUT_BUFFER
            g.update()
            if i % draw_every == 0:
                g.draw()
            self.assertTrue(0 <= g.player.lives <= 3)

    def test_todas_as_dificuldades_e_fases_especiais(self):
        for diff in range(len(jogo.DIFFICULTIES)):
            for level in (1, 3, 5, 6, 8, 10):
                with self.subTest(diff=diff, level=level):
                    g = new_game(level, diff)
                    g.pulse_charges = 2
                    g.fire_pulse()
                    self.rodar(g)
        jogo.SETTINGS["difficulty"] = 1

    def test_respawn_seguro(self):
        g = new_game(3, 1)
        for d in g.drones:
            d.delay = 999
        reach = list(jogo.Nav.flood(g, g.spawn_tile))
        far = max(reach, key=lambda t: jogo.Nav.manhattan(t, g.spawn_tile))
        g.checkpoints.append(far)
        self.assertEqual(g.respawn_tile(), far)
        g.diff = jogo.DIFFICULTIES[2]            # difícil: sempre volta ao início
        self.assertEqual(g.respawn_tile(), g.spawn_tile)
        g.diff = jogo.DIFFICULTIES[1]
        g.drones[0].delay = 0                    # drone em cima do checkpoint: não vale
        g.drones[0].x, g.drones[0].y = far[0] * jogo.TILE, far[1] * jogo.TILE
        self.assertEqual(g.respawn_tile(), g.spawn_tile)

    def test_buffer_de_direcao_expira(self):
        g = new_game(1)
        original = pygame.key.get_pressed
        try:
            pygame.key.get_pressed = lambda: FakeKeys({pygame.K_RIGHT})
            g.update()
            self.assertEqual(g.player.next_direction, (1, 0))
            self.assertEqual(g.player.buffer, jogo.INPUT_BUFFER)
            pygame.key.get_pressed = lambda: FakeKeys()
            for _ in range(jogo.INPUT_BUFFER):
                g.update()
            self.assertEqual(g.player.next_direction, (0, 0))
        finally:
            pygame.key.get_pressed = original

    def test_itens_novos(self):
        g = new_game(4)
        for d in g.drones:
            d.delay = 0
            d.stun = 0
        g.pickups.append({"kind": "freeze", "pos": (1, 1)})
        g.collect_pickup(g.pickups[-1])
        self.assertTrue(all(d.stun > 0 for d in g.drones))
        g.pickups.append({"kind": "silence", "pos": (1, 1)})
        g.collect_pickup(g.pickups[-1])
        self.assertGreater(g.silent_t, 0)
        for d in g.drones:
            d.state, d.goal = "PATROL", None
        g.director.report_noise(g, g.spawn_tile, 99)       # silêncio: ninguém investiga
        self.assertTrue(all(d.state == "PATROL" for d in g.drones))
        g.silent_t = 0
        for d in g.drones:
            d.stun = 0
        g.director.report_noise(g, g.spawn_tile, 99)
        self.assertTrue(any(d.state == "INVESTIGATE" for d in g.drones))

    def test_chefe_resiste_ao_pulso(self):
        g = new_game(5)
        boss = next(d for d in g.drones if d.boss)
        normal = next(d for d in g.drones if not d.boss)
        for d in (boss, normal):
            d.delay = 0
            d.x, d.y = g.player.x, g.player.y
        g.pulse_charges = 1
        g.fire_pulse()
        self.assertEqual(normal.stun, jogo.PULSE_STUN)
        self.assertEqual(boss.stun, jogo.PULSE_STUN // 2)

    def test_fantasma_teleporta(self):
        g = new_game(6)
        ph = next(d for d in g.drones if d.role == "phantom")
        ph.delay, ph.state, ph.blink_t = 0, "PATROL", 1
        before = ph.current_tile()
        ph.blink(g, g.director)
        self.assertNotEqual(ph.current_tile(), before)

    def test_vitoria_da_bonus_e_conquistas(self):
        g = new_game(1)
        g.level_chased, g.level_catches, g.level_frames = False, 0, 10 * jogo.FPS
        score = g.score
        g.on_level_complete()
        self.assertEqual(g.win_bonus, ((90 - 10) * 3, 200))
        self.assertEqual(g.score, score + 80 * 3 + 200)


class TestConquistas(unittest.TestCase):
    def test_desbloqueio_e_arquivo(self):
        jogo.ACH_FILE = os.path.join(os.environ["MANSAO_DATA_DIR"], "ach_teste.json")
        a = jogo.Achievements()
        self.assertTrue(a.unlock("fase5"))
        self.assertFalse(a.unlock("fase5"))
        self.assertFalse(a.unlock("nao_existe"))
        self.assertEqual(jogo.Achievements().unlocked, {"fase5"})


class TestOpcoes(unittest.TestCase):
    def tearDown(self):
        for a, k in jogo.DEFAULT_KEYS.items():
            jogo.KEYMAP[a] = list(k)

    def test_remapear_tecla(self):
        s = jogo.SettingsScreen()
        s.show()
        s.page, s.idx = "keys", [a for a, _ in jogo.ACTIONS].index("pulse")
        s.handle(ev(pygame.K_RETURN))
        self.assertTrue(s.capture)
        s.handle(ev(pygame.K_ESCAPE))                      # cancelar não altera nada
        self.assertEqual(jogo.KEYMAP["pulse"], [pygame.K_SPACE])
        s.handle(ev(pygame.K_RETURN))
        s.handle(ev(pygame.K_F5))                          # reservada: recusa
        self.assertTrue(s.capture)
        s.handle(ev(pygame.K_z))
        self.assertEqual(jogo.KEYMAP["pulse"], [pygame.K_z])
        self.assertTrue(jogo.key_is(pygame.K_z, "pulse"))
        s.idx = len(jogo.ACTIONS)                          # "Restaurar padrão"
        s.handle(ev(pygame.K_RETURN))
        self.assertEqual(jogo.KEYMAP["pulse"], [pygame.K_SPACE])

    def test_dificuldade_e_volume(self):
        s = jogo.SettingsScreen()
        s.show()
        jogo.SETTINGS["difficulty"], jogo.SETTINGS["music"] = 1, 0.5
        s.idx = 0
        s.handle(ev(pygame.K_RIGHT))
        self.assertEqual(jogo.SETTINGS["difficulty"], 2)
        s.handle(ev(pygame.K_RIGHT))
        self.assertEqual(jogo.SETTINGS["difficulty"], 0)
        s.idx = 1
        s.handle(ev(pygame.K_RIGHT))
        self.assertEqual(jogo.SETTINGS["music"], 0.6)
        jogo.SETTINGS["difficulty"], jogo.SETTINGS["music"] = 1, 1.0

    def test_config_salva_e_carrega(self):
        jogo.SETTINGS["difficulty"] = 2
        jogo.KEYMAP["pause"] = [pygame.K_o + 1]
        jogo.save_settings()
        loaded = jogo.load_settings()
        self.assertEqual(loaded["difficulty"], 2)
        self.assertEqual(loaded["keys"]["pause"], [pygame.K_o + 1])
        jogo.SETTINGS["difficulty"] = 1


class TestEfeitos(unittest.TestCase):
    def test_fx_desenha_em_todas_as_fases_especiais(self):
        import fx as FXMOD
        for level in (1, 3, 5, 6):
            with self.subTest(level=level):
                g = new_game(level)
                for i in range(90):
                    g.player.next_direction = (1, 0)
                    g.player.buffer = jogo.INPUT_BUFFER
                    g.update()
                    g.draw()
                FXMOD.toggle()
                g.draw()
                FXMOD.toggle()

    def test_assets_de_terceiros_tem_fallback(self):
        import asset_loader as AL
        self.assertIsNone(AL.external_image("nao_existe_xyz"))
        self.assertEqual(len(AL.split_strip(jogo.DRONE_STRIP, 4)), 4)
        self.assertEqual(AL.fit(jogo.PILOT_IMG, 24).get_width(), 24)


class TestAudio(unittest.TestCase):
    def test_cache_de_sons(self):
        if not jogo.SFX:
            self.skipTest("sem áudio neste computador")
        files = os.listdir(jogo.AUDIO_DIR)
        self.assertTrue(any(f.startswith("sfx_") for f in files))


if __name__ == "__main__":
    unittest.main(verbosity=2)
