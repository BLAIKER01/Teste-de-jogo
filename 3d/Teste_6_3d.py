import math
import random
import json
import os
import sys
import glob
import subprocess
import heapq
import io
import base64
import array
import threading
import time
import wave
import zlib
from collections import deque

from assets_b64 import *   # imagens em base64 (arquivo assets_b64.py, na mesma pasta)
from mapas import RAW_MAPS  # mapas das primeiras fases (arquivo mapas.py)

# Se o VS Code usar Python 3.15 sem Pygame, tenta abrir com Python 3.13.
try:
    import pygame
except ModuleNotFoundError:
    appdata = os.environ.get("APPDATA", "")
    localappdata = os.environ.get("LOCALAPPDATA", "")
    candidatos = [
        os.path.join(appdata, "uv", "python", "cpython-3.13.0-windows-x86_64-none", "python.exe"),
        os.path.join(localappdata, "Programs", "Python", "Python313", "python.exe"),
        os.path.join(localappdata, "Programs", "Python", "Python3.13", "python.exe"),
    ]
    candidatos.extend(glob.glob(os.path.join(appdata, "uv", "python", "cpython-3.13*", "python.exe")))
    atual = os.path.normcase(os.path.abspath(sys.executable))
    for interpretador in candidatos:
        if os.path.isfile(interpretador) and os.path.normcase(os.path.abspath(interpretador)) != atual:
            teste = subprocess.run([interpretador, "-c", "import pygame"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if teste.returncode == 0:
                # subprocess cuida das aspas (execv quebrava caminhos com espaços no Windows).
                raise SystemExit(subprocess.call([interpretador, os.path.abspath(__file__), *sys.argv[1:]]))
    raise SystemExit(
        "\nPygame não está instalado. Instale com:  pip install pygame\n\nNão encontrei um Python 3.13 com Pygame instalado.\n"
        "No VS Code, pressione Ctrl+Shift+P > Python: Select Interpreter e escolha "
        "o Python 3.13 que tem Pygame. Depois clique em Executar novamente."
    )

# ============================================================
# MANSÃO: FUGA SOMBRIA — Escape room com labirinto, drones de segurança e FASES INFINITAS
# Controles: WASD/setas mover, E interagir, ESPAÇO pulso, P pausa, R reiniciar,
#            M som, F5/F6 volume da música, F7/F8 volume dos efeitos, F11 janela/tela cheia, Esc menu
#            No menu: setas / A / D / TAB mudam a dificuldade
# Linha de comando:  --janela  ou  --tela-cheia  (força o modo e grava a escolha)
# ============================================================

import render3d   # renderizador 3D (render3d.py); vem depois do import do pygame acima

try:
    pygame.mixer.pre_init(22050, -16, 2, 512)   # estéreo 16 bits, pouca latência
except pygame.error:
    pass
pygame.init()
pygame.font.init()

TILE = 32
COLS, ROWS = 37, 21
SCREEN_W, SCREEN_H = COLS * TILE, ROWS * TILE
HUD_H = 0  # sem barra superior: o mapa ocupa a tela toda
FPS = 60

# ------------------------------------------------------------
# MODO DE TELA: janela (padrão) ou tela cheia. A escolha é lembrada em config.json.
# F11 alterna durante o jogo; --janela / --tela-cheia forçam o modo ao abrir.
# ------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _data_dir():
    """Onde ficam config, placar, conquistas, memória da IA e cache de áudio.
    Rodando o .py: ao lado do script. Empacotado (.exe): pasta do usuário.
    MANSAO_DATA_DIR força outra pasta (usado nos testes)."""
    forced = os.environ.get("MANSAO_DATA_DIR")
    if forced:
        path = forced
    elif getattr(sys, "frozen", False):
        root = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
        path = os.path.join(root, "MansaoFugaSombria")
    else:
        path = BASE_DIR
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        path = BASE_DIR
    return path


DATA_DIR = _data_dir()
SETTINGS_FILE = os.path.join(DATA_DIR, "config.json")


# Dificuldades (escolha no menu; fica salva em config.json).
#   speed ........ multiplica a velocidade dos drones
#   vision ....... soma/subtrai tiles do alcance de visão
#   react ........ multiplica o tempo de hesitação dos drones ao te ver (maior = mais fácil)
#   safe_respawn . ao ser pego, volta ao último ponto seguro (senão, ao início da fase)
#   arrow ........ mostra uma seta apontando o próximo passo até o objetivo
#   blackout_r ... raio de luz (em tiles) nas fases de apagão
DIFFICULTIES = [
    {"name": "FÁCIL",   "speed": 0.86, "vision": -1, "react": 1.35, "safe_respawn": True,  "arrow": True,  "blackout_r": 8.5},
    {"name": "NORMAL",  "speed": 1.00, "vision": 0,  "react": 1.00, "safe_respawn": True,  "arrow": False, "blackout_r": 7.0},
    {"name": "DIFÍCIL", "speed": 1.08, "vision": 1,  "react": 0.80, "safe_respawn": False, "arrow": False, "blackout_r": 5.5},
]


# Teclas do jogo (configuráveis em Opções > Configurar teclas). Cada ação aceita 1 ou mais teclas.
ACTIONS = [("up", "Cima"), ("down", "Baixo"), ("left", "Esquerda"), ("right", "Direita"),
           ("interact", "Interagir"), ("pulse", "Pulso"), ("pause", "Pausar")]
DEFAULT_KEYS = {
    "up": [pygame.K_UP, pygame.K_w], "down": [pygame.K_DOWN, pygame.K_s],
    "left": [pygame.K_LEFT, pygame.K_a], "right": [pygame.K_RIGHT, pygame.K_d],
    "interact": [pygame.K_e], "pulse": [pygame.K_SPACE], "pause": [pygame.K_p],
}
# Teclas que o jogo usa para outras coisas e não podem ser atribuídas a uma ação.
RESERVED_KEYS = ({pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_TAB,
                  pygame.K_m, pygame.K_r, pygame.K_n, pygame.K_o}
                 | {getattr(pygame, f"K_F{i}") for i in range(1, 13)})


def load_settings():
    base = {"fullscreen": False, "difficulty": 1, "music": 1.0, "sfx": 1.0,
            "keys": {a: list(k) for a, k in DEFAULT_KEYS.items()}}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        base["fullscreen"] = bool(raw.get("fullscreen", False))
        base["difficulty"] = max(0, min(len(DIFFICULTIES) - 1, int(raw.get("difficulty", 1))))
        base["music"] = max(0.0, min(1.0, float(raw.get("music", 1.0))))
        base["sfx"] = max(0.0, min(1.0, float(raw.get("sfx", 1.0))))
        raw_keys = raw.get("keys", {})
        for action in DEFAULT_KEYS:
            v = raw_keys.get(action)
            if isinstance(v, list) and v and all(isinstance(x, int) for x in v):
                base["keys"][action] = v[:3]
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return base


def save_settings():
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({"fullscreen": bool(FULLSCREEN), "difficulty": SETTINGS["difficulty"],
                       "music": SETTINGS["music"], "sfx": SETTINGS["sfx"],
                       "keys": SETTINGS["keys"]}, f)
    except OSError:
        pass


SETTINGS = load_settings()
if "--tela-cheia" in sys.argv:
    SETTINGS["fullscreen"] = True
elif "--janela" in sys.argv:
    SETTINGS["fullscreen"] = False
FULLSCREEN = SETTINGS["fullscreen"]


def current_difficulty():
    return DIFFICULTIES[SETTINGS["difficulty"]]


KEYMAP = SETTINGS["keys"]          # ação -> lista de teclas (mesmo dicionário salvo em config.json)
START_LEVEL = 1                    # --fase N começa direto na fase N (para testar)
for _i, _a in enumerate(sys.argv):
    if _a == "--fase" and _i + 1 < len(sys.argv) and sys.argv[_i + 1].isdigit():
        START_LEVEL = max(1, int(sys.argv[_i + 1]))


def key_held(keys, action):
    """True se alguma tecla da ação está pressionada (keys = pygame.key.get_pressed())."""
    return any(keys[k] for k in KEYMAP[action])


def key_is(event_key, action):
    return event_key in KEYMAP[action]


def key_label(action):
    return pygame.key.name(KEYMAP[action][0]).upper()


def create_window(fullscreen):
    """Abre a janela (ou tela cheia) escalando a imagem mantendo a proporção."""
    base = pygame.FULLSCREEN if fullscreen else pygame.RESIZABLE
    try:
        surf = pygame.display.set_mode((SCREEN_W, SCREEN_H), base | pygame.SCALED)
    except pygame.error:
        surf = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.FULLSCREEN if fullscreen else 0)
    pygame.mouse.set_visible(not fullscreen)     # cursor só aparece em janela
    return surf


def toggle_fullscreen():
    """F11: alterna janela <-> tela cheia e grava a preferência."""
    global screen, FULLSCREEN
    target = not FULLSCREEN
    try:
        ok = pygame.display.toggle_fullscreen()
    except pygame.error:
        ok = 0
    if not ok:                                   # alguns drivers falham: recria a janela
        screen = create_window(target)
    else:
        pygame.mouse.set_visible(not target)
    if hasattr(pygame.display, "is_fullscreen"):
        try:
            target = bool(pygame.display.is_fullscreen())
        except pygame.error:
            pass
    FULLSCREEN = target
    save_settings()


screen = create_window(FULLSCREEN)
pygame.display.set_caption("Mansão: Fuga Sombria 3D")
clock = pygame.time.Clock()

BLACK = (8, 10, 24)
NAVY = (12, 20, 54)
WALL = (35, 70, 210)
WALL_EDGE = (60, 190, 255)
YELLOW = (255, 220, 40)
WHITE = (245, 248, 255)
GOLD = (255, 180, 45)
RED = (255, 65, 80)
PINK = (255, 105, 190)
CYAN = (50, 235, 235)
ORANGE = (255, 155, 45)
GREEN = (70, 235, 125)
PURPLE = (175, 100, 255)
GREY = (100, 115, 150)
PHANTOM_COLOR = (130, 150, 255)   # drone fantasma (teleporta)

font = pygame.font.Font(None, 25)
small_font = pygame.font.Font(None, 20)
title_font = pygame.font.Font(None, 56)
big_font = pygame.font.Font(None, 38)


# ============================================================
# SONS — sintetizados em código (nenhum arquivo de áudio necessário).
# M liga/desliga o som. Se o computador não tiver áudio, o jogo roda mudo.
# ============================================================
SAMPLE_RATE = 22050
AUDIO_DIR = os.path.join(DATA_DIR, "audio_cache")   # sons/música são gerados 1x e guardados aqui
MUSIC_VERSION = "v1"                              # mude se alterar a música (invalida o cache)
SOUND_ON = True
SFX = {}
_last_play = {}
EAT_SCALE = [523, 587, 659, 784, 880, 1046, 1175, 1319]   # C5 D5 E5 G5 A5 C6 D6 E6
EAT_PATTERN = [0, 1, 2, 3, 4, 5, 6, 7, 6, 5, 4, 3, 2, 1]


def synth_data(notes, vol=0.35, wave="square"):
    """notes: lista de (freq_inicial, freq_final, duração_s[, onda]); freq 0 = pausa."""
    info = pygame.mixer.get_init()
    stereo = bool(info) and info[2] == 2
    data = array.array("h")
    phase = 0.0
    rnd = random.Random(7)
    for note in notes:
        f0, f1, dur = note[:3]
        w = note[3] if len(note) > 3 else wave
        n = max(1, int(SAMPLE_RATE * dur))
        for i in range(n):
            t = i / n
            if f0 <= 0:
                v = 0
            else:
                phase += (f0 + (f1 - f0) * t) / SAMPLE_RATE
                ph = phase % 1.0
                if w == "square":
                    s = 1.0 if ph < 0.5 else -1.0
                elif w == "tri":
                    s = 4.0 * abs(ph - 0.5) - 1.0
                elif w == "saw":
                    s = 2.0 * ph - 1.0
                elif w == "bell":     # timbre de sino/marimba: fundamental + harmônicos
                    s = (math.sin(2 * math.pi * ph) + 0.4 * math.sin(4 * math.pi * ph)
                         + 0.15 * math.sin(6 * math.pi * ph)) / 1.4
                elif w == "noise":
                    s = rnd.uniform(-1, 1)
                else:
                    s = math.sin(2 * math.pi * ph)
                env = min(1.0, i / (0.004 * SAMPLE_RATE)) * (1.0 - t) ** (2.2 if w == "bell" else 0.6)
                v = int(32767 * vol * s * env)
            data.append(v)
            if stereo:
                data.append(v)
    return data


def _cached_sound(key, make_data):
    """Carrega o som do cache (WAV). Se não existir, gera, grava o WAV e carrega dele."""
    info = pygame.mixer.get_init()
    ch = 2 if (info and info[2] == 2) else 1
    path = os.path.join(AUDIO_DIR, f"{key}_{SAMPLE_RATE}_{ch}.wav")
    if os.path.isfile(path):
        try:
            return pygame.mixer.Sound(path)
        except (pygame.error, OSError):
            pass
    data = make_data()
    try:
        os.makedirs(AUDIO_DIR, exist_ok=True)
        pcm = array.array("h", data)
        if sys.byteorder == "big":
            pcm.byteswap()
        with wave.open(path, "wb") as w:
            w.setnchannels(ch)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm.tobytes())
        return pygame.mixer.Sound(path)
    except (OSError, wave.Error, pygame.error):
        return pygame.mixer.Sound(buffer=data.tobytes())   # sem cache: usa direto da memória


def build_sounds():
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init(SAMPLE_RATE, -16, 2, 512)
        specs = {
            "combo":       ([(1046, 1046, 0.06, "bell"), (1319, 1319, 0.06, "bell"), (1568, 1568, 0.07, "bell"),
                             (2093, 2093, 0.22, "bell")], 0.30, "bell"),
            "key":         ([(660, 660, 0.07), (880, 880, 0.07), (1320, 1320, 0.14)], 0.30, "square"),
            "alarm":       ([(900, 600, 0.16), (0, 0, 0.04)] * 3, 0.22, "saw"),
            "console_ok":  ([(523, 523, 0.08), (659, 659, 0.08), (784, 784, 0.08), (1046, 1046, 0.22)], 0.30, "square"),
            "code_bad":    ([(220, 140, 0.28)], 0.30, "saw"),
            "deny":        ([(180, 180, 0.12)], 0.25, "square"),
            "heal":        ([(523, 1046, 0.22, "tri"), (1046, 1046, 0.12, "tri")], 0.30, "tri"),
            "hit":         ([(700, 90, 0.5, "saw"), (0, 0, 0.02), (120, 40, 0.18, "noise")], 0.35, "saw"),
            "gameover":    ([(440, 440, 0.22), (370, 370, 0.22), (311, 311, 0.22), (220, 180, 0.7)], 0.32, "tri"),
            "spot":        ([(1200, 1200, 0.05), (0, 0, 0.03), (1200, 1200, 0.05)], 0.28, "square"),
            "spot_hunter": ([(330, 330, 0.08), (495, 495, 0.08), (740, 990, 0.18)], 0.34, "square"),
            "lost":        ([(520, 300, 0.22)], 0.20, "tri"),
            "beat":        ([(90, 45, 0.13)], 0.55, "sine"),
            "win":         ([(523, 523, 0.10), (659, 659, 0.10), (784, 784, 0.10), (1046, 1046, 0.32)], 0.32, "square"),
            "level":       ([(392, 392, 0.08), (523, 523, 0.08), (784, 784, 0.16)], 0.28, "tri"),
            "start":       ([(440, 440, 0.07), (880, 880, 0.18)], 0.30, "square"),
            "tick":        ([(1000, 1000, 0.03)], 0.18, "square"),
            # --- novos: bilhete, itens temporários, pulso e pausa ---
            "note":        ([(900, 900, 0.05, "noise"), (0, 0, 0.02), (1320, 1320, 0.07, "bell"),
                             (1760, 1760, 0.16, "bell")], 0.28, "bell"),
            "shield_on":   ([(440, 880, 0.10, "tri"), (880, 1320, 0.10, "tri"), (1320, 1760, 0.16, "tri")], 0.30, "tri"),
            "shield_off":  ([(700, 220, 0.25, "tri")], 0.22, "tri"),
            "shield_hit":  ([(1500, 900, 0.07, "square"), (0, 0, 0.02), (900, 600, 0.07, "square")], 0.22, "square"),
            "boost":       ([(260, 1300, 0.28, "saw")], 0.22, "saw"),
            "zap":         ([(1700, 160, 0.34, "saw"), (0, 0, 0.02), (900, 900, 0.16, "noise")], 0.32, "saw"),
            "pickup":      ([(784, 784, 0.06, "tri"), (1046, 1318, 0.12, "tri")], 0.30, "tri"),
            "pause":       ([(660, 440, 0.09, "square")], 0.22, "square"),
            "unpause":     ([(440, 660, 0.09, "square")], 0.22, "square"),
            "blink":       ([(1500, 300, 0.12, "tri"), (0, 0, 0.02), (300, 1500, 0.12, "tri")], 0.22, "tri"),
            "freeze":      ([(1800, 600, 0.22, "bell"), (0, 0, 0.02), (1200, 400, 0.28, "bell")], 0.30, "bell"),
            "silence":     ([(500, 200, 0.30, "tri")], 0.20, "tri"),
        }
        # "Comer": notas de escala pentatônica; cada ponto em sequência sobe (e depois desce)
        # a escala, formando uma melodia satisfatória enquanto você come.
        for i, hz in enumerate(EAT_SCALE):
            specs[f"eat{i}"] = ([(hz, hz, 0.13, "bell")], 0.34, "bell")
        for name, (notes, vol, wave) in specs.items():
            sig = zlib.crc32(repr((notes, vol, wave)).encode("utf-8"))
            SFX[name] = _cached_sound(f"sfx_{name}_{sig:08x}",
                                      lambda n=notes, v=vol, w=wave: synth_data(n, v, w))
    except Exception:       # sem placa de som / mixer indisponível
        SFX.clear()


def play(name, cooldown=0):
    """Toca um efeito; 'cooldown' (ms) evita repetir o mesmo som em sequência."""
    snd = SFX.get(name)
    if snd is None or not SOUND_ON:
        return
    now = pygame.time.get_ticks()
    if cooldown and now - _last_play.get(name, -99999) < cooldown:
        return
    _last_play[name] = now
    snd.set_volume(SETTINGS["sfx"])
    snd.play()


build_sounds()


# ------------------------------------------------------------
# MÚSICA DE FUNDO "melosa": lo-fi suave em loop (~15 s), também sintetizada.
# Progressão Fmaj7 → Em7 → Dm7 → Cmaj7, pad macio + arpejo + melodia + baixo + eco.
# É gerada numa thread para não atrasar a abertura do jogo.
# ------------------------------------------------------------
MUSIC_SND = None
MUSIC_CH = None
MUSIC_VOL = 0.34


def _midi(n):
    return 440.0 * 2 ** ((n - 69) / 12.0)


def render_music():
    bpm = 62.0
    beat = 60.0 / bpm
    bars = 4
    total = int(SAMPLE_RATE * beat * 4 * bars)
    buf = [0.0] * total
    two_pi = 2 * math.pi

    def note(start_beat, dur_beats, midi, amp, attack=0.04, release=0.5, harm=0.0, trem=0.0):
        f = _midi(midi)
        st = int(start_beat * beat * SAMPLE_RATE)
        n = int((dur_beats * beat + release) * SAMPLE_RATE)
        a_n = max(1, int(attack * SAMPLE_RATE))
        r_start = int(dur_beats * beat * SAMPLE_RATE)
        w = two_pi * f / SAMPLE_RATE
        for i in range(n):
            env = min(1.0, i / a_n)
            if i > r_start:
                env *= max(0.0, 1.0 - (i - r_start) / (n - r_start))
            v = math.sin(w * i)
            if harm:
                v += harm * math.sin(2 * w * i)
            if trem:
                v *= 1.0 - trem + trem * math.sin(two_pi * 0.25 * i / SAMPLE_RATE)
            buf[(st + i) % total] += v * env * amp   # índice circular: o loop emenda sem estalo
        time.sleep(0.002)    # cede a vez ao jogo (esta função roda numa thread de fundo)

    chords = [  # (baixo, [notas do acorde])
        (41, [53, 57, 60, 64]),   # Fmaj7
        (40, [52, 55, 59, 62]),   # Em7
        (38, [50, 53, 57, 60]),   # Dm7
        (36, [48, 52, 55, 59]),   # Cmaj7
    ]
    melody = [  # (compasso, tempo, duração, nota)
        (0, 0, 1.5, 81), (0, 1.5, 0.5, 79), (0, 2, 2, 76),
        (1, 0, 1.5, 79), (1, 1.5, 0.5, 76), (1, 2, 2, 74),
        (2, 0, 1, 74), (2, 1, 1, 76), (2, 2, 1, 81), (2, 3, 1, 79),
        (3, 0, 2, 76), (3, 2, 1, 74), (3, 3, 1, 72),
    ]
    for bar, (bass, tones) in enumerate(chords):
        b0 = bar * 4
        for t in tones:                                   # pad
            note(b0, 4, t, 0.10, attack=0.5, release=0.8, harm=0.18, trem=0.12)
        note(b0, 2, bass, 0.34, attack=0.03, release=0.4)  # baixo
        note(b0 + 2, 2, bass + 7, 0.24, attack=0.03, release=0.4)
        order = [0, 1, 2, 3, 2, 1, 3, 2]
        for k, idx in enumerate(order):                   # arpejo em colcheias
            note(b0 + k * 0.5, 0.5, tones[idx] + 12, 0.07, attack=0.01, release=0.35)
    for bar, tb, db, m in melody:                         # melodia
        note(bar * 4 + tb, db, m, 0.16, attack=0.05, release=0.6, harm=0.10, trem=0.18)

    # Eco suave (circular) para dar "ambiente".
    delay = int(beat * 0.75 * SAMPLE_RATE)
    echo = buf[:]
    for i in range(total):
        echo[i] += 0.32 * buf[(i - delay) % total] + 0.16 * buf[(i - 2 * delay) % total]
    peak = max(max(echo), -min(echo)) or 1.0
    scale = 0.55 * 32767 / peak
    data = array.array("h")
    width = 24                                           # leve diferença L/R = mais "largo"
    stereo = (pygame.mixer.get_init() or (0, 0, 1))[2] == 2
    for i in range(total):
        l = int(echo[i] * scale)
        data.append(l)
        if stereo:
            data.append(int(echo[(i - width) % total] * scale))
    return data


def _build_music():
    global MUSIC_SND
    try:
        MUSIC_SND = _cached_sound(f"music_{MUSIC_VERSION}", render_music)
        MUSIC_SND.set_volume(MUSIC_VOL * SETTINGS["music"])
    except Exception:
        MUSIC_SND = None


def music_tick(target_volume):
    """Chamado a cada frame: inicia o loop quando pronto e ajusta o volume suavemente."""
    global MUSIC_CH, MUSIC_VOL
    if MUSIC_SND is None or not SOUND_ON:
        return
    MUSIC_VOL += (target_volume - MUSIC_VOL) * 0.04
    MUSIC_SND.set_volume(MUSIC_VOL * SETTINGS["music"])
    if MUSIC_CH is None or not MUSIC_CH.get_busy():
        MUSIC_CH = MUSIC_SND.play(loops=-1)


if SFX:
    try:
        pygame.mixer.set_num_channels(16)
    except pygame.error:
        pass
    threading.Thread(target=_build_music, daemon=True).start()


# ============================================================
# TEXTURAS DAS PAREDES — "Pixel Sci-Fi Tileset" (reodesuxz), tiles 16x16 ampliados 2x.
# 4 estilos (azul, escuro, aço, branco) x 4 peças (top, face, cap_left, cap_right).
# O atlas está embutido abaixo, então o jogo continua sendo um único arquivo.
# Cada fase usa um estilo: fase 1 azul, 2 escuro, 3 aço, 4 branco, e repete.
# ============================================================

WALL_PARTS = ["top", "face", "cap_left", "cap_right"]

def load_wall_tiles():
    atlas = pygame.image.load(io.BytesIO(base64.b64decode(WALL_ATLAS_B64)), "walls.png").convert_alpha()
    styles = []
    for row in range(4):
        pieces = {}
        for col, name in enumerate(WALL_PARTS):
            sub = atlas.subsurface((col * 16, row * 16, 16, 16))
            pieces[name] = pygame.transform.scale(sub, (TILE, TILE))  # ampliação "nearest": pixel art nítida
        styles.append(pieces)
    return styles

WALL_TILES = load_wall_tiles()


# ============================================================
# SPRITES DA CHAVE E DO NÚCLEO DE SAÍDA
#   • Chave  -> pacote "Key" (key1.png recortado), ampliada 2x.
#   • Núcleo -> "Argon Neon Bits" (portal.png 16x16), ampliado 2x.
#               Fechado = tom vermelho, aberto = tom verde (mesma lógica de antes).
# Também embutidos em base64: o jogo continua sendo um único arquivo.
# ============================================================





def tint_sprite(src, base):
    """Recolore um sprite pela luminância (mantém alfa e brilhos brancos)."""
    out = src.copy()
    w, h = out.get_size()
    for yy in range(h):
        for xx in range(w):
            r, g, b, a = out.get_at((xx, yy))
            if a == 0:
                continue
            lum = (0.30 * r + 0.59 * g + 0.11 * b) / 255.0
            if lum > 0.9:
                col = (255, 245, 245)
            else:
                k = 0.30 + 0.85 * (lum ** 0.9)
                col = tuple(min(255, int(c * k)) for c in base)
            out.set_at((xx, yy), (*col, a))
    return out


def load_item_sprites():
    key = pygame.image.load(io.BytesIO(base64.b64decode(KEY_PNG_B64)), "key.png").convert_alpha()
    key = pygame.transform.scale(key, (key.get_width() * 2, key.get_height() * 2))
    portal = pygame.image.load(io.BytesIO(base64.b64decode(PORTAL_PNG_B64)), "portal.png").convert_alpha()
    locked = tint_sprite(portal, (255, 55, 70))
    opened = tint_sprite(portal, (70, 255, 130))
    size = (TILE, TILE)
    return (key,
            pygame.transform.scale(locked, size),
            pygame.transform.scale(opened, size))

KEY_IMG, EXIT_LOCKED_IMG, EXIT_OPEN_IMG = load_item_sprites()


def load_extra_sprites():
    """Console (chip) e vida extra (bateria), do pacote Argon Neon Bits, ampliados 2x."""
    size = (TILE, TILE)
    chip = pygame.image.load(io.BytesIO(base64.b64decode(CHIP_PNG_B64)), "chip.png").convert_alpha()
    battery = pygame.image.load(io.BytesIO(base64.b64decode(BATTERY_PNG_B64)), "battery.png").convert_alpha()
    chip_on = tint_sprite(chip, (70, 255, 130))     # console ativado: verde
    return (pygame.transform.scale(chip, size),
            pygame.transform.scale(chip_on, size),
            pygame.transform.scale(battery, size))

CONSOLE_IMG, CONSOLE_ON_IMG, HEAL_IMG = load_extra_sprites()


# ============================================================
# SPRITES NOVOS — pacote "Argon Neon Bits" (CC0), 16x16 ampliados com "nearest":
#   • drone_hover_strip4 -> drone animado (4 quadros), pintado por papel e estado
#   • pilot_helmet       -> jogador (e ícone das vidas)
#   • spark              -> pontinhos
#   • shield / neon_vial / orb_pulse_strip4 -> itens temporários (escudo, aceleração, pulso)
# O bilhete (papel) é desenhado em código, pois o pacote não tem um.
# Tudo embutido em base64: o jogo continua sendo um único arquivo.
# ============================================================







def _load_png(b64, name):
    return pygame.image.load(io.BytesIO(base64.b64decode(b64)), name).convert_alpha()


def recolor(src, mapping):
    """Troca cores exatas de um sprite (pinta o drone por papel/estado sem perder o contorno)."""
    out = src.copy()
    w, h = out.get_size()
    for yy in range(h):
        for xx in range(w):
            r, g, b, a = out.get_at((xx, yy))
            if a and (r, g, b) in mapping:
                out.set_at((xx, yy), (*mapping[(r, g, b)], a))
    return out


def shade(color, k):
    return tuple(max(0, min(255, int(c * k))) for c in color)


def dimmed(img, alpha=70):
    """Cópia translúcida (usada para vidas perdidas e itens ainda não obtidos no HUD)."""
    out = img.copy()
    out.fill((255, 255, 255, alpha), special_flags=pygame.BLEND_RGBA_MULT)
    return out


def scaled(img, size):
    return pygame.transform.scale(img, size)


def make_note_sprite():
    """Bilhete de papel 16x16 (pixel art feita em código)."""
    s = pygame.Surface((16, 16), pygame.SRCALPHA)
    outline, paper, fold, ink, tape = (4, 8, 16), (238, 232, 205), (190, 182, 150), (86, 78, 66), (255, 95, 110)
    pygame.draw.rect(s, outline, (3, 1, 10, 14))
    pygame.draw.rect(s, paper, (4, 2, 8, 12))
    pygame.draw.rect(s, fold, (10, 2, 2, 2))                 # canto dobrado
    pygame.draw.rect(s, outline, (9, 1, 1, 3))
    pygame.draw.rect(s, outline, (9, 3, 4, 1))
    for yy in (6, 8, 10):                                      # linhas de texto
        pygame.draw.line(s, ink, (5, yy), (10, yy))
    pygame.draw.line(s, ink, (5, 12), (8, 12))
    pygame.draw.rect(s, tape, (6, 0, 4, 2))                    # fita vermelha: chama atenção
    return s


def make_clock_sprite():
    """Relógio de gelo 16x16 (item RELÓGIO: congela os drones)."""
    s = pygame.Surface((16, 16), pygame.SRCALPHA)
    edge, ice = (4, 8, 16), (150, 215, 255)
    pygame.draw.circle(s, edge, (8, 9), 7)
    pygame.draw.circle(s, ice, (8, 9), 6)
    pygame.draw.circle(s, (225, 245, 255), (8, 9), 4)
    pygame.draw.line(s, edge, (8, 9), (8, 6))
    pygame.draw.line(s, edge, (8, 9), (10, 9))
    pygame.draw.rect(s, edge, (7, 0, 2, 2))
    return s


def make_mute_sprite():
    """Alto-falante cortado 16x16 (item SILÊNCIO)."""
    s = pygame.Surface((16, 16), pygame.SRCALPHA)
    edge, body, red = (4, 8, 16), (200, 205, 225), (255, 95, 110)
    pygame.draw.rect(s, edge, (1, 5, 5, 6))
    pygame.draw.rect(s, body, (2, 6, 3, 4))
    pygame.draw.polygon(s, edge, [(5, 4), (11, 1), (11, 14), (5, 11)])
    pygame.draw.polygon(s, body, [(6, 5), (10, 3), (10, 12), (6, 10)])
    pygame.draw.line(s, red, (2, 2), (14, 14), 2)
    return s


DRONE_STRIP = _load_png(DRONE_STRIP_PNG_B64, "drone_strip.png")
_PILOT = _load_png(PILOT_PNG_B64, "pilot.png")
_SHIELD = _load_png(SHIELD_PNG_B64, "shield.png")
_VIAL = _load_png(VIAL_PNG_B64, "vial.png")
_SPARK = _load_png(SPARK_PNG_B64, "spark.png")
_ORB_STRIP = _load_png(ORB_STRIP_PNG_B64, "orb_strip.png")
_NOTE = make_note_sprite()

PILOT_IMG = scaled(_PILOT, (TILE, TILE))
LIFE_IMG = scaled(_PILOT, (24, 24))
LIFE_DIM_IMG = dimmed(LIFE_IMG, 55)
SHIELD_IMG = scaled(_SHIELD, (TILE, TILE))
VIAL_IMG = scaled(_VIAL, (TILE, TILE))
NOTE_IMG = scaled(_NOTE, (TILE, TILE))
DOT_IMG = scaled(_SPARK, (24, 24))
ORB_FRAMES = [scaled(_ORB_STRIP.subsurface((i * 16, 0, 16, 16)), (TILE, TILE)) for i in range(4)]
SHIELD_ICON = scaled(_SHIELD, (24, 24))
VIAL_ICON = scaled(_VIAL, (24, 24))
ORB_ICON = scaled(_ORB_STRIP.subsurface((0, 0, 16, 16)), (24, 24))
ORB_ICON_DIM = dimmed(ORB_ICON, 55)
NOTE_ICON = scaled(_NOTE, (24, 24))
NOTE_ICON_DIM = dimmed(NOTE_ICON)
_CLOCK, _MUTE = make_clock_sprite(), make_mute_sprite()
CLOCK_IMG, CLOCK_ICON = scaled(_CLOCK, (TILE, TILE)), scaled(_CLOCK, (24, 24))
MUTE_IMG, MUTE_ICON = scaled(_MUTE, (TILE, TILE)), scaled(_MUTE, (24, 24))
KEY_ICON = scaled(KEY_IMG, (14, 22))
KEY_ICON_DIM = dimmed(KEY_ICON)
CONSOLE_ICON = scaled(CONSOLE_IMG, (24, 24))
CONSOLE_ICON_ON = scaled(CONSOLE_ON_IMG, (24, 24))
CONSOLE_ICON_DIM = dimmed(CONSOLE_ICON)

# Cores originais do sprite do drone (corpo, hélices, olhos) -> recoloridas por papel/estado.
_DRONE_BODY, _DRONE_ROTOR, _DRONE_EYE = (48, 96, 160), (224, 64, 192), (32, 224, 232)
_DRONE_CACHE = {}


def drone_frames(color, eye):
    """4 quadros do drone (TILE x TILE) com corpo na cor do papel e olhos na cor do estado."""
    key = (color, eye)
    frames = _DRONE_CACHE.get(key)
    if frames is None:
        mapping = {_DRONE_BODY: shade(color, 0.62), _DRONE_ROTOR: color, _DRONE_EYE: eye}
        frames = [scaled(recolor(DRONE_STRIP.subsurface((i * 16, 0, 16, 16)), mapping), (TILE, TILE))
                  for i in range(4)]
        _DRONE_CACHE[key] = frames
    return frames

def build_wall_layer(grid, level):
    """
    Pré-renderiza todas as paredes numa única superfície (desenhada 1x por frame).
      • chão logo abaixo da parede  -> 'face' (frente com painéis)
      • chão só à esquerda / direita -> 'cap_left' / 'cap_right' (borda lateral)
      • demais casos                 -> 'top' (topo liso)
    """
    tiles = WALL_TILES[(level - 1) % len(WALL_TILES)]
    layer = pygame.Surface((COLS * TILE, ROWS * TILE), pygame.SRCALPHA)
    is_wall = lambda x, y: 0 <= x < COLS and 0 <= y < ROWS and grid[y][x] == '#'
    for y in range(ROWS):
        for x in range(COLS):
            if grid[y][x] != '#':
                continue
            if y + 1 < ROWS and not is_wall(x, y + 1):
                part = "face"
            else:
                left_open = x > 0 and not is_wall(x - 1, y)
                right_open = x + 1 < COLS and not is_wall(x + 1, y)
                if left_open and not right_open:
                    part = "cap_left"
                elif right_open and not left_open:
                    part = "cap_right"
                else:
                    part = "top"
            layer.blit(tiles[part], (x * TILE, y * TILE))
    return layer.convert_alpha()

# '#' = parede; '.' = ponto; P = jogador; K = chave; C = console; E = saída;
# D = porta (abre com a chave e isola a ala da saída); H = vida extra.
# Cada fase usa um mapa diferente (os 3 se repetem em ciclo). Todas as linhas
# têm exatamente COLS caracteres e COLS x ROWS = 37 x 21.

def make_map(index=0):
    raw = RAW_MAPS[index % len(RAW_MAPS)]
    grid = [list(row.ljust(COLS, '#')[:COLS]) for row in raw]
    # Mantém bordas sólidas mesmo se o mapa for editado.
    for y in range(ROWS):
        grid[y][0] = '#'
        grid[y][-1] = '#'
    for x in range(COLS):
        grid[0][x] = '#'
        grid[-1][x] = '#'
    return grid


# ============================================================
# FASES INFINITAS
# As 3 primeiras fases usam os mapas feitos à mão. A partir da fase 4 cada
# mansão é GERADA na hora (labirinto + salas + porta + chave/console/saída
# espalhados), e a dificuldade sobe a cada fase:
#   • menos atalhos (loops) no labirinto  -> mais becos sem saída
#   • mais drones (até 8), mais rápidos, enxergam mais longe e reagem mais rápido
#   • objetivos cada vez mais distantes entre si
# ============================================================
def _flood_grid(grid, source, blocked=None):
    """Distâncias (BFS) sobre a grade de caracteres; só '#' bloqueia."""
    dist = {source: 0}
    prev = {source: None}
    queue = deque([source])
    while queue:
        cur = queue.popleft()
        for dx, dy in DIRS4:
            nxt = (cur[0] + dx, cur[1] + dy)
            if nxt in dist or nxt == blocked:
                continue
            if 0 <= nxt[0] < COLS and 0 <= nxt[1] < ROWS and grid[nxt[1]][nxt[0]] != '#':
                dist[nxt] = dist[cur] + 1
                prev[nxt] = cur
                queue.append(nxt)
    return dist, prev


def generate_level(level, rng):
    """Devolve uma grade (lista de listas de caracteres) ou None se falhar."""
    cw, ch = (COLS - 1) // 2, (ROWS - 1) // 2
    grid = [['#'] * COLS for _ in range(ROWS)]

    # 1) Labirinto perfeito (DFS): corredores longos e sinuosos.
    seen = {(0, 0)}
    stack = [(0, 0)]
    grid[1][1] = ' '
    while stack:
        cx, cy = stack[-1]
        opts = [(cx + dx, cy + dy, dx, dy) for dx, dy in DIRS4
                if 0 <= cx + dx < cw and 0 <= cy + dy < ch and (cx + dx, cy + dy) not in seen]
        if not opts:
            stack.pop()
            continue
        nx, ny, dx, dy = rng.choice(opts)
        grid[cy * 2 + 1 + dy][cx * 2 + 1 + dx] = ' '
        grid[ny * 2 + 1][nx * 2 + 1] = ' '
        seen.add((nx, ny))
        stack.append((nx, ny))

    # 2) Algumas salas 3x3 abertas (lugares para fugir... ou para ser cercado).
    for _ in range(rng.randint(1, 3)):
        x0 = rng.randrange(1, COLS - 3, 2)
        y0 = rng.randrange(1, ROWS - 3, 2)
        if x0 <= 5 and y0 <= 5:
            continue  # mantém a área inicial como corredor
        for yy in range(y0, y0 + 3):
            for xx in range(x0, x0 + 3):
                grid[yy][xx] = ' '

    spawn = (1, 1)
    dist, prev = _flood_grid(grid, spawn)
    floors = sorted(dist, key=lambda t: (dist[t], t))
    far = dist[floors[-1]]
    if far < 40:
        return None

    # 3) Porta: um corredor que, fechado, isola um trecho do mapa (15%-45% da área).
    #    A saída fica sempre dentro desse trecho trancado.
    total = len(dist)
    corridors = [t for t in floors if t != spawn and dist[t] >= 6
                 and sum(1 for dx, dy in DIRS4 if grid[t[1] + dy][t[0] + dx] != '#') == 2]
    rng.shuffle(corridors)
    door, sealed = None, None
    for t in corridors[:70]:
        d2, _ = _flood_grid(grid, spawn, blocked=t)
        cut = total - len(d2) - 1            # tiles isolados atrás da porta
        if 0.15 * total <= cut <= 0.45 * total:
            door = t
            behind, _ = _flood_grid(grid, t)
            sealed = {c: behind[c] for c in behind if c not in d2 and c != t}
            break
    exit_t = None
    if door:
        # Saída = ponto mais fundo do trecho trancado.
        deep = max(sealed.values())
        exit_t = rng.choice([c for c, dd in sealed.items() if dd >= deep * 0.8])

    # 4) Atalhos (braid): quanto maior a fase, menos atalhos. Nunca abre caminho
    #    para dentro do trecho trancado (a porta continua sendo a única entrada).
    braid = max(0.04, 0.22 - 0.012 * (level - 4))
    walls = []
    for y in range(1, ROWS - 1):
        for x in range(1, COLS - 1):
            if grid[y][x] != '#':
                continue
            if x % 2 == 0 and y % 2 == 1:
                a, b = (x - 1, y), (x + 1, y)
            elif x % 2 == 1 and y % 2 == 0:
                a, b = (x, y - 1), (x, y + 1)
            else:
                continue
            if grid[a[1]][a[0]] == '#' or grid[b[1]][b[0]] == '#':
                continue
            if door and (a == door or b == door or ((a in sealed) != (b in sealed))):
                continue
            walls.append((x, y))
    rng.shuffle(walls)
    for x, y in walls[:int(len(walls) * braid)]:
        grid[y][x] = ' '
    dist, prev = _flood_grid(grid, spawn)
    floors = sorted(dist, key=lambda t: (dist[t], t))
    far = dist[floors[-1]]
    if door:
        dist_nd, _ = _flood_grid(grid, spawn, blocked=door)
    else:
        exit_t = rng.choice([t for t in floors if dist[t] >= far * 0.85])
        dist_nd = dist
    area = sorted((t for t in dist_nd if t not in (spawn, exit_t)), key=lambda t: (dist_nd[t], t))
    if len(area) < 30:
        return None

    # 5) Chave longe do início; console longe da chave.
    far_nd = dist_nd[area[-1]]
    key_t = rng.choice([t for t in area if dist_nd[t] >= far_nd * 0.7])
    from_key, _ = _flood_grid(grid, key_t)
    cons_pool = [t for t in area if t != key_t and from_key.get(t, 0) >= 12 and dist_nd[t] >= 8
                 and (door is None or t != door)]
    if not cons_pool:
        return None
    far_key = max(from_key[t] for t in cons_pool)
    console_t = rng.choice([t for t in cons_pool if from_key[t] >= far_key * 0.6])

    # 6) Vida extra num ponto intermediário.
    used = {spawn, exit_t, key_t, console_t, door}
    heal_pool = [t for t in area if t not in used and 10 <= dist_nd[t]]
    heal_t = rng.choice(heal_pool) if heal_pool else None
    used.add(heal_t)

    # 7) Converte para os caracteres usados pelo jogo.
    for t in dist:
        grid[t[1]][t[0]] = '.'
    grid[spawn[1]][spawn[0]] = 'P'
    grid[exit_t[1]][exit_t[0]] = 'E'
    grid[key_t[1]][key_t[0]] = 'K'
    grid[console_t[1]][console_t[0]] = 'C'
    if heal_t:
        grid[heal_t[1]][heal_t[0]] = 'H'
    if door:
        grid[door[1]][door[0]] = 'D'
    return grid


def build_level_grid(level):
    """(grade, id_do_mapa). Fases 1-3: mapas fixos; depois, mapas gerados."""
    if level <= len(RAW_MAPS):
        index = (level - 1) % len(RAW_MAPS)
        return make_map(index), index
    for _ in range(40):
        grid = generate_level(level, random.Random(random.getrandbits(48)))
        if grid:
            return grid, "gen"
    index = (level - 1) % len(RAW_MAPS)   # nunca deve acontecer; mantém o jogo rodando
    return make_map(index), index


# ============================================================
# SISTEMA DE IA DOS INIMIGOS (v2)
#
#  • Nav ............ A*, flood-fill e linha de visão na grade
#  • AdaptiveBrain .. memória do jogador (mapa de calor, locais de captura,
#                     hábitos de curva) salva em JSON de forma econômica
#  • DroneDirector .. "cérebro do esquadrão": alerta, rádio, ruído,
#                     pontos de patrulha/busca e coordenação entre drones
#  • SecurityDrone .. máquina de estados com visão, audição e papéis
#
#  Estados: PATROL → NOTICE → CHASE → SEARCH → PATROL
#           INVESTIGATE (ouviu um ruído) e REGROUP (recuo após capturar)
#
#  Papéis:  hunter   (vermelho) persegue direto e patrulha onde você mais anda
#           ambusher (rosa)     prevê sua rota e intercepta à frente
#           guard    (ciano)    defende o objetivo atual (chave/console/saída)
#           scout    (laranja)  flanqueia de longe e patrulha onde você já foi pego
# ============================================================

DIRS4 = [(1, 0), (-1, 0), (0, 1), (0, -1)]
PLAYER_SPEED = 2.0  # mesma velocidade usada em Game.update


def ai_profile(level, diff=None):
    """Parâmetros de dificuldade que crescem com a fase (e com o modo escolhido no menu)."""
    lv = max(1, level)
    diff = diff or DIFFICULTIES[1]
    prof = {
        "level": lv,
        # velocidade em perseguição (continua subindo devagar depois da fase 8)
        "speed": min(2.35, 1.55 + 0.11 * (lv - 1)) + min(0.15, 0.01 * max(0, lv - 8)),
        "vision": min(11, 5 + lv) + (1 if lv >= 12 else 0),  # alcance da visão frontal (tiles)
        "peripheral": 3 if lv < 10 else 4,             # visão lateral/traseira (tiles)
        "sense": 1 if lv < 3 else (2 if lv < 6 else 3),  # "radar" de proximidade (tiles de caminho)
        "react": max(6, 32 - 3 * lv),                   # frames de hesitação ao ver o jogador
        "guard_zone": min(9, 4 + lv),                  # raio (em tiles) que o guardião defende
        "guard_engage": min(6, 2 + lv),                # distância em que ele persegue fora da zona
        "grace": 40 + 6 * lv,                          # frames perseguindo a última posição conhecida
        "search": min(900, 220 + 40 * lv),             # frames vasculhando a área depois
        "regroup": 210,                                # recuo depois de capturar o jogador
        "reverse_cost": 6.0,                           # custo de dar meia-volta
    }
    prof["speed"] *= diff["speed"]
    prof["vision"] = max(3, prof["vision"] + diff["vision"])
    prof["react"] = max(4, int(prof["react"] * diff["react"]))
    return prof


def is_blackout_level(level):
    """Fases 3, 7, 11, ...: apagão (só se enxerga perto do jogador)."""
    return level >= 3 and level % 4 == 3


def is_boss_level(level):
    """Fases 5, 10, 15, ...: aparece um drone CHEFE (roxo)."""
    return level >= 5 and level % 5 == 0


class Nav:
    """Utilidades de grade: vizinhança, A*, flood-fill e linha de visão."""

    @staticmethod
    def manhattan(a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    @staticmethod
    def neighbors(game, tile):
        x, y = tile
        return [(x + dx, y + dy) for dx, dy in DIRS4 if game.walkable(x + dx, y + dy)]

    @staticmethod
    def nearest_open(game, origin):
        """Célula livre mais próxima (usada se o alvo cair numa parede)."""
        start = (min(max(origin[0], 0), COLS - 1), min(max(origin[1], 0), ROWS - 1))
        if game.walkable(*start):
            return start
        seen = {start}
        queue = deque([start])
        while queue:
            cx, cy = queue.popleft()
            for dx, dy in DIRS4:
                nxt = (cx + dx, cy + dy)
                if nxt in seen or not (0 <= nxt[0] < COLS and 0 <= nxt[1] < ROWS):
                    continue
                if game.walkable(*nxt):
                    return nxt
                seen.add(nxt)
                queue.append(nxt)
        return (1, 1)

    @staticmethod
    def flood(game, source, limit=None):
        """Distância (em tiles) de 'source' até cada célula alcançável."""
        dist = {source: 0}
        queue = deque([source])
        while queue:
            cur = queue.popleft()
            d = dist[cur]
            if limit is not None and d >= limit:
                continue
            for nxt in Nav.neighbors(game, cur):
                if nxt not in dist:
                    dist[nxt] = d + 1
                    queue.append(nxt)
        return dist

    @staticmethod
    def astar(game, start, goal, extra=None, reverse_tile=None, reverse_cost=0.0):
        """A* com custos extras por célula e penalidade para dar meia-volta."""
        if start == goal:
            return [start]
        extra = extra or {}
        best = {start: 0.0}
        prev = {start: None}
        heap = [(Nav.manhattan(start, goal), 0.0, start)]
        while heap:
            _, g, cur = heapq.heappop(heap)
            if cur == goal:
                break
            if g > best.get(cur, 1e9):
                continue
            for nxt in Nav.neighbors(game, cur):
                cost = 1.0 + extra.get(nxt, 0.0)
                if cur == start and nxt == reverse_tile:
                    cost += reverse_cost
                ng = g + cost
                if ng < best.get(nxt, 1e9):
                    best[nxt] = ng
                    prev[nxt] = cur
                    heapq.heappush(heap, (ng + Nav.manhattan(nxt, goal), ng, nxt))
        if goal not in prev:
            return None
        path = []
        cell = goal
        while cell is not None:
            path.append(cell)
            cell = prev[cell]
        path.reverse()
        return path

    @staticmethod
    def clear_line(game, a, b):
        """True se a e b estão na mesma linha/coluna sem paredes no meio."""
        if a == b:
            return True
        if a[0] == b[0]:
            step = 1 if b[1] > a[1] else -1
            return all(game.walkable(a[0], y) for y in range(a[1] + step, b[1], step))
        if a[1] == b[1]:
            step = 1 if b[0] > a[0] else -1
            return all(game.walkable(x, a[1]) for x in range(a[0] + step, b[0], step))
        return False


class AdaptiveBrain:
    """
    Memória do jogador entre partidas (sem bibliotecas externas):
      heat   — quanto tempo o jogador passa em cada tile
      danger — onde o jogador já foi capturado
      turns  — qual saída ele costuma escolher em cada cruzamento
    Os drones usam isso para escolher onde patrulhar e para prever a rota.
    O arquivo só é gravado de vez em quando (não a cada passo).
    """
    MEMORY_FILE = os.path.join(DATA_DIR, "ai_memoria.json")
    VERSION = 3  # v3: dados separados por mapa

    def __init__(self):
        self.heat = {}
        self.danger = {}
        self.turns = {}
        self.map_id = 0
        self.heat_max = 1.0
        self.danger_max = 1.0
        self.last_tile = None
        self.last_dir = None
        self.dirty = False
        self.save_timer = 0
        self.load()

    # ---------- persistência ----------
    def _k(self, tile):
        return f"{self.map_id}:{tile[0]},{tile[1]}"

    def load(self):
        try:
            with open(self.MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("version") != self.VERSION:
                return
            decay = 0.85  # o que o jogador fez recentemente pesa mais
            self.heat = {k: float(v) * decay for k, v in data.get("heat", {}).items()}
            self.danger = {k: float(v) * decay for k, v in data.get("danger", {}).items()}
            self.turns = {k: {d: float(n) * decay for d, n in b.items()}
                          for k, b in data.get("turns", {}).items()}
            self.heat = {k: v for k, v in self.heat.items() if v > 0.05}
            self.danger = {k: v for k, v in self.danger.items() if v > 0.05}
        except (OSError, ValueError, TypeError, AttributeError):
            self.heat, self.danger, self.turns = {}, {}, {}
        self._refresh_max()

    def _refresh_max(self):
        prefix = f"{self.map_id}:"
        self.heat_max = max((v for k, v in self.heat.items() if k.startswith(prefix)), default=1.0)
        self.danger_max = max((v for k, v in self.danger.items() if k.startswith(prefix)), default=1.0)

    def save(self):
        if not self.dirty:
            return
        turns = self.turns
        if len(turns) > 1200:
            ranked = sorted(turns.items(), key=lambda kv: sum(kv[1].values()), reverse=True)
            turns = dict(ranked[:800])
            self.turns = turns
        try:
            with open(self.MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump({"version": self.VERSION,
                           "heat": {k: round(v, 2) for k, v in self.heat.items()},
                           "danger": {k: round(v, 2) for k, v in self.danger.items()},
                           "turns": turns}, f, separators=(",", ":"))
            self.dirty = False
        except OSError:
            pass

    def forget_map(self, map_id):
        """Mapas gerados são descartáveis: apaga a memória do mapa anterior."""
        prefix = f"{map_id}:"
        self.heat = {k: v for k, v in self.heat.items() if not k.startswith(prefix)}
        self.danger = {k: v for k, v in self.danger.items() if not k.startswith(prefix)}
        self.turns = {k: v for k, v in self.turns.items() if not k.startswith(prefix)}
        self.dirty = True

    def set_map(self, map_id, fresh=False):
        """Cada mapa tem sua própria memória do jogador."""
        if fresh:
            self.forget_map(map_id)
        self.map_id = map_id
        self.last_tile = None
        self.last_dir = None
        self._refresh_max()

    def tick(self):
        """Chamado a cada frame: grava no máximo a cada ~15 segundos."""
        self.save_timer += 1
        if self.dirty and self.save_timer >= 900:
            self.save_timer = 0
            self.save()

    # ---------- observação ----------
    def observe(self, game):
        tile = game.player_tile()
        if tile == self.last_tile:
            return
        if self.last_tile is not None:
            out_dir = (tile[0] - self.last_tile[0], tile[1] - self.last_tile[1])
            if abs(out_dir[0]) + abs(out_dir[1]) == 1:
                # Só importa a escolha feita em cruzamentos (3+ saídas).
                if self.last_dir is not None and len(Nav.neighbors(game, self.last_tile)) >= 3:
                    key = f"{self._k(self.last_tile)}|{self.last_dir[0]},{self.last_dir[1]}"
                    bucket = self.turns.setdefault(key, {})
                    dk = f"{out_dir[0]},{out_dir[1]}"
                    bucket[dk] = bucket.get(dk, 0.0) + 1.0
                self.last_dir = out_dir
            else:
                self.last_dir = None  # teleporte (respawn)
        self.last_tile = tile
        k = self._k(tile)
        self.heat[k] = self.heat.get(k, 0.0) + 1.0
        self.heat_max = max(self.heat_max, self.heat[k])
        self.dirty = True

    def record_catch(self, tile):
        k = self._k(tile)
        self.danger[k] = self.danger.get(k, 0.0) + 1.0
        self.danger_max = max(self.danger_max, self.danger[k])
        self.dirty = True
        self.save()

    # ---------- consulta ----------
    def heat_norm(self, tile):
        return math.sqrt(self.heat.get(self._k(tile), 0.0) / self.heat_max)

    def danger_norm(self, tile):
        return math.sqrt(self.danger.get(self._k(tile), 0.0) / self.danger_max)

    def habit(self, tile, in_dir):
        """Saída que o jogador costuma pegar neste cruzamento (ou None)."""
        bucket = self.turns.get(f"{self._k(tile)}|{in_dir[0]},{in_dir[1]}")
        if not bucket:
            return None
        total = sum(bucket.values())
        if total < 3:
            return None
        best, n = max(bucket.items(), key=lambda kv: kv[1])
        if n / total < 0.5:
            return None
        dx, dy = best.split(",")
        return (int(dx), int(dy))


class DroneDirector:
    """Cérebro do esquadrão: compartilha informação e distribui tarefas."""

    def __init__(self, game):
        self.profile = ai_profile(game.level, game.diff)
        self.frame = 0
        self.alert = 0.0
        self.last_known = None          # {"tile", "dir", "frame"} do jogador
        self.player_dir = (1, 0)
        self._last_radio = -999
        self._objective = None
        self._goal = None
        self._goal_dist = {}
        self._zone = {}
        self._route = set()
        self.waypoints = []
        self.waypoint_set = set()
        self._refresh_waypoints(game)
        self.drones = []
        self._spawn(game)

    # ---------- montagem ----------
    def _refresh_waypoints(self, game):
        """Cruzamentos, becos e curvas ALCANÇÁVEIS: bons pontos de patrulha."""
        reachable = Nav.flood(game, game.spawn_tile)
        points = []
        for tile in reachable:
            exits = Nav.neighbors(game, tile)
            if len(exits) != 2:
                points.append(tile)
            else:  # corredor reto não interessa; curva sim
                a, b = exits
                if (a[0] - tile[0], a[1] - tile[1]) != (tile[0] - b[0], tile[1] - b[1]):
                    points.append(tile)
        self.waypoints = points
        self.waypoint_set = set(points)

    def _spawn(self, game):
        reach = Nav.flood(game, game.spawn_tile)   # só nasce em área alcançável
        near = lambda pos: min(reach, key=lambda t: (Nav.manhattan(t, pos), t))
        from_key = Nav.flood(game, game.key_pos)
        guard_tile = min((t for t in from_key if t in reach), key=lambda t: (abs(from_key[t] - 8), t))
        specs = [
            ("hunter",   RED,  near((COLS // 2, 5)),             60),
            ("ambusher", PINK, near((COLS * 2 // 3, ROWS // 2 + 2)), 150),
            ("guard",    CYAN, guard_tile,                       90),
        ]
        if game.level >= 3:
            specs.append(("scout", ORANGE, near((COLS * 3 // 4, ROWS - 6)), 240))
        if game.level >= 6:     # fantasma: teleporta de tempos em tempos
            specs.append(("phantom", PHANTOM_COLOR, near((COLS // 3, ROWS - 5)), 300))
        if game.level >= 8:     # sentinela: lenta, mas enxerga muito longe pela frente
            specs.append(("sentinel", GREEN, near((COLS * 5 // 6, 4)), 330))
        # Fases infinitas: a cada 2 fases (a partir da 5) entra mais um drone, até 8.
        extra = min(4, max(0, (game.level - 3) // 2))
        colors = {"hunter": RED, "ambusher": PINK, "scout": ORANGE, "guard": CYAN}
        from_spawn = reach
        far_tiles = [t for t in reach if from_spawn[t] >= 14]
        if not far_tiles:
            far_tiles = sorted(reach, key=lambda t: from_spawn[t])[-max(1, len(reach) // 4):]
        for i in range(extra):
            role = ("hunter", "ambusher", "scout", "hunter")[i % 4]
            options = [t for t in far_tiles if all(Nav.manhattan(t, s[2]) >= 6 for s in specs)] or far_tiles
            specs.append((role, colors[role], random.choice(options), 120 + 45 * i))
        boss = is_boss_level(game.level)
        if boss:    # drone chefe: roxo, mais rápido e resiste ao pulso (atordoa metade do tempo)
            options = [t for t in far_tiles if all(Nav.manhattan(t, s[2]) >= 6 for s in specs)] or far_tiles
            specs.append(("hunter", PURPLE, random.choice(options), 150))
        for role, color, tile, delay in specs:
            self.drones.append(SecurityDrone(role, color, tile, self.profile, delay))
        if boss:
            chief = self.drones[-1]
            chief.boss = True
            chief.profile = dict(self.profile)
            chief.profile["speed"] *= 1.08

    # ---------- atualização ----------
    def update(self, game):
        self.frame += 1
        if tuple(game.player.direction) != (0, 0):
            self.player_dir = tuple(game.player.direction)
        self.alert = max(0.0, self.alert - 1 / 1500)  # ~25 s para acalmar

        obj = game.current_objective()
        if obj != self._objective:
            self._objective = obj
            self._refresh_waypoints(game)  # a porta pode ter aberto
            # Se o objetivo estiver isolado (mapa editado/quebrado), usa o tile
            # alcançável mais próximo dele para a IA nunca ficar sem rumo.
            reach = Nav.flood(game, game.spawn_tile)
            if obj not in reach:
                obj = min(reach, key=lambda t: Nav.manhattan(t, obj))
            self._goal = obj
            self._goal_dist = Nav.flood(game, obj)
            self._zone = {t: d for t, d in self._goal_dist.items() if d <= self.profile["guard_zone"]}
            start = game.player_tile()
            path = Nav.astar(game, start, obj) or []
            self._route = set(path)
            for d in self.drones:
                if d.role == "guard" and d.state in ("PATROL", "SEARCH"):
                    d.goal = None

        for d in self.drones:
            d.update(game, self)

    def in_zone(self, tile):
        return tile in self._zone

    def phase(self):
        states = {d.state for d in self.drones if d.delay <= 0}
        if states & {"CHASE", "NOTICE"}:
            return "CAÇADA", RED
        if states & {"INVESTIGATE", "SEARCH"}:
            return "BUSCA", GOLD
        return "PATRULHA", CYAN

    # ---------- comunicação ----------
    def report_sighting(self, spotter, game):
        tile = game.player_tile()
        self.last_known = {"tile": tile, "dir": self.player_dir, "frame": self.frame}
        self.alert = 1.0
        if self.frame - self._last_radio < 45:
            return
        self._last_radio = self.frame
        field = Nav.flood(game, spotter.current_tile(), limit=16)  # alcance do rádio
        for o in self.drones:
            if o is spotter or o.delay > 0 or o.state in ("CHASE", "NOTICE", "REGROUP"):
                continue
            if o.current_tile() not in field:
                continue
            if o.role == "guard" and not self.in_zone(tile):
                continue
            o.set_state("CHASE")

    def report_noise(self, game, tile, radius):
        """Barulho (pegar a chave, usar o console): drones próximos vão investigar."""
        if game.silent_t > 0:          # item SILÊNCIO ativo
            return
        self.alert = max(self.alert, 0.5)
        for o in self.drones:
            if o.delay > 0 or o.state in ("CHASE", "NOTICE", "REGROUP"):
                continue
            if Nav.manhattan(o.current_tile(), tile) <= radius:
                o.set_state("INVESTIGATE")
                o.goal = Nav.nearest_open(game, tile)
                o.wait = 0

    def on_player_caught(self, game):
        """Depois de capturar o jogador o esquadrão recua e se reorganiza."""
        self.last_known = None
        self.alert = 0.0
        field = Nav.flood(game, game.spawn_tile)
        far = sorted((t for t in self.waypoints if t in field), key=lambda t: field[t], reverse=True)
        far = far[:max(8, len(far) * 2 // 5)]
        taken = []
        for d in self.drones:
            d.set_state("REGROUP")
            d.regroup_timer = self.profile["regroup"] + random.randint(0, 40)
            options = [t for t in far if all(Nav.manhattan(t, g) >= 5 for g in taken)] or far
            d.goal = random.choice(options) if options else d.tile_pos
            d.wait = 0
            taken.append(d.goal)

    # ---------- escolha de alvos ----------
    def _taken_goals(self, drone):
        return [o.goal for o in self.drones if o is not drone and o.goal]

    def patrol_point(self, drone, game):
        brain = game.brain
        me = drone.current_tile()
        taken = self._taken_goals(drone)
        lk = self.last_known
        obj = self._goal
        cands, weights = [], []
        for t in self.waypoints:
            if Nav.manhattan(t, me) < 4:
                continue
            if any(Nav.manhattan(t, g) < 5 for g in taken):
                continue
            w = 1.0
            heat, danger = brain.heat_norm(t), brain.danger_norm(t)
            if drone.role == "hunter":
                w += 4 * heat + 2 * danger
            elif drone.role == "ambusher":
                w += (5.0 if t in self._route else 0.0) + 2 * heat
            elif drone.role == "guard":
                d = self._goal_dist.get(t)       # raio de patrulha fixo; só o
                if d is None or d > 6:           # engajamento cresce com a fase
                    continue
                w += 7 - d
            elif drone.role == "scout":
                w += 6 * danger + 3 * heat
            elif drone.role == "phantom":
                w += 3 * heat + 3 * danger
            if lk and self.alert > 0.2 and Nav.manhattan(t, lk["tile"]) <= 9:
                w += 8 * self.alert
            cands.append(t)
            weights.append(w)
        if not cands:
            if drone.role == "guard" and obj:
                return Nav.nearest_open(game, obj)
            return random.choice(self.waypoints) if self.waypoints else me
        return random.choices(cands, weights)[0]

    def search_point(self, drone, game):
        """Distribui os drones em busca por saídas diferentes ao redor da última posição."""
        lk = self.last_known
        origin = lk["tile"] if lk else drone.current_tile()
        heading = lk["dir"] if lk else (0, 0)
        field = Nav.flood(game, origin, limit=10)
        taken = self._taken_goals(drone)
        cands, weights = [], []
        for t, dist in field.items():
            if t not in self.waypoint_set or dist < 2:
                continue
            if any(Nav.manhattan(t, g) < 4 for g in taken):
                continue
            w = 1.0 + 3.0 * game.brain.heat_norm(t)
            if (t[0] - origin[0]) * heading[0] + (t[1] - origin[1]) * heading[1] > 0:
                w += 3.0  # provavelmente seguiu nessa direção
            cands.append(t)
            weights.append(w)
        if not cands:
            return origin
        return random.choices(cands, weights)[0]

    def predict_route(self, game, start, direction, steps):
        """Simula o caminho provável do jogador: hábitos aprendidos, senão rumo ao objetivo."""
        route = []
        pos, d = tuple(start), tuple(direction)
        for _ in range(steps):
            exits = Nav.neighbors(game, pos)
            if not exits:
                break
            rev = (pos[0] - d[0], pos[1] - d[1])
            options = [n for n in exits if n != rev] or exits
            if len(options) == 1:
                nxt = options[0]
            else:
                nxt = None
                if d != (0, 0):
                    h = game.brain.habit(pos, d)
                    if h and (pos[0] + h[0], pos[1] + h[1]) in options:
                        nxt = (pos[0] + h[0], pos[1] + h[1])
                if nxt is None:
                    nxt = min(options, key=lambda n: self._goal_dist.get(n, 999))
            d = (nxt[0] - pos[0], nxt[1] - pos[1])
            route.append(nxt)
            pos = nxt
        return route

    def intercept_point(self, drone, game, start, direction, age, look):
        """
        Tile mais distante da rota prevista que o drone consegue alcançar
        ANTES do jogador. Retorna None se não houver (aí o drone persegue direto).
        'age' = frames desde que o jogador foi visto pela última vez.
        """
        route = self.predict_route(game, start, direction, look)
        if not route:
            return None
        field = Nav.flood(game, drone.tile_pos)
        spd = max(0.5, drone.speed_chase)
        best = None
        for i, t in enumerate(route, 1):
            d = field.get(t)
            if d is not None and d * PLAYER_SPEED / spd <= i - age * PLAYER_SPEED / TILE:
                best = t
        return best

    def congestion(self, drone):
        """Custo extra nas células ocupadas por outros drones (evita enfileirar)."""
        extra = {}
        for o in self.drones:
            if o is drone:
                continue
            for t in (o.tile_pos, o.step):
                if t:
                    extra[t] = extra.get(t, 0.0) + 3.0
        return extra


class SecurityDrone:
    """Drone com visão, audição, memória e comportamento próprio por papel."""

    SPEED_FACTOR = {"PATROL": 0.78, "INVESTIGATE": 0.95, "SEARCH": 0.85,
                    "CHASE": 1.0, "NOTICE": 0.0, "REGROUP": 0.9}
    ROLE_SPEED = {"hunter": 1.0, "ambusher": 1.0, "guard": 0.88, "scout": 1.05,
                  "phantom": 1.0, "sentinel": 0.8}
    EYE = {"PATROL": (90, 205, 255), "INVESTIGATE": GOLD, "SEARCH": GOLD,
           "NOTICE": WHITE, "CHASE": RED, "REGROUP": GREY}

    def __init__(self, role, color, tile, profile, delay=0):
        self.role = role
        self.color = color
        self.profile = profile
        self.tile_pos = tile
        self.x, self.y = float(tile[0] * TILE), float(tile[1] * TILE)
        self.prev_tile = None
        self.step = None
        self.facing = random.choice(DIRS4)
        self.state = "PATROL"
        self.goal = None
        self.path = []
        self.delay = delay
        self.wait = random.randint(10, 40)
        self.react = 0
        self.search_timer = 0
        self.regroup_timer = 0
        self.sees = False
        self.pulse = 0
        self.stun = 0                        # frames atordoado pelo pulso (parado e cego)
        self.anim_off = random.randrange(4)  # desencontra a animação dos drones
        self.boss = False                    # drone chefe (fases múltiplas de 5)
        self.blink_t = random.randint(300, 540)   # fantasma: frames até o próximo teleporte

    # ---------- utilidades ----------
    @property
    def speed(self):
        return self.profile["speed"] * self.ROLE_SPEED[self.role] * self.SPEED_FACTOR[self.state]

    @property
    def speed_chase(self):
        return self.profile["speed"] * self.ROLE_SPEED[self.role]

    def current_tile(self):
        return round(self.x / TILE), round(self.y / TILE)

    def set_state(self, state):
        if state != self.state:
            self.state = state
            self.goal = None
            self.path = []

    # ---------- ciclo principal ----------
    def update(self, game, director):
        if self.delay > 0:
            self.delay -= 1
            return
        self.pulse += 1
        if self.stun > 0:                    # atordoado: não vê, não anda, não captura
            self.stun -= 1
            self.sees = False
            if self.stun == 0:
                self.wait = 0
            return
        if self.role == "phantom":
            self.blink(game, director)
        self.perceive(game, director)
        self.update_state(game, director)
        self.move(game, director)

    def vision_range(self):
        """Alcance da visão frontal (a sentinela enxerga 3 tiles a mais, mas não tem visão lateral)."""
        return self.profile["vision"] + (3 if self.role == "sentinel" else 0)

    def blink(self, game, director):
        """Fantasma: de tempos em tempos some e reaparece em outro ponto da mansão."""
        if self.state in ("CHASE", "NOTICE", "REGROUP"):
            return
        self.blink_t -= 1
        if self.blink_t > 0:
            return
        self.blink_t = random.randint(420, 660)
        pt = game.player_tile()
        spots = [t for t in director.waypoints
                 if Nav.manhattan(t, pt) >= 8 and Nav.manhattan(t, self.current_tile()) >= 6]
        if not spots:
            return
        dest = random.choice(spots)
        ox, oy = int(self.x + TILE // 2), int(self.y + TILE // 2 + HUD_H)
        game.particles.burst(ox, oy, [PHANTOM_COLOR, WHITE], n=14, speed=2.5, life=(14, 30))
        self.tile_pos, self.prev_tile, self.step = dest, None, None
        self.x, self.y = float(dest[0] * TILE), float(dest[1] * TILE)
        self.goal, self.path, self.wait = None, [], 25
        nx_, ny_ = game.center_px(dest)
        game.particles.burst(nx_, ny_, [PHANTOM_COLOR, WHITE], n=14, speed=2.5, life=(14, 30))
        if Nav.manhattan(dest, pt) <= 14:
            play("blink", cooldown=300)

    def perceive(self, game, director):
        """Visão frontal longa + visão lateral curta + radar de proximidade."""
        self.sees = False
        if self.state == "REGROUP":
            return
        me, pt = self.current_tile(), game.player_tile()
        dist = Nav.manhattan(me, pt)
        if dist == 0:
            self.sees = True
        else:
            if me[0] == pt[0] or me[1] == pt[1]:
                heading = ((pt[0] > me[0]) - (pt[0] < me[0]), (pt[1] > me[1]) - (pt[1] < me[1]))
                reach = (self.vision_range() if heading == self.facing
                         else (0 if self.role == "sentinel" else self.profile["peripheral"]))
                if dist <= reach and Nav.clear_line(game, me, pt):
                    self.sees = True
            sense = self.profile["sense"]
            if not self.sees and dist <= sense and pt in Nav.flood(game, me, limit=sense):
                self.sees = True
        # O guardião só se compromete se o jogador estiver na sua zona ou muito perto.
        if self.sees and self.role == "guard" and not (director.in_zone(pt) or dist <= self.profile["guard_engage"]):
            self.sees = False

    def update_state(self, game, director):
        if self.wait > 0:
            self.wait -= 1
        if self.state == "REGROUP":
            self.regroup_timer -= 1
            if self.regroup_timer <= 0:
                self.set_state("PATROL")
            return
        if self.sees:
            director.report_sighting(self, game)
        if self.state == "NOTICE":
            self.react -= 1
            if self.react <= 0:
                self.set_state("CHASE")
        elif self.sees and self.state != "CHASE":
            play("spot_hunter" if self.role == "hunter" else "spot", cooldown=350)
            self.set_state("NOTICE")
            self.react = self.profile["react"]
            self.wait = 0
        elif self.state == "CHASE" and not self.sees:
            lk = director.last_known
            age = director.frame - lk["frame"] if lk else 9999
            if age > self.profile["grace"]:
                play("lost", cooldown=900)
                self.set_state("SEARCH")
                self.search_timer = self.profile["search"]
        elif self.state == "SEARCH":
            self.search_timer -= 1
            if self.search_timer <= 0:
                self.set_state("PATROL")

    # ---------- movimento tile a tile ----------
    def move(self, game, director):
        budget = self.speed
        for _ in range(4):
            if budget <= 1e-6:
                return
            if self.step is None:
                self.step = self.decide(game, director)
                if self.step is None:
                    return
                self.facing = (self.step[0] - self.tile_pos[0], self.step[1] - self.tile_pos[1])
            tx, ty = self.step[0] * TILE, self.step[1] * TILE
            dx, dy = tx - self.x, ty - self.y
            dist = abs(dx) + abs(dy)
            if dist <= budget:
                self.x, self.y = float(tx), float(ty)
                budget -= dist
                self.prev_tile, self.tile_pos, self.step = self.tile_pos, self.step, None
            else:
                self.x += budget * ((dx > 0) - (dx < 0))
                self.y += budget * ((dy > 0) - (dy < 0))
                return

    def decide(self, game, director):
        """Chamado ao chegar no centro de um tile: escolhe o próximo tile do caminho."""
        if self.state == "NOTICE" or self.wait > 0:
            return None
        goal = self.pick_goal(game, director)
        me = self.tile_pos
        if goal is None or goal == me:
            return None
        goal = Nav.nearest_open(game, goal)
        path = Nav.astar(game, me, goal, director.congestion(self),
                         self.prev_tile, self.profile["reverse_cost"])
        self.path = path or []
        if not path or len(path) < 2:
            if path is None:          # alvo inalcançável: sorteia outro
                self.goal = None
                self.wait = 5
            return None
        return path[1]

    def pick_goal(self, game, director):
        me, s = self.tile_pos, self.state
        if s == "CHASE":
            goal = self.chase_goal(game, director)
            if not self.sees and goal == me:      # chegou e não achou ninguém
                self.set_state("SEARCH")
                self.search_timer = self.profile["search"]
                s = "SEARCH"
            else:
                self.goal = goal
                return goal
        if s == "INVESTIGATE":
            if self.goal is not None and me != self.goal:
                return self.goal
            self.set_state("SEARCH")
            self.search_timer = self.profile["search"] // 2
            s = "SEARCH"
        if s == "SEARCH":
            if self.goal is not None and me == self.goal:
                self.goal = None
                self.wait = 20                     # "escaneia" o corredor
                return None
            if self.goal is None:
                self.goal = director.search_point(self, game)
            return self.goal
        if s == "REGROUP":
            return self.goal
        # PATROL
        if self.goal is not None and me == self.goal:
            self.goal = None
            self.wait = random.randint(25, 70)
            return None
        if self.goal is None:
            self.goal = director.patrol_point(self, game)
        return self.goal

    def chase_goal(self, game, director):
        lk = director.last_known
        if lk is None:
            return None
        if self.sees:
            tile, heading, age = game.player_tile(), director.player_dir, 0
        else:
            tile, heading, age = lk["tile"], lk["dir"], director.frame - lk["frame"]
        if self.role in ("hunter", "guard", "phantom", "sentinel"):
            return tile
        look = 9 if self.role == "scout" else min(8, 3 + self.profile["level"])
        return director.intercept_point(self, game, tile, heading, age, look) or tile

    # ---------- desenho ----------
    def draw_beam(self, surf, game):
        """Cone de visão frontal (mostra ao jogador por onde o drone enxerga)."""
        if self.delay > 0 or self.state == "REGROUP" or self.stun > 0:
            return
        fx, fy = self.facing
        t, n = self.current_tile(), 0
        while n < self.vision_range() and game.walkable(t[0] + fx, t[1] + fy):
            t = (t[0] + fx, t[1] + fy)
            n += 1
        if n == 0:
            return
        cx, cy = int(self.x + TILE // 2), int(self.y + TILE // 2 + HUD_H)
        length, width = n * TILE, 14
        if fx:
            rect = pygame.Rect(min(cx, cx + fx * length), cy - width // 2, length, width)
        else:
            rect = pygame.Rect(cx - width // 2, min(cy, cy + fy * length), width, length)
        beam = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        chasing = self.state in ("CHASE", "NOTICE")
        beam.fill((*(RED if chasing else self.color), 62 if chasing else 30))
        surf.blit(beam, rect.topleft)

    def draw(self, surf, anim=0):
        # Drone de segurança: sprite animado (Argon Neon Bits). Corpo/hélices = cor do papel,
        # olhos = cor do estado (azul = patrulha, dourado = busca, vermelho = caça).
        x, y = int(self.x + TILE // 2), int(self.y + TILE // 2 + HUD_H)
        eye = self.EYE[self.state]
        if self.state == "NOTICE" and (self.pulse // 4) % 2:
            eye = RED
        if self.stun > 0:                    # atordoado: olhos piscando em branco/azul
            eye = WHITE if (anim // 5) % 2 else (120, 150, 255)
        frames = drone_frames(self.color, eye)
        frame = frames[(anim // 7 + self.anim_off) % 4] if self.stun <= 0 else frames[0]
        surf.blit(frame, frame.get_rect(center=(x, y)))
        # Indicador de estado acima do drone.
        mark = {"NOTICE": ("!", WHITE), "CHASE": ("!", RED),
                "INVESTIGATE": ("?", GOLD), "SEARCH": ("?", GOLD)}.get(self.state)
        if self.stun > 0:
            mark = ("zZ", (150, 190, 255))
            for k in range(3):               # faíscas girando em volta do drone
                ang = anim / 6.0 + k * 2.1
                pygame.draw.circle(surf, (190, 225, 255),
                                   (int(x + 15 * math.cos(ang)), int(y + 11 * math.sin(ang))), 2)
        if mark:
            label = small_font.render(mark[0], True, mark[1])
            surf.blit(label, (x - label.get_width() // 2, y - 34))

    def draw_debug(self, surf):
        """F3: mostra estado, caminho planejado e objetivo de cada drone."""
        x, y = int(self.x + TILE // 2), int(self.y + TILE // 2 + HUD_H)
        pts = [(t[0] * TILE + TILE // 2, t[1] * TILE + TILE // 2 + HUD_H) for t in self.path]
        if len(pts) >= 2:
            pygame.draw.lines(surf, self.color, False, pts, 2)
        if self.goal:
            gx, gy = self.goal[0] * TILE + 6, self.goal[1] * TILE + 6 + HUD_H
            pygame.draw.rect(surf, self.color, (gx, gy, TILE - 12, TILE - 12), 2)
        txt = small_font.render(f"{self.role}:{self.state}", True, self.color)
        surf.blit(txt, (x - txt.get_width() // 2, y + 14))


BEST_FILE = os.path.join(DATA_DIR, "recorde.json")


def load_best():
    try:
        with open(BEST_FILE, "r", encoding="utf-8") as f:
            return int(json.load(f).get("fase", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def load_scores():
    """Placar: as 5 melhores partidas (fase alcançada, depois pontos)."""
    try:
        with open(BEST_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f).get("placar", [])
        out = [{"id": int(e["id"]), "fase": int(e["fase"]), "pontos": int(e["pontos"])} for e in raw]
        out.sort(key=lambda e: (e["fase"], e["pontos"]), reverse=True)
        return out[:5]
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return []


def save_scores(entries, best):
    try:
        with open(BEST_FILE, "w", encoding="utf-8") as f:
            json.dump({"fase": int(best), "placar": entries}, f)
    except OSError:
        pass


def draw_scoreboard(cx, y, entries, highlight=None, rows=5):
    """Desenha o PLACAR centralizado em cx, começando em y."""
    head = font.render("PLACAR", True, GOLD)
    screen.blit(head, (cx - head.get_width() // 2, y))
    if not entries:
        t = small_font.render("Nenhuma partida registrada ainda", True, GREY)
        screen.blit(t, (cx - t.get_width() // 2, y + 26))
        return
    for i, e in enumerate(entries[:rows]):
        mine = highlight is not None and e["id"] == highlight
        col = YELLOW if mine else (WHITE if i == 0 else GREY)
        line = f"{i + 1}.   Fase {e['fase']:>2}     {e['pontos']:>6} pts" + ("   < você" if mine else "")
        t = font.render(line, True, col)
        screen.blit(t, (cx - 130, y + 26 + i * 22))


# ============================================================
# ITENS TEMPORÁRIOS (equilíbrio das fases altas)
# Depois da fase ~8 os drones ficam mais rápidos que o jogador. Itens espalhados pelo
# mapa (a partir da fase 2) ajudam a compensar. Ajuste os números aqui, se quiser.
#   • ESCUDO ........ sprite "shield": drones não conseguem te capturar
#   • ACELERAÇÃO .... sprite "neon_vial": você fica mais rápido que qualquer drone
#   • PULSO ......... esfera de energia: fica guardado; ESPAÇO atordoa os drones próximos
# ============================================================
SHIELD_TIME = 8 * FPS       # duração do escudo (frames)
BOOST_TIME = 7 * FPS        # duração da aceleração
BOOST_SPEED = 3.0           # velocidade do jogador acelerado (normal = PLAYER_SPEED = 2.0)
PULSE_RADIUS = 7.5 * TILE   # alcance do pulso (pixels)
PULSE_STUN = 4 * FPS        # quanto tempo os drones ficam atordoados
MAX_PULSES = 2              # cargas de pulso que dá para guardar
ITEM_KINDS = ("shield", "speed", "pulse", "freeze", "silence")
ITEM_NAMES = {"shield": "Escudo", "speed": "Aceleração", "pulse": "Pulso",
              "freeze": "Relógio", "silence": "Silêncio"}
FREEZE_TIME = 3 * FPS       # RELÓGIO: congela todos os drones
SILENCE_TIME = 10 * FPS     # SILÊNCIO: seus barulhos não atraem drones
FLASH_FRAMES = 26           # duração do clarão vermelho ao ser pego
SHAKE_FRAMES = 26           # duração do tremor de tela ao ser pego


def item_count(level):
    """Quantos itens aparecem na fase (0 na fase 1; sobe com a dificuldade)."""
    if level < 2:
        return 0
    return 1 if level < 4 else 2 if level < 7 else 3 if level < 10 else 4


def make_code():
    """Código de 4 dígitos novo a cada fase (nunca todo igual, tipo 0000)."""
    while True:
        code = "".join(random.choice("0123456789") for _ in range(4))
        if len(set(code)) > 1:
            return code


class Particles:
    """Partículas quadradinhas (pixel art) que encolhem até sumir."""
    MAX = 600

    def __init__(self):
        self.items = []

    def clear(self):
        self.items = []

    def burst(self, x, y, colors, n=12, speed=2.5, life=(16, 32), size=(2.0, 4.0), gravity=0.0):
        if colors and isinstance(colors[0], int):      # uma cor só
            colors = [colors]
        for _ in range(n):
            if len(self.items) >= self.MAX:
                return
            ang = random.uniform(0, 2 * math.pi)
            sp = random.uniform(0.35, 1.0) * speed
            lf = random.randint(life[0], life[1])
            self.items.append([x, y, math.cos(ang) * sp, math.sin(ang) * sp, lf, lf,
                               random.choice(colors), random.uniform(size[0], size[1]), gravity])

    def update(self):
        alive = []
        for q in self.items:
            q[0] += q[2]
            q[1] += q[3]
            q[2] *= 0.95
            q[3] = q[3] * 0.95 + q[8]
            q[4] -= 1
            if q[4] > 0:
                alive.append(q)
        self.items = alive

    def draw(self, surf):
        for x, y, _vx, _vy, life, maxlife, col, size, _g in self.items:
            s = max(1, int(round(size * life / maxlife)))
            pygame.draw.rect(surf, col, (int(x - s / 2), int(y - s / 2), s, s))


def make_vignette():
    """Moldura vermelha que escurece as bordas (clarão quando o jogador é pego)."""
    surf = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
    depth = 80
    for i in range(depth):
        a = int(235 * (1 - i / depth) ** 2)
        pygame.draw.rect(surf, (255, 40, 60, a), (i, i, SCREEN_W - 2 * i, SCREEN_H - 2 * i), 1)
    return surf


VIGNETTE = make_vignette()


def apply_shake(amount):
    """Tremor de tela: desloca a imagem já desenhada por alguns pixels aleatórios."""
    if amount < 1:
        return
    ox, oy = random.randint(-amount, amount), random.randint(-amount, amount)
    snap = screen.copy()
    screen.fill(BLACK)
    screen.blit(snap, (ox, oy))


# ============================================================
# AVISOS NA TELA, CONQUISTAS, EFEITOS VISUAIS (apagão, alcance do pulso)
# ============================================================
TOASTS = []          # fila de avisos: [texto, frames restantes]
VOL_TOAST = [0]      # frames restantes do aviso de volume


def toast(text, frames=240):
    TOASTS.append([text, frames])


def draw_toasts():
    if not TOASTS:
        return
    text, left = TOASTS[0]
    surf = font.render(text, True, WHITE)
    w, h = surf.get_width() + 28, 30
    panel = pygame.Rect(SCREEN_W // 2 - w // 2, 36, w, h)
    pygame.draw.rect(screen, (28, 22, 8), panel, border_radius=8)
    pygame.draw.rect(screen, GOLD, panel, 2, border_radius=8)
    screen.blit(surf, (panel.x + 14, panel.y + (h - surf.get_height()) // 2))
    TOASTS[0][1] -= 1
    if TOASTS[0][1] <= 0:
        TOASTS.pop(0)


def draw_volume_toast():
    if VOL_TOAST[0] <= 0:
        return
    VOL_TOAST[0] -= 1
    text = f"Música {round(SETTINGS['music'] * 100)}%   Efeitos {round(SETTINGS['sfx'] * 100)}%"
    t = small_font.render(text, True, WHITE)
    panel = pygame.Rect(10, 36, t.get_width() + 20, 24)
    pygame.draw.rect(screen, (16, 22, 45), panel, border_radius=6)
    pygame.draw.rect(screen, WALL_EDGE, panel, 1, border_radius=6)
    screen.blit(t, (panel.x + 10, panel.y + 5))


def draw_overlays():
    draw_toasts()
    draw_volume_toast()


ACH_FILE = os.path.join(DATA_DIR, "conquistas.json")
ACH_INFO = {
    "fantasma":  ("Fantasma", "escape de uma fase sem nenhum drone te notar"),
    "intocavel": ("Intocável", "escape de uma fase sem ser capturado"),
    "fase5":     ("Veterano", "escape da fase 5"),
    "fase10":    ("Lenda da mansão", "escape da fase 10"),
    "chefe":     ("Caçador de chefes", "escape de uma fase com drone chefe"),
    "pulso10":   ("Eletrizante", "use 10 pulsos (soma todas as partidas)"),
}


class Achievements:
    """Conquistas simples, gravadas em conquistas.json."""

    def __init__(self):
        self.unlocked = set()
        self.counters = {}
        try:
            with open(ACH_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.unlocked = {k for k in raw.get("unlocked", []) if k in ACH_INFO}
            self.counters = {str(k): int(v) for k, v in raw.get("counters", {}).items()}
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def save(self):
        try:
            with open(ACH_FILE, "w", encoding="utf-8") as f:
                json.dump({"unlocked": sorted(self.unlocked), "counters": self.counters}, f)
        except OSError:
            pass

    def unlock(self, key):
        if key in self.unlocked or key not in ACH_INFO:
            return False
        self.unlocked.add(key)
        self.save()
        name, desc = ACH_INFO[key]
        toast(f"Conquista: {name} - {desc}")
        play("combo")
        return True

    def bump(self, name, n=1):
        self.counters[name] = self.counters.get(name, 0) + n     # gravado ao desbloquear/sair
        return self.counters[name]


ACH = Achievements()


def _make_pulse_ring(alpha_line, alpha_fill):
    r = int(PULSE_RADIUS)
    s = pygame.Surface((2 * r + 4, 2 * r + 4), pygame.SRCALPHA)
    pygame.draw.circle(s, (*CYAN, alpha_fill), (r + 2, r + 2), r)
    pygame.draw.circle(s, (*CYAN, alpha_line), (r + 2, r + 2), r, 2)
    return s


PULSE_RING_IDLE = _make_pulse_ring(55, 8)      # alcance do pulso (você tem carga)
PULSE_RING_HOT = _make_pulse_ring(170, 30)     # ...e há um drone dentro do alcance
HALO_CACHE = {}


def _make_danger_surface():
    s = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
    for i in range(28):
        a = int(200 * (1 - i / 28.0) ** 2)
        pygame.draw.rect(s, (255, 40, 60, a), (i, i, SCREEN_W - 2 * i, SCREEN_H - 2 * i), 1)
    return s


DANGER_SURF = _make_danger_surface()
PLAYER_GLOW = pygame.Surface((TILE + 14, TILE + 14), pygame.SRCALPHA)
pygame.draw.circle(PLAYER_GLOW, (*YELLOW, 48), (PLAYER_GLOW.get_width() // 2, PLAYER_GLOW.get_height() // 2), 17)
_HOLE_CACHE = {}
_DARK_CACHE = {}


def light_hole(r):
    """Círculo de luz com borda suave (usado no apagão)."""
    h = _HOLE_CACHE.get(r)
    if h is None:
        h = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        for rr in range(r, 0, -3):
            a = int(255 * min(1.0, (1.0 - rr / r) * 2.4))
            pygame.draw.circle(h, (255, 255, 255, a), (r, r), rr)
        _HOLE_CACHE[r] = h
    return h


def draw_blackout(px, py, radius_tiles, drones):
    """Escurece a tela deixando só um círculo de luz ao redor do jogador."""
    r = int(radius_tiles * TILE)
    mask = _DARK_CACHE.get("mask")
    if mask is None:
        mask = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        _DARK_CACHE["mask"] = mask
    mask.fill((0, 0, 6, 238))
    hole = light_hole(r)
    mask.blit(hole, hole.get_rect(center=(px, py)), special_flags=pygame.BLEND_RGBA_SUB)
    screen.blit(mask, (0, 0))
    for d in drones:        # os olhos dos drones continuam visíveis no escuro (para ser justo)
        if d.delay <= 0:
            c = (int(d.x + TILE // 2), int(d.y + TILE // 2 + HUD_H))
            pygame.draw.circle(screen, d.EYE[d.state], c, 5, 2)


JOYSTICKS = []
JOY_ADDED = getattr(pygame, "JOYDEVICEADDED", -1)
JOY_REMOVED = getattr(pygame, "JOYDEVICEREMOVED", -1)


def _joy_id(j):
    return j.get_instance_id() if hasattr(j, "get_instance_id") else j.get_id()


def add_joystick(index):
    try:
        j = pygame.joystick.Joystick(index)
        j.init()
        if all(_joy_id(x) != _joy_id(j) for x in JOYSTICKS):
            JOYSTICKS.append(j)
    except pygame.error:
        pass


def remove_joystick(instance_id):
    JOYSTICKS[:] = [j for j in JOYSTICKS if _joy_id(j) != instance_id]


try:
    pygame.joystick.init()
    for _n in range(pygame.joystick.get_count()):
        add_joystick(_n)
except pygame.error:
    pass


def joystick_direction():
    """Direção do D-pad ou do analógico esquerdo (None se nada pressionado)."""
    for j in JOYSTICKS:
        try:
            if j.get_numhats() > 0:
                hx, hy = j.get_hat(0)
                if hx or hy:
                    return (hx, 0) if hx else (0, -hy)
            if j.get_numaxes() >= 2:
                ax, ay = j.get_axis(0), j.get_axis(1)
                if max(abs(ax), abs(ay)) > 0.5:
                    return ((1 if ax > 0 else -1), 0) if abs(ax) >= abs(ay) else (0, (1 if ay > 0 else -1))
        except pygame.error:
            continue
    return None


def translate_joy(event, in_menu):
    """Converte botões do controle em teclas (assim o resto do jogo não precisa saber de controle)."""
    t = event.type
    if t == getattr(pygame, "JOYBUTTONDOWN", -2):
        if in_menu:
            k = {0: pygame.K_RETURN, 7: pygame.K_RETURN, 1: pygame.K_ESCAPE}.get(event.button)
        else:   # A interage, X/B pulso, Y próxima fase, LB reinicia, Start pausa, Back menu
            k = {0: KEYMAP["interact"][0], 1: KEYMAP["pulse"][0], 2: KEYMAP["pulse"][0],
                 3: pygame.K_n, 4: pygame.K_r, 7: KEYMAP["pause"][0], 6: pygame.K_ESCAPE}.get(event.button)
    elif t == getattr(pygame, "JOYHATMOTION", -3) and in_menu:
        k = {(0, 1): pygame.K_UP, (0, -1): pygame.K_DOWN,
             (-1, 0): pygame.K_LEFT, (1, 0): pygame.K_RIGHT}.get(tuple(event.value))
    else:
        return event
    if k is None:
        return None
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode="", mod=0)


INPUT_BUFFER = 24     # frames em que uma curva pedida fica "guardada" esperando a esquina
ALIGN_TOL = 6         # tolerância (px) para virar perto do centro do tile


TURN_SPEED = 0.045     # giro com teclado (rad/frame)
MOUSE_SENS = 0.0028    # giro com mouse (rad/pixel)
PLAYER_RADIUS = 9.0    # raio de colisão do jogador (px)

R3D = render3d.Renderer({
    "TILE": TILE, "WALL_TILES": WALL_TILES, "KEY": KEY_IMG, "NOTE": NOTE_IMG,
    "CONSOLE": CONSOLE_IMG, "CONSOLE_ON": CONSOLE_ON_IMG, "EXIT_LOCKED": EXIT_LOCKED_IMG,
    "EXIT_OPEN": EXIT_OPEN_IMG, "HEAL": HEAL_IMG, "DOT": DOT_IMG, "ORB_FRAMES": ORB_FRAMES,
    "drone_frames": drone_frames, "small_font": small_font,
    "item_imgs": {"shield": SHIELD_IMG, "speed": VIAL_IMG, "freeze": CLOCK_IMG, "silence": MUTE_IMG},
})


class Game:
    def __init__(self):
        self.diff = current_difficulty()
        self.show_map = True             # F2 liga/desliga o minimapa
        self.mouse_turn = 0.0
        self.seen_hints = set()          # dicas do tutorial já mostradas nesta partida
        self.stats = {"pulses": 0, "stunned": 0, "catches": 0, "frames": 0}
        self.level = START_LEVEL
        self.best = load_best()
        self.scores = load_scores()
        self.run_id = random.getrandbits(40)
        self.eat_streak = 0
        self.eat_last = -99999
        self.combo = 1
        self.brain = AdaptiveBrain()
        self.debug_ai = False
        self.total_score = 0
        self.particles = Particles()
        self.pulse_charges = 0      # pulsos guardados (passam de fase em fase)
        self.reset()

    def note_best(self):
        """Grava esta partida no placar (atualiza a mesma entrada durante a partida)."""
        if self.score <= 0 and self.level <= 1:
            return
        entries = [e for e in load_scores() if e["id"] != self.run_id]
        entries.append({"id": self.run_id, "fase": self.level, "pontos": self.score})
        entries.sort(key=lambda e: (e["fase"], e["pontos"]), reverse=True)
        self.scores = entries[:5]
        self.best = max(self.best, self.level)
        save_scores(self.scores, self.best)

    def advance_level(self):
        self.brain.save()
        self.note_best()
        play("level")
        old_score = self.score
        old_lives = self.player.lives
        self.level += 1
        self.reset()                         # novo mapa, novo bilhete e novo código
        self.score = old_score + 250
        self.player.lives = old_lives
        self.invincible = 180
        if self.level <= len(RAW_MAPS):
            self.say(f"FASE {self.level}! Os drones aprenderam com seus movimentos.", 300)
        else:
            self.say(f"FASE {self.level}! Nova planta da mansão e drones mais perigosos.", 300)
        if is_boss_level(self.level):
            self.say(f"FASE {self.level}: DRONE CHEFE roxo! Ele resiste ao pulso.", 360)
        elif self.blackout:
            self.say(f"FASE {self.level}: APAGÃO! Você só enxerga perto de si.", 360)


    def reset(self):
        self.grid, self.map_index = build_level_grid(self.level)
        self.brain.set_map(self.map_index, fresh=(self.map_index == "gen"))
        self.win_timer = 0
        self.player = type("Player", (), {})()
        self.player.x, self.player.y = 1*TILE, 1*TILE
        self.player.direction = (0,0)
        self.player.next_direction = (0,0)
        self.player.mouth = 0
        self.player.lives = 3
        self.score = getattr(self, 'score', 0) if self.level > 1 else 0
        self.has_key = False
        self.console_open = False
        self.exit_open = False
        self.game_over = False
        self.won = False
        self.message = "Ache a chave, o bilhete com o código e o console!  E interagir • P pausa"
        self.message_timer = 420
        self.invincible = 120
        self.player.buffer = 0              # frames restantes da curva guardada
        self.checkpoints = deque(maxlen=40) # pontos seguros recentes (para o respawn)
        self.checkpoint_timer = 0
        self.heal_hint = False
        self.level_catches = 0
        self.level_chased = False
        self.blackout = is_blackout_level(self.level)
        self.arrow_timer = 0
        self.arrow_dir = None
        # --- efeitos e itens desta fase ---
        self.anim = 0                  # relógio de animação (para quando o jogo está pausado)
        self.shake = 0
        self.flash = 0
        self.rings = []                # ondas de choque do pulso: [x, y, idade]
        self.shield_t = 0
        self.boost_t = 0
        self.silent_t = 0
        self.level_frames = 0
        self.win_bonus = (0, 0)
        self.danger = 0.0
        self.particles.clear()
        # --- escape room: o código muda a cada fase e fica num bilhete escondido no mapa ---
        self.code = make_code()
        self.has_note = False
        self.code_prompt = False       # interact() pede ao laço principal que abra o teclado
        self.note_pos = (-99, -99)
        self.pickups = []              # [{"kind": ..., "pos": (x, y)}]
        self.dots = set()
        self.key_pos = (1,19)
        self.console_pos = (15,19)
        self.exit_pos = (29,17)
        self.heal_pos = (27,19)
        for y, row in enumerate(self.grid):
            for x, ch in enumerate(row):
                if ch == '.':
                    self.dots.add((x,y))
                    self.grid[y][x] = ' '
                elif ch == 'P':
                    self.player.x, self.player.y = x*TILE, y*TILE
                    self.grid[y][x] = ' '
                elif ch == 'K':
                    self.key_pos = (x,y)
                    self.grid[y][x] = ' '
                elif ch == 'C':
                    self.console_pos = (x,y)
                    self.grid[y][x] = ' '
                elif ch == 'E':
                    self.exit_pos = (x,y)
                    self.grid[y][x] = ' '
                elif ch == 'H':
                    self.heal_pos = (x,y)
                    self.grid[y][x] = ' '
        self.wall_layer = build_wall_layer(self.grid, self.level)
        self.door_tiles = [(x, y) for y, row in enumerate(self.grid) for x, ch in enumerate(row) if ch == 'D']
        self.spawn_tile = (round(self.player.x / TILE), round(self.player.y / TILE))
        self.player.angle = 0.0                 # câmera olha para o primeiro corredor livre
        for ddx, ddy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            if self.walkable(self.spawn_tile[0] + ddx, self.spawn_tile[1] + ddy):
                self.player.angle = math.atan2(ddy, ddx)
                break
        self.mouse_turn = 0.0
        self.explored = set()
        self.place_extras()
        self.director = DroneDirector(self)
        self.drones = self.director.drones
        self.total_dots = len(self.dots)

    def place_extras(self):
        """Esconde o bilhete e espalha os itens temporários em tiles alcançáveis SEM a chave
        (nada fica preso atrás da porta trancada)."""
        reach = Nav.flood(self, self.spawn_tile)
        taken = {self.spawn_tile, self.key_pos, self.console_pos, self.exit_pos, self.heal_pos}
        taken.update(self.door_tiles)

        def far_enough(tile, others, gap):
            return all(Nav.manhattan(tile, o) >= gap for o in others)

        # Bilhete: longe do início, de preferência num beco sem saída, longe da chave e do console.
        base = [t for t in reach if t not in taken and reach[t] >= 10
                and far_enough(t, (self.key_pos, self.console_pos), 6)]
        dead_ends = [t for t in base if len(Nav.neighbors(self, t)) == 1]
        pool = dead_ends or base or [t for t in reach if t not in taken]
        if pool:
            self.note_pos = random.choice(sorted(pool))
            taken.add(self.note_pos)

        # Itens: espalhados, variando o tipo (embaralha a lista e repete se precisar).
        kinds = []
        for _ in range(item_count(self.level)):
            if not kinds:
                kinds = list(ITEM_KINDS)
                random.shuffle(kinds)
            kind = kinds.pop()
            options = [t for t in reach if t not in taken and reach[t] >= 8
                       and far_enough(t, [p["pos"] for p in self.pickups] + [self.note_pos], 7)]
            if not options:
                options = [t for t in reach if t not in taken and reach[t] >= 4]
            if not options:
                break
            pos = random.choice(sorted(options))
            taken.add(pos)
            self.pickups.append({"kind": kind, "pos": pos})

        for tile in taken:                  # nada de pontinho embaixo de bilhete/item
            self.dots.discard(tile)

    def finish_session(self):
        """Salva aprendizado da IA e placar (usado ao sair, reiniciar ou voltar ao menu)."""
        self.brain.save()
        self.note_best()
        ACH.save()

    def respawn_tile(self):
        """Onde voltar depois de ser pego: último ponto seguro (longe dos drones) ou o início."""
        if self.diff["safe_respawn"]:
            live = [d.current_tile() for d in self.drones if d.delay <= 0]
            for tile in reversed(self.checkpoints):
                if self.walkable(*tile) and all(Nav.manhattan(tile, t) >= 10 for t in live):
                    return tile
        return self.spawn_tile

    HINTS = {
        "key": "Aquela é a CHAVE dourada. Ao pegá-la, o alarme dispara e os drones vêm!",
        "console": "Este é o CONSOLE. Fique perto dele e aperte a tecla de interagir.",
        "drone": "Um drone te viu! Vire numa esquina para quebrar a linha de visão.",
        "shield": "ESCUDO: por alguns segundos os drones não conseguem te pegar.",
        "speed": "ACELERAÇÃO: você fica mais rápido que os drones por um tempo.",
        "pulse": "PULSO: fica guardado. Use a tecla de pulso para atordoar drones por perto.",
        "freeze": "RELÓGIO: congela todos os drones por alguns segundos.",
        "silence": "SILÊNCIO: seus barulhos (chave, console) não chamam os drones.",
    }

    def hint(self, key):
        """Mostra uma dica de tutorial uma única vez por partida."""
        if key in self.seen_hints:
            return
        self.seen_hints.add(key)
        self.say(self.HINTS[key], 280)

    def tutorial_update(self):
        pt = self.player_tile()
        if not self.has_key and Nav.manhattan(pt, self.key_pos) <= 4:
            self.hint("key")
        elif self.has_key and not self.console_open and Nav.manhattan(pt, self.console_pos) <= 3:
            self.hint("console")
        for p in self.pickups:
            if Nav.manhattan(pt, p["pos"]) <= 4:
                self.hint(p["kind"])
        if any(d.delay <= 0 and d.stun <= 0 and d.state in ("CHASE", "NOTICE") for d in self.drones):
            self.hint("drone")

    def on_level_complete(self):
        secs = self.level_frames // FPS
        time_bonus = max(0, 90 - secs) * 3                 # rápido = mais pontos
        ghost_bonus = 200 if not self.level_chased else 0  # sem ser notado = bônus
        self.win_bonus = (time_bonus, ghost_bonus)
        self.score += time_bonus + ghost_bonus
        if not self.level_chased:
            ACH.unlock("fantasma")
        if self.level_catches == 0:
            ACH.unlock("intocavel")
        if self.level >= 5:
            ACH.unlock("fase5")
        if self.level >= 10:
            ACH.unlock("fase10")
        if is_boss_level(self.level):
            ACH.unlock("chefe")

    def walkable(self, tx, ty):
        if not (0 <= tx < COLS and 0 <= ty < ROWS):
            return False
        ch = self.grid[ty][tx]
        if ch == '#':
            return False
        if ch == 'D' and not self.has_key:
            return False
        return True

    def player_tile(self):
        return round(self.player.x / TILE), round(self.player.y / TILE)

    def current_objective(self):
        """Próximo objetivo do jogador (os drones sabem disso: a mansão é deles)."""
        if not self.has_key:
            return self.key_pos
        if not self.console_open:
            return self.console_pos
        return self.exit_pos

    def say(self, text, duration=210):
        self.message, self.message_timer = text, duration

    def try_move(self, direction):
        # Só troca de direção quando o personagem está alinhado ao centro da casa.
        if direction == (0,0):
            return
        px, py = self.player.x, self.player.y
        tx, ty = round(px / TILE), round(py / TILE)
        aligned_x = abs(px - tx*TILE) <= ALIGN_TOL
        aligned_y = abs(py - ty*TILE) <= ALIGN_TOL
        if direction[0] != 0 and aligned_y:
            self.player.y = ty*TILE
            if self.walkable(tx + direction[0], ty):
                self.player.direction = direction
        elif direction[1] != 0 and aligned_x:
            self.player.x = tx*TILE
            if self.walkable(tx, ty + direction[1]):
                self.player.direction = direction

    # ---------- movimento 3D (livre, com giro) ----------
    def free_at(self, cx, cy, r=PLAYER_RADIUS):
        for ox in (-r, r):
            for oy in (-r, r):
                if not self.walkable(int((cx + ox) // TILE), int((cy + oy) // TILE)):
                    return False
        return True

    def try_step(self, dx, dy):
        """Anda dx,dy (px) deslizando nas paredes."""
        p = self.player
        cx, cy = p.x + TILE / 2, p.y + TILE / 2
        if self.free_at(cx + dx, cy):
            cx += dx
        if self.free_at(cx, cy + dy):
            cy += dy
        p.x, p.y = cx - TILE / 2, cy - TILE / 2

    def move_free(self):
        p = self.player
        keys = pygame.key.get_pressed()
        turn = (1 if key_held(keys, "right") else 0) - (1 if key_held(keys, "left") else 0)
        fwd = (1 if key_held(keys, "up") else 0) - (1 if key_held(keys, "down") else 0)
        jd = joystick_direction()
        if jd:
            turn += jd[0]
            fwd -= jd[1]
        turn = max(-1, min(1, turn))
        fwd = max(-1, min(1, fwd))
        p.angle = (p.angle + turn * TURN_SPEED + self.mouse_turn * MOUSE_SENS) % (2 * math.pi)
        self.mouse_turn = 0.0
        if fwd:
            sp = (BOOST_SPEED if self.boost_t > 0 else PLAYER_SPEED) * (1.0 if fwd > 0 else 0.6)
            ca, sa = math.cos(p.angle) * fwd, math.sin(p.angle) * fwd
            self.try_step(ca * sp, sa * sp)
            if abs(ca) > abs(sa):                       # direção "de grade" (usada pela IA)
                p.direction = (1 if ca > 0 else -1, 0)
            else:
                p.direction = (0, 1 if sa > 0 else -1)
        else:
            p.direction = (0, 0)

    def reveal_map(self):
        """Minimapa: revela o entorno e os corredores em linha reta à frente."""
        tx, ty = self.player_tile()
        for ddx in range(-2, 3):
            for ddy in range(-2, 3):
                self.explored.add((tx + ddx, ty + ddy))
        for ddx, ddy in DIRS4:
            x, y = tx, ty
            for _ in range(6):
                x += ddx
                y += ddy
                self.explored.add((x, y))
                if not self.walkable(x, y):
                    break

    def interact(self):
        tx, ty = round(self.player.x/TILE), round(self.player.y/TILE)
        near = lambda pos: abs(tx-pos[0])+abs(ty-pos[1]) <= 1
        if near(self.console_pos):
            if not self.has_key:
                play("deny")
                self.say("O console está bloqueado. Procure a chave dourada!")
            elif self.console_open:
                play("tick")
                self.say("Console ativado! A saída foi destrancada.")
            else:
                # O código NÃO aparece aqui: ele está num bilhete escondido no mapa.
                if self.has_note:
                    self.say("Digite o código do bilhete e aperte Enter.", 300)
                else:
                    self.say("O console pede 4 dígitos. Procure o bilhete escondido no mapa!", 300)
                self.code_prompt = True      # o laço principal abre o teclado numérico
        elif near(self.exit_pos):
            if self.exit_open:
                self.won = True
                self.on_level_complete()
                play("win")
                self.note_best()
                self.brain.save()
                ex, ey = self.center_px(self.exit_pos)
                self.particles.burst(ex, ey, [GREEN, WHITE, GOLD, CYAN], n=70, speed=4.2,
                                     life=(30, 60), size=(3, 6))
                self.rings.append([ex, ey, 0, GREEN, 90])
                self.say(f"Você escapou da fase {self.level}!", 99999)
            else:
                play("deny")
                self.say("A saída está selada. Ative o console primeiro.")
        else:
            play("deny")
            self.say("Nada para interagir aqui. Procure a chave, o bilhete e o console.")

    # ---------- efeitos / itens ----------
    def center_px(self, tile):
        return tile[0] * TILE + TILE // 2, tile[1] * TILE + TILE // 2 + HUD_H

    def player_center(self):
        return int(self.player.x + TILE // 2), int(self.player.y + TILE // 2 + HUD_H)

    def shake_amount(self):
        return min(9, (self.shake + 2) // 3)

    def fx_update(self):
        self.particles.update()
        for r in self.rings:
            r[2] += 1
        self.rings = [r for r in self.rings if r[2] < 24]
        if self.shake > 0:
            self.shake -= 1
        if self.flash > 0:
            self.flash -= 1

    def collect_pickup(self, pickup):
        kind, pos = pickup["kind"], pickup["pos"]
        self.pickups.remove(pickup)
        x, y = self.center_px(pos)
        self.score += 30
        if kind == "shield":
            self.shield_t = SHIELD_TIME
            play("shield_on")
            self.say(f"ESCUDO! Os drones não conseguem te pegar por {SHIELD_TIME // FPS} s.", 240)
            cols = [(90, 210, 255), WHITE, CYAN]
        elif kind == "speed":
            self.boost_t = BOOST_TIME
            play("boost")
            self.say(f"ACELERAÇÃO! Você está mais rápido que os drones por {BOOST_TIME // FPS} s.", 240)
            cols = [PINK, (255, 200, 255), PURPLE]
        elif kind == "freeze":
            for d in self.drones:
                if d.delay <= 0:
                    d.stun = max(d.stun, FREEZE_TIME // 2 if d.boss else FREEZE_TIME)
            play("freeze")
            self.say(f"RELÓGIO! Todos os drones congelaram por {FREEZE_TIME // FPS} s.", 240)
            cols = [(150, 215, 255), WHITE, CYAN]
        elif kind == "silence":
            self.silent_t = SILENCE_TIME
            play("silence")
            self.say(f"SILÊNCIO! Seus barulhos não atraem drones por {SILENCE_TIME // FPS} s.", 240)
            cols = [(200, 200, 230), WHITE, GREY]
        else:
            self.pulse_charges = min(MAX_PULSES, self.pulse_charges + 1)
            play("pickup")
            self.say(f"PULSO guardado! Aperte {key_label('pulse')} para atordoar os drones por perto.", 270)
            cols = [CYAN, WHITE, (112, 240, 248)]
        self.particles.burst(x, y, cols, n=22, speed=3.2, life=(20, 40), size=(2, 5))
        self.rings.append([x, y, 0, cols[0], 44])

    def fire_pulse(self):
        """ESPAÇO: onda de energia que atordoa (para e cega) os drones próximos."""
        if self.game_over or self.won:
            return
        if self.pulse_charges <= 0:
            play("deny")
            self.say("Sem pulso guardado. Pegue uma esfera de energia no mapa.", 150)
            return
        self.pulse_charges -= 1
        self.stats["pulses"] += 1
        if ACH.bump("pulses") >= 10:
            ACH.unlock("pulso10")
        px, py = self.player_center()
        hit = 0
        for d in self.drones:
            if d.delay > 0:
                continue
            dx, dy = d.x + TILE // 2 - px, d.y + TILE // 2 + HUD_H - py
            if math.hypot(dx, dy) <= PULSE_RADIUS:
                d.stun = max(d.stun, PULSE_STUN // 2 if d.boss else PULSE_STUN)
                hit += 1
                self.stats["stunned"] += 1
                self.particles.burst(int(d.x + TILE // 2), int(d.y + TILE // 2 + HUD_H),
                                     [WHITE, CYAN, (150, 190, 255)], n=14, speed=3.0, life=(18, 36))
        self.rings.append([px, py, 0, CYAN, int(PULSE_RADIUS)])
        self.rings.append([px, py, 4, WHITE, int(PULSE_RADIUS * 0.7)])
        self.particles.burst(px, py, [CYAN, WHITE], n=24, speed=4.0, life=(14, 30))
        self.shake = max(self.shake, 10)
        play("zap")
        if hit:
            self.say(f"PULSO! {hit} drone(s) atordoado(s) por {PULSE_STUN // FPS} s.", 180)
        else:
            self.say("Pulso disparado, mas não havia drones por perto.", 150)

    def update(self):
        self.anim += 1
        self.fx_update()                     # partículas, ondas e tremor continuam até na vitória
        if self.game_over or self.won:
            return
        self.stats["frames"] += 1
        self.level_frames += 1
        self.move_free()
        self.reveal_map()
        self.brain.observe(self)
        self.brain.tick()
        dx, dy = self.player.direction
        speed = BOOST_SPEED if self.boost_t > 0 else PLAYER_SPEED

        tx, ty = round(self.player.x/TILE), round(self.player.y/TILE)
        if (tx,ty) in self.dots:
            self.dots.remove((tx,ty))
            now = pygame.time.get_ticks()
            self.eat_streak = self.eat_streak + 1 if now - self.eat_last < 700 else 0
            self.eat_last = now
            self.combo = 1 + min(3, self.eat_streak // 20)     # x2 a cada 20 pontinhos seguidos (até x4)
            self.score += 10 * self.combo
            play(f"eat{EAT_PATTERN[self.eat_streak % len(EAT_PATTERN)]}")
            if self.eat_streak and self.eat_streak % 14 == 0:
                play("combo")      # a cada volta completa da escala: brilho extra
            cx, cy = self.center_px((tx, ty))      # faíscas ao comer
            self.particles.burst(cx, cy, [(112, 240, 248), (240, 128, 224), WHITE], n=4, speed=1.6,
                                 life=(10, 20), size=(1.5, 3))
        if not self.has_key and (tx,ty) == self.key_pos:
            self.has_key = True
            self.score += 100
            self.say("Chave encontrada! Um alarme soou: drones a caminho. Vá ao console!", 260)
            self.director.report_noise(self, (tx, ty), 14)
            play("key")
            play("alarm")
            kx, ky = self.center_px((tx, ty))
            self.particles.burst(kx, ky, [GOLD, YELLOW, WHITE], n=44, speed=4.0, life=(24, 52), size=(2, 5))
            self.rings.append([kx, ky, 0, GOLD, 70])
        if not self.has_note and (tx,ty) == self.note_pos:
            self.has_note = True
            self.score += 50
            self.say(f"Bilhete encontrado! O código do console é {self.code}  (fica no canto da tela).", 420)
            play("note")
            nx_, ny_ = self.center_px((tx, ty))
            self.particles.burst(nx_, ny_, [WHITE, (238, 232, 205), GOLD], n=26, speed=3.0, life=(20, 44))
            self.rings.append([nx_, ny_, 0, WHITE, 50])
        for pickup in list(self.pickups):
            if (tx,ty) == pickup["pos"]:
                self.collect_pickup(pickup)
        if (tx,ty) == self.heal_pos and self.player.lives < 3:
            self.player.lives += 1
            play("heal")
            hx, hy = self.center_px(self.heal_pos)
            self.particles.burst(hx, hy, [GREEN, WHITE, (170, 255, 190)], n=26, speed=3.0, life=(20, 46))
            self.heal_pos = (-99,-99)
            self.say("Você encontrou uma vida extra!")
        elif (tx,ty) == self.heal_pos and not self.heal_hint:
            self.heal_hint = True
            self.say("Vidas cheias! Volte aqui quando precisar de uma vida extra.", 180)
        if self.invincible > 0:
            self.invincible -= 1
        # Itens temporários: contagem regressiva e rastro da aceleração.
        if self.shield_t > 0:
            self.shield_t -= 1
            if self.shield_t == 0:
                play("shield_off")
                self.say("O escudo acabou!", 120)
        if self.silent_t > 0:
            self.silent_t -= 1
        if self.boost_t > 0:
            self.boost_t -= 1
            if (dx or dy) and self.anim % 3 == 0:
                bx, by = self.player_center()
                self.particles.burst(bx, by, [PINK, (255, 200, 255), PURPLE], n=2, speed=0.8,
                                     life=(10, 18), size=(2, 4))
            if self.boost_t == 0:
                self.say("A aceleração acabou.", 120)
        self.director.update(self)
        self.tutorial_update()
        if any(d.delay <= 0 and d.stun <= 0 and d.state in ("CHASE", "NOTICE") for d in self.drones):
            self.level_chased = True
        else:
            self.checkpoint_timer += 1
            if self.checkpoint_timer >= 45:          # a cada ~0,75 s sem perigo, guarda o ponto
                self.checkpoint_timer = 0
                pt_ = self.player_tile()
                if self.walkable(*pt_) and (not self.checkpoints or self.checkpoints[-1] != pt_):
                    self.checkpoints.append(pt_)
        if self.diff["arrow"]:
            self.arrow_timer -= 1
            if self.arrow_timer <= 0:
                self.arrow_timer = 15
                path = Nav.astar(self, self.player_tile(), self.current_objective())
                if path and len(path) > 1:
                    self.arrow_dir = (path[1][0] - path[0][0], path[1][1] - path[0][1])
                else:
                    self.arrow_dir = None
        # Batimento cardíaco: acelera quando um drone em perseguição está perto.
        pt = self.player_tile()
        near = [Nav.manhattan(d.current_tile(), pt) for d in self.drones
                if d.delay <= 0 and d.state in ("CHASE", "NOTICE") and d.stun <= 0]
        if near and min(near) <= 7:
            play("beat", cooldown=220 + 60 * min(near))
        self.danger += ((1.0 if near and min(near) <= 8 else 0.0) - self.danger) * 0.08
        for drone in self.drones:
            if (math.hypot(self.player.x-drone.x, self.player.y-drone.y) < 21
                    and self.invincible <= 0 and drone.state != "REGROUP" and drone.stun <= 0):
                if self.shield_t > 0:
                    # Escudo: o drone bate e fica tonto por um instante; você não perde vida.
                    drone.stun = max(drone.stun, 40)
                    play("shield_hit", cooldown=200)
                    sx, sy = self.player_center()
                    self.particles.burst(sx, sy, [(90, 210, 255), WHITE], n=10, speed=3.2, life=(10, 22))
                    continue
                self.brain.record_catch(self.player_tile())
                self.stats["catches"] += 1
                self.level_catches += 1
                self.player.lives -= 1
                self.invincible = 120
                # Impacto: tremor de tela, clarão vermelho e fagulhas.
                hx, hy = self.player_center()
                self.shake = SHAKE_FRAMES
                self.flash = FLASH_FRAMES
                self.particles.burst(hx, hy, [RED, ORANGE, WHITE, YELLOW], n=40, speed=4.4,
                                     life=(22, 48), size=(2, 6))
                rx, ry = self.respawn_tile()
                self.player.x, self.player.y = rx * TILE, ry * TILE
                self.player.buffer = 0
                self.player.direction = (0,0)
                self.player.next_direction = (0,0)
                self.director.on_player_caught(self)
                self.say("Um drone detectou você! Cuidado.", 180)
                play("hit")
                if self.player.lives <= 0:
                    self.game_over = True
                    play("gameover")
                    self.note_best()
                    self.brain.save()
                break
        if self.message_timer > 0:
            self.message_timer -= 1
        self.player.mouth += 1

    def draw(self):
        R3D.render(self, screen)
        if self.danger > 0.03 and not (self.game_over or self.won):    # borda vermelha: perigo perto
            DANGER_SURF.set_alpha(int(255 * min(1.0, self.danger) * (0.7 + 0.3 * math.sin(self.anim / 5.0))))
            screen.blit(DANGER_SURF, (0, 0))

        # Mensagem: faixa discreta sobre a parede de cima.
        if self.message_timer > 0 and self.message:
            msg = font.render(self.message, True, WHITE)
            panel = pygame.Rect(190, 3, SCREEN_W-380, 27)
            pygame.draw.rect(screen, (16,22,45), panel, border_radius=8)
            pygame.draw.rect(screen, WALL_EDGE, panel, 1, border_radius=8)
            screen.blit(msg, (panel.centerx-msg.get_width()//2, panel.y+6))
        self.draw_hud()
        if self.flash > 0:
            VIGNETTE.set_alpha(int(255 * self.flash / FLASH_FRAMES))
            screen.blit(VIGNETTE, (0, 0))
        if self.game_over or self.won:
            overlay = pygame.Surface((SCREEN_W,SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0,0,0,190))
            screen.blit(overlay,(0,0))
            text = f"FASE {self.level} CONCLUÍDA!" if self.won else f"FIM DE JOGO — você chegou à fase {self.level}"
            color = GREEN if self.won else RED
            t = title_font.render(text, True, color)
            sub_text = (f"Fase {self.level + 1} começando...   |   N: pular   R: reiniciar" if self.won
                        else "Pressione R para jogar novamente")
            sub = big_font.render(sub_text, True, WHITE)
            score_t = big_font.render(f"Pontos: {self.score}", True, YELLOW)
            if self.won:
                screen.blit(t,(SCREEN_W//2-t.get_width()//2,SCREEN_H//2-60))
                screen.blit(score_t,(SCREEN_W//2-score_t.get_width()//2,SCREEN_H//2-5))
                screen.blit(sub,(SCREEN_W//2-sub.get_width()//2,SCREEN_H//2+40))
                tb, gb = self.win_bonus
                bon = small_font.render(f"Bônus:  tempo +{tb}    sem ser notado +{gb}", True, CYAN)
                screen.blit(bon, (SCREEN_W//2 - bon.get_width()//2, SCREEN_H//2 + 80))
            else:
                screen.blit(t,(SCREEN_W//2-t.get_width()//2,90))
                screen.blit(score_t,(SCREEN_W//2-score_t.get_width()//2,150))
                screen.blit(sub,(SCREEN_W//2-sub.get_width()//2,195))
                secs = self.stats["frames"] // FPS
                resumo = small_font.render(
                    f"Tempo {secs // 60}:{secs % 60:02d}   •   Pulsos usados {self.stats['pulses']}   •   "
                    f"Drones atordoados {self.stats['stunned']}   •   Capturas {self.stats['catches']}", True, CYAN)
                screen.blit(resumo, (SCREEN_W//2 - resumo.get_width()//2, 238))
                draw_scoreboard(SCREEN_W//2, 270, self.scores, highlight=self.run_id)
            if self.won:                 # confete por cima do escurecimento
                self.particles.draw(screen)

    def draw_hud(self):
        """Barra inferior (por cima da parede de baixo): vidas, chave, console, bilhete, itens, pontos."""
        bar_y = SCREEN_H - TILE
        cy = bar_y + TILE // 2
        screen.blit(HUD_BAR, (0, bar_y))
        x = 10
        for i in range(3):                                   # vidas = capacetes
            screen.blit(LIFE_IMG if i < self.player.lives else LIFE_DIM_IMG, (x, cy - 12))
            x += 27
        x += 10
        screen.blit(KEY_ICON if self.has_key else KEY_ICON_DIM, (x, cy - 11))
        x += 26
        screen.blit(CONSOLE_ICON_ON if self.console_open else
                    (CONSOLE_ICON if self.has_key else CONSOLE_ICON_DIM), (x, cy - 12))
        x += 32
        screen.blit(NOTE_ICON if self.has_note else NOTE_ICON_DIM, (x, cy - 12))
        x += 28
        code_txt = font.render(self.code if self.has_note else "????", True, GOLD if self.has_note else GREY)
        screen.blit(code_txt, (x, cy - code_txt.get_height() // 2))
        x += code_txt.get_width() + 22
        pygame.draw.line(screen, GREY, (x - 10, cy - 9), (x - 10, cy + 9), 1)
        # Pulsos guardados (ESPAÇO)
        for i in range(MAX_PULSES):
            screen.blit(ORB_ICON if i < self.pulse_charges else ORB_ICON_DIM, (x, cy - 12))
            x += 26
        if self.pulse_charges > 0:
            hint = small_font.render(key_label("pulse"), True, CYAN)
            screen.blit(hint, (x, cy - hint.get_height() // 2))
            x += hint.get_width()
        x += 16
        # Efeitos ativos, com barra de tempo
        for icon, left, total, color in ((SHIELD_ICON, self.shield_t, SHIELD_TIME, (90, 210, 255)),
                                         (VIAL_ICON, self.boost_t, BOOST_TIME, PINK),
                                         (MUTE_ICON, self.silent_t, SILENCE_TIME, (200, 200, 230))):
            if left > 0:
                screen.blit(icon, (x, cy - 12))
                pygame.draw.rect(screen, (30, 36, 70), (x + 28, cy - 3, 46, 6))
                pygame.draw.rect(screen, color, (x + 28, cy - 3, int(46 * left / total), 6))
                x += 86
        pts = font.render(f"PONTOS {self.score}", True, YELLOW)
        px_ = max(x + 10, 640)
        screen.blit(pts, (px_, cy - pts.get_height() // 2))
        if self.combo > 1 and pygame.time.get_ticks() - self.eat_last < 900:
            cmb = font.render(f"x{self.combo}", True, GOLD)
            screen.blit(cmb, (px_ + pts.get_width() + 8, cy - cmb.get_height() // 2))
        lvl = font.render(f"FASE {self.level}   RECORDE {max(self.best, self.level)}", True, WHITE)
        screen.blit(lvl, (SCREEN_W - lvl.get_width() - 14, cy - lvl.get_height() // 2))


HUD_BAR = pygame.Surface((SCREEN_W, TILE), pygame.SRCALPHA)
HUD_BAR.fill((6, 8, 22, 232))
pygame.draw.line(HUD_BAR, WALL_EDGE, (0, 0), (SCREEN_W, 0), 1)


PAUSE_OVERLAY = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
PAUSE_OVERLAY.fill((2, 4, 16, 175))


def draw_pause(frame):
    """Tela de pausa por cima do jogo congelado."""
    screen.blit(PAUSE_OVERLAY, (0, 0))
    cx, cy = SCREEN_W // 2, SCREEN_H // 2
    pulse = 0.5 + 0.5 * math.sin(frame / 20.0)
    title = title_font.render("PAUSADO", True, (255, int(200 + 45 * pulse), 70))
    screen.blit(title, (cx - title.get_width() // 2, cy - 80))
    lines = [("P  continuar", WHITE),
             ("R reiniciar     Esc menu     M som     F11 janela / tela cheia", (175, 190, 220))]
    for i, (text, col) in enumerate(lines):
        t = (big_font if i == 0 else font).render(text, True, col)
        screen.blit(t, (cx - t.get_width() // 2, cy - 5 + i * 44))
    head = small_font.render(f"CONQUISTAS  {len(ACH.unlocked)}/{len(ACH_INFO)}", True, GOLD)
    screen.blit(head, (cx - head.get_width() // 2, cy + 92))
    for i, (key, (name, desc)) in enumerate(ACH_INFO.items()):
        done = key in ACH.unlocked
        line = small_font.render(f"[{'x' if done else ' '}] {name} - {desc}", True, WHITE if done else GREY)
        screen.blit(line, (cx - 190, cy + 116 + i * 19))


def draw_menu(game, frame):
    """Tela de início: mansão escurecida ao fundo, título, legenda e instruções."""
    game.draw()
    overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
    overlay.fill((4, 6, 20, 215))
    screen.blit(overlay, (0, 0))
    cx = SCREEN_W // 2

    pulse = 0.5 + 0.5 * math.sin(frame / 25.0)
    title = title_font.render("MANSÃO: FUGA SOMBRIA", True, (255, int(190 + 50 * pulse), 60))
    shadow = title_font.render("MANSÃO: FUGA SOMBRIA", True, (120, 30, 50))
    screen.blit(shadow, (cx - title.get_width() // 2 + 3, 47))
    screen.blit(title, (cx - title.get_width() // 2, 44))
    sub = big_font.render("Fases infinitas • cada fase é mais difícil", True, CYAN)
    screen.blit(sub, (cx - sub.get_width() // 2, 90))
    dtxt = small_font.render(f"<   Dificuldade: {current_difficulty()['name']}   >     (setas, A/D ou TAB)", True, GOLD)
    screen.blit(dtxt, (cx - dtxt.get_width() // 2, 124))

    panel = pygame.Rect(cx - 380, 142, 760, 340)
    pygame.draw.rect(screen, (12, 18, 45), panel, border_radius=12)
    pygame.draw.rect(screen, WALL_EDGE, panel, 2, border_radius=12)

    # Legenda com os próprios sprites do jogo.
    rows = [
        ("key", "Pegue a CHAVE dourada (isso faz soar o alarme!)"),
        ("note", "Ache o BILHETE escondido: o código muda a cada fase"),
        ("console", "Use o CONSOLE (E) e digite o código do bilhete"),
        ("exit", "Corra até o NÚCLEO de saída quando ele ficar verde"),
        ("drones", "Fuja dos DRONES: cada cor caça de um jeito (roxo = chefe, azul teleporta)"),
        ("items", "Itens: ESCUDO, ACELERAÇÃO, PULSO, RELÓGIO e SILÊNCIO ajudam a escapar"),
    ]
    y = panel.y + 20
    ix = panel.x + 55
    for kind, text in rows:
        if kind == "key":
            screen.blit(KEY_IMG, KEY_IMG.get_rect(center=(ix, y + 12)))
        elif kind == "note":
            screen.blit(NOTE_IMG, NOTE_IMG.get_rect(center=(ix, y + 12)))
        elif kind == "console":
            screen.blit(CONSOLE_IMG, CONSOLE_IMG.get_rect(center=(ix, y + 12)))
        elif kind == "exit":
            screen.blit(EXIT_LOCKED_IMG if (frame // 40) % 2 == 0 else EXIT_OPEN_IMG,
                        EXIT_LOCKED_IMG.get_rect(center=(ix, y + 12)))
        elif kind == "drones":
            for i, col in enumerate((RED, PINK, CYAN, ORANGE)):
                spr = drone_frames(col, SecurityDrone.EYE["PATROL"])[(frame // 8 + i) % 4]
                spr = scaled(spr, (24, 24))
                screen.blit(spr, spr.get_rect(center=(ix - 33 + i * 22, y + 12)))
        else:
            for i, icon in enumerate((SHIELD_ICON, VIAL_ICON, ORB_ICON)):
                screen.blit(icon, icon.get_rect(center=(ix - 28 + i * 28, y + 12)))
        small = kind in ("drones", "items")
        label = (small_font if small else font).render(text, True, WHITE)
        screen.blit(label, (panel.x + 112, y + (6 if small else 4)))
        y += 40

    controls = [
        "W/S: andar     A/D: girar (ou mouse)     E: interagir     ESPAÇO: pulso     P: pausar     R: reiniciar",
        "M: som     F5/F6: música     F7/F8: efeitos     F11: tela     F2: minimapa     F3: depurar IA     Esc: sair",
        f"Tela agora: {'TELA CHEIA' if FULLSCREEN else 'JANELA'}  (F11 alterna)    •    O: opções (volume, teclas, tela)",
    ]
    for i, line in enumerate(controls):
        t = small_font.render(line, True, CYAN if i == 2 else GREY)
        screen.blit(t, (cx - t.get_width() // 2, y + 8 + i * 22))

    if (frame // 30) % 2 == 0:
        go = big_font.render("Pressione ENTER ou ESPAÇO para começar", True, YELLOW)
        screen.blit(go, (cx - go.get_width() // 2, 488))
    draw_scoreboard(cx, 530, game.scores, highlight=None)
    cc = small_font.render(f"Conquistas: {len(ACH.unlocked)}/{len(ACH_INFO)}", True, GREY)
    screen.blit(cc, (SCREEN_W - cc.get_width() - 10, 8))
    if not SFX:
        m = small_font.render("(áudio indisponível: jogo rodando sem som)", True, GREY)
        screen.blit(m, (10, 8))


class SettingsScreen:
    """Opções (no menu: tecla O): dificuldade, volumes, tela cheia e teclas."""
    MAIN = ["difficulty", "music", "sfx", "fullscreen", "keys", "back"]
    LABELS = {"difficulty": "Dificuldade", "music": "Volume da música", "sfx": "Volume dos efeitos",
              "fullscreen": "Tela cheia", "keys": "Configurar teclas...", "back": "Voltar"}

    def __init__(self):
        self.open = False
        self.page = "main"       # "main" ou "keys"
        self.idx = 0
        self.capture = False     # esperando uma tecla para remapear
        self.note = ""

    def show(self):
        self.open, self.page, self.idx, self.capture, self.note = True, "main", 0, False, ""

    def count(self):
        return len(self.MAIN) if self.page == "main" else len(ACTIONS) + 2

    def handle(self, event):
        key = event.key
        if self.capture:
            if key == pygame.K_ESCAPE:
                self.capture, self.note = False, ""
            elif key in RESERVED_KEYS:
                self.note = "Essa tecla é reservada pelo jogo. Escolha outra."
            else:
                action, label = ACTIONS[self.idx]
                KEYMAP[action] = [key]
                self.capture = False
                self.note = f"{label}: {pygame.key.name(key).upper()}"
                save_settings()
                play("tick")
            return
        if key == pygame.K_ESCAPE:
            if self.page == "keys":
                self.page, self.idx = "main", self.MAIN.index("keys")
            else:
                self.open = False
            return
        n = self.count()
        enter = key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)
        if key == pygame.K_UP:
            self.idx = (self.idx - 1) % n
            play("tick")
        elif key == pygame.K_DOWN:
            self.idx = (self.idx + 1) % n
            play("tick")
        elif key in (pygame.K_LEFT, pygame.K_RIGHT) or enter:
            step = -1 if key == pygame.K_LEFT else 1
            if self.page == "main":
                self.activate_main(step, enter)
            else:
                self.activate_keys(enter)

    def activate_main(self, step, enter):
        item = self.MAIN[self.idx]
        if item == "difficulty":
            SETTINGS["difficulty"] = (SETTINGS["difficulty"] + step) % len(DIFFICULTIES)
        elif item in ("music", "sfx"):
            v = SETTINGS[item] + 0.1 * step
            if enter and v > 1.0:
                v = 0.0                                  # Enter na ponta máxima volta a zero
            SETTINGS[item] = round(max(0.0, min(1.0, v)), 1)
        elif item == "fullscreen":
            toggle_fullscreen()
        elif item == "keys" and enter:
            self.page, self.idx, self.note = "keys", 0, ""
        elif item == "back" and enter:
            self.open = False
        save_settings()
        play("tick")

    def activate_keys(self, enter):
        if not enter:
            return
        if self.idx < len(ACTIONS):
            self.capture = True
            self.note = "Pressione a nova tecla (Esc cancela)"
        elif self.idx == len(ACTIONS):
            for action, keys in DEFAULT_KEYS.items():
                KEYMAP[action] = list(keys)
            self.note = "Teclas restauradas para o padrão."
            save_settings()
        else:
            self.page, self.idx, self.note = "main", self.MAIN.index("keys"), ""

    def rows(self):
        out = []
        if self.page == "main":
            for item in self.MAIN:
                if item == "difficulty":
                    value = f"<  {current_difficulty()['name']}  >"
                elif item in ("music", "sfx"):
                    value = f"<  {round(SETTINGS[item] * 100)}%  >"
                elif item == "fullscreen":
                    value = "SIM" if FULLSCREEN else "NÃO"
                else:
                    value = ""
                out.append((self.LABELS[item], value))
        else:
            for i, (action, label) in enumerate(ACTIONS):
                if self.capture and i == self.idx:
                    value = "pressione uma tecla..."
                else:
                    value = " / ".join(pygame.key.name(k).upper() for k in KEYMAP[action])
                out.append((label, value))
            out += [("Restaurar padrão", ""), ("Voltar", "")]
        return out

    def draw(self, game, frame):
        game.draw()
        screen.blit(PAUSE_OVERLAY, (0, 0))
        screen.blit(PAUSE_OVERLAY, (0, 0))
        cx = SCREEN_W // 2
        title = title_font.render("OPÇÕES" if self.page == "main" else "TECLAS", True, GOLD)
        screen.blit(title, (cx - title.get_width() // 2, 50))
        y = 130
        for i, (label, value) in enumerate(self.rows()):
            sel = i == self.idx
            lab = big_font.render(label, True, YELLOW if sel else WHITE)
            screen.blit(lab, (cx - 290, y))
            if value:
                val = big_font.render(value, True, CYAN if sel else GREY)
                screen.blit(val, (cx + 290 - val.get_width(), y))
            if sel:
                pygame.draw.rect(screen, YELLOW, (cx - 310, y - 6, 620, 38), 2, border_radius=8)
            y += 44
        if self.note:
            note = small_font.render(self.note, True, GOLD)
            screen.blit(note, (cx - note.get_width() // 2, y + 6))
        foot = small_font.render("Setas: mover / alterar     Enter: selecionar     Esc: voltar     "
                                 "Controle: D-pad e A / B", True, GREY)
        screen.blit(foot, (cx - foot.get_width() // 2, SCREEN_H - 40))


def restart_game(old):
    """Salva a partida atual e devolve um Game novo (mantém o modo de depuração da IA)."""
    old.finish_session()
    new = Game()
    new.debug_ai = old.debug_ai
    return new


def main():
    global SOUND_ON
    game = Game()
    in_menu = True
    paused = False
    frame = 0
    code_entry = False
    code = ""
    settings = SettingsScreen()
    STEP_MS = 1000.0 / FPS
    acc_ms, last_ms = 0.0, STEP_MS
    running = True
    focus_lost = getattr(pygame, "WINDOWFOCUSLOST", None)
    grabbed = False
    while running:
        frame += 1
        for event in pygame.event.get():
            if event.type == JOY_ADDED:
                add_joystick(event.device_index)
                continue
            if event.type == JOY_REMOVED:
                remove_joystick(event.instance_id)
                continue
            event = translate_joy(event, in_menu)
            if event is None:
                continue
            if event.type == pygame.QUIT:
                running = False
            elif focus_lost is not None and event.type == focus_lost:
                # Trocou de janela? Pausa sozinho para você não ser pego de surpresa.
                if not in_menu and not (game.game_over or game.won) and not code_entry:
                    paused = True
            elif event.type == pygame.MOUSEMOTION:
                if not in_menu and not paused and not code_entry:
                    game.mouse_turn += event.rel[0]
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_F11:
                    toggle_fullscreen()
                    continue
                if in_menu and settings.open:
                    settings.handle(event)
                    continue
                if event.key == pygame.K_m and not code_entry:
                    SOUND_ON = not SOUND_ON
                    if not SOUND_ON:
                        pygame.mixer.stop()
                    else:
                        play("tick")
                    continue
                if not code_entry and event.key in (pygame.K_F5, pygame.K_F6, pygame.K_F7, pygame.K_F8):
                    which = "music" if event.key in (pygame.K_F5, pygame.K_F6) else "sfx"
                    step = -0.1 if event.key in (pygame.K_F5, pygame.K_F7) else 0.1
                    SETTINGS[which] = round(max(0.0, min(1.0, SETTINGS[which] + step)), 1)
                    VOL_TOAST[0] = 90
                    save_settings()
                    if which == "sfx":
                        play("tick")
                    continue
                if in_menu:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_o:
                        settings.show()
                        play("tick")
                    elif event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_a, pygame.K_d, pygame.K_TAB):
                        step = -1 if event.key in (pygame.K_LEFT, pygame.K_a) else 1
                        SETTINGS["difficulty"] = (SETTINGS["difficulty"] + step) % len(DIFFICULTIES)
                        save_settings()
                        play("tick")
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                        play("start")
                        game = Game()          # começa uma partida nova
                        in_menu = False
                        paused = False
                        code_entry, code = False, ""
                    continue
                if key_is(event.key, "pause") and not code_entry and not (game.game_over or game.won):
                    paused = not paused
                    play("pause" if paused else "unpause")
                    continue
                if paused:
                    # Na pausa só valem: continuar (P), reiniciar (R) e voltar ao menu (Esc).
                    if event.key == pygame.K_ESCAPE:
                        game.finish_session()
                        in_menu, paused = True, False
                        code_entry, code = False, ""
                    elif event.key == pygame.K_r:
                        game = restart_game(game)
                        paused = False
                        code_entry, code = False, ""
                    continue
                if event.key == pygame.K_n and game.won:
                    game.advance_level()
                    code_entry, code = False, ""
                elif event.key == pygame.K_F2:
                    game.show_map = not game.show_map
                elif event.key == pygame.K_F3:
                    game.debug_ai = not game.debug_ai
                elif event.key == pygame.K_F4 and game.debug_ai and not game.game_over:
                    game.advance_level()           # atalho de teste: F3 (depurar IA) + F4 pula a fase
                    code_entry, code = False, ""
                elif event.key == pygame.K_ESCAPE and not code_entry:
                    game.finish_session()
                    in_menu = True             # Esc volta para a tela de início
                    code_entry, code = False, ""
                elif event.key == pygame.K_r and not code_entry:     # R não reinicia enquanto digita o código
                    game = restart_game(game)
                    code_entry, code = False, ""
                elif key_is(event.key, "interact") and not code_entry and not (game.game_over or game.won):
                    game.interact()
                    if game.code_prompt:       # o console pediu o código
                        game.code_prompt = False
                        code_entry, code = True, ""
                elif key_is(event.key, "pulse") and not code_entry:
                    game.fire_pulse()
                elif code_entry:
                    if event.key == pygame.K_ESCAPE:
                        code_entry, code = False, ""
                        game.say("Entrada de código cancelada.")
                    elif event.key == pygame.K_BACKSPACE:
                        code = code[:-1]
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        if code == game.code:
                            game.console_open = True
                            game.exit_open = True
                            game.score += 150
                            game.director.report_noise(game, game.console_pos, 16)
                            play("console_ok")
                            cx_, cy_ = game.center_px(game.console_pos)
                            game.particles.burst(cx_, cy_, [GREEN, WHITE, (170, 255, 190)], n=40, speed=3.8,
                                                 life=(24, 50), size=(2, 5))
                            game.rings.append([cx_, cy_, 0, GREEN, 80])
                            game.say("Código correto! A saída foi destrancada. Corra até ela!", 300)
                        else:
                            play("code_bad")
                            game.shake = max(game.shake, 8)
                            game.say("Código incorreto. Confira o bilhete!" if game.has_note
                                     else "Código incorreto. O código está num bilhete escondido no mapa.", 240)
                        code_entry, code = False, ""
                    elif event.unicode.isdigit() and len(code) < 4:
                        code += event.unicode
                        play("tick")
        want_grab = not in_menu and not paused and not code_entry and not (game.game_over or game.won)
        if want_grab != grabbed:                  # mouse preso na janela só durante o jogo
            grabbed = want_grab
            try:
                pygame.event.set_grab(grabbed)
                pygame.mouse.set_visible(not grabbed and not FULLSCREEN)
                pygame.mouse.get_rel()
            except pygame.error:
                pass
            game.mouse_turn = 0.0
        if in_menu:
            music_tick(0.34)
            if settings.open:
                settings.draw(game, frame)
            else:
                draw_menu(game, frame)
            draw_overlays()
            pygame.display.flip()
            last_ms, acc_ms = clock.tick(FPS), 0.0
            continue
        if paused:
            music_tick(0.07)
            game.draw()
            draw_pause(frame)
            draw_overlays()
            pygame.display.flip()
            last_ms, acc_ms = clock.tick(FPS), 0.0
            continue
        # Passo fixo de 60 Hz: se o computador não segura 60 FPS, roda mais de um update por quadro
        # (o jogo mantém a mesma velocidade). Em 60 FPS são sempre exatamente 1 update por quadro.
        acc_ms += last_ms
        steps = int(acc_ms // STEP_MS)
        if steps == 0 and acc_ms > STEP_MS * 0.8:
            steps = 1
        acc_ms = max(0.0, acc_ms - steps * STEP_MS)
        if steps > 4:
            steps, acc_ms = 4, 0.0
        for _ in range(steps):
            game.update()
            if game.won:
                # Fases infinitas: depois de ~2,5 s a próxima fase começa sozinha.
                game.win_timer += 1
                if game.win_timer >= 150:
                    game.advance_level()
                    code_entry, code = False, ""
                    break
        chasing = any(d.delay <= 0 and d.state in ("CHASE", "NOTICE") and d.stun <= 0 for d in game.drones)
        music_tick(0.14 if chasing else 0.34)   # a música abaixa durante a perseguição
        game.draw()
        if code_entry:
            panel = pygame.Rect(SCREEN_W//2-220, SCREEN_H//2-75, 440, 156)
            pygame.draw.rect(screen, (12,18,45), panel, border_radius=12)
            pygame.draw.rect(screen, PURPLE, panel, 3, border_radius=12)
            t = big_font.render("CÓDIGO DO CONSOLE", True, WHITE)
            screen.blit(t,(panel.centerx-t.get_width()//2,panel.y+14))
            value = big_font.render(" ".join(code.ljust(4, "_")), True, GOLD)
            screen.blit(value,(panel.centerx-value.get_width()//2,panel.y+58))
            hint_txt = ("Digite o código do bilhete (4 dígitos)" if game.has_note
                        else "Dica: o código está num bilhete escondido no mapa")
            hint = small_font.render(hint_txt, True, CYAN if game.has_note else GREY)
            screen.blit(hint, (panel.centerx-hint.get_width()//2, panel.y+102))
            ctl = small_font.render("Enter confirmar • Esc cancelar", True, GREY)
            screen.blit(ctl, (panel.centerx-ctl.get_width()//2, panel.y+126))
        apply_shake(game.shake_amount())          # tremor de tela ao ser pego (HUD incluso)
        draw_overlays()
        pygame.display.flip()
        last_ms = clock.tick(FPS)
    game.finish_session()
    save_settings()
    pygame.quit()

if __name__ == "__main__":
    main()
