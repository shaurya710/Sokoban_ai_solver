"""
Sokoban game window, built on top of sokoban_solver.py.

Setup (once), in the VS Code terminal:
    pip install pygame

Run:
    python sokoban_game.py          # start at level 1
    python sokoban_game.py 4        # start at level 4

Controls:
    Arrow keys / WASD   move (walk into a box to push it)
    Z                   undo your last move
    R                   restart the level
    S                   let the AI (A* + deadlock detection) solve it from where you are
    N / P               next / previous level
    Esc                 stop the AI if it is working, otherwise quit
"""

import argparse
import copy
import os
import sys
import threading

try:
    import pygame
except ImportError:
    sys.exit("pygame isn't installed. In the VS Code terminal run:  pip install pygame")

from sokoban_solver import Solver, load_levels, replay


# ----------------------------------------------------------------------------
# Look and feel
# ----------------------------------------------------------------------------
HUD_TOP = 70          # space above the board for the title and counters
HUD_BOTTOM = 58       # space below the board for the key help
MIN_WIDTH = 720       # window is never narrower than this
ANIM_MS = 130         # how long each step of the AI's solution is shown

BG = (24, 26, 32)
FLOOR = (58, 62, 74)
FLOOR_LINE = (50, 54, 65)
WALL = (112, 88, 72)
WALL_DARK = (84, 64, 52)
GOAL = (240, 200, 60)
BOX = (200, 140, 70)
BOX_DARK = (140, 92, 44)
BOX_DONE = (92, 190, 112)
BOX_DONE_DARK = (52, 132, 72)
PLAYER = (84, 160, 240)
TEXT = (232, 234, 240)
TEXT_DIM = (150, 156, 170)
ACCENT = (250, 214, 90)


class Game:
    def __init__(self, levels, start_index=0):
        self.levels = levels
        self.screen = None
        self.font_big = pygame.font.Font(None, 38)
        self.font = pygame.font.Font(None, 28)
        self.font_small = pygame.font.Font(None, 23)
        self.job_id = 0
        self.load_level(start_index)

    # -- loading a level -----------------------------------------------------
    def load_level(self, index):
        self.index = index % len(self.levels)
        self.level = self.levels[self.index]
        self.boxes = self.level.start_boxes
        self.player = self.level.start_player
        self.moves = 0
        self.pushes = 0
        self.history = []          # for undo: (boxes, player, moves, pushes)
        self.job_id += 1           # invalidates any AI job still running
        self.solving = False
        self.solve_result = None
        self.anim = None           # set while the AI's solution is being played
        self.msg = ""
        self._resize()

    def _resize(self):
        lv = self.level
        cols = lv.width - 1
        self.cols = cols
        avail_h = 720 - HUD_TOP - HUD_BOTTOM
        self.tile = max(24, min(72, 1100 // cols, avail_h // lv.height))
        win_w = max(cols * self.tile, MIN_WIDTH)
        win_h = lv.height * self.tile + HUD_TOP + HUD_BOTTOM
        self.ox = (win_w - cols * self.tile) // 2   # centre the board
        self.screen = pygame.display.set_mode((win_w, win_h))
        pygame.display.set_caption("Sokoban - AI solver (A* + deadlock detection)")

    @property
    def won(self):
        return self.boxes == self.level.goals

    @property
    def busy(self):
        return self.solving or self.anim is not None

    # -- playing -------------------------------------------------------------
    def try_move(self, letter):
        lv = self.level
        step = lv.step_of[letter]
        nxt = self.player + step
        if nxt not in lv.floor:
            return
        new_boxes = self.boxes
        pushed = False
        if nxt in self.boxes:
            beyond = nxt + step
            if beyond not in lv.floor or beyond in self.boxes:
                return
            new_boxes = (self.boxes - {nxt}) | {beyond}
            pushed = True
        self.history.append((self.boxes, self.player, self.moves, self.pushes))
        self.boxes = frozenset(new_boxes)
        self.player = nxt
        self.moves += 1
        if pushed:
            self.pushes += 1
        self.msg = ""

    def undo(self):
        if self.history:
            self.boxes, self.player, self.moves, self.pushes = self.history.pop()
            self.msg = ""

    # -- the AI --------------------------------------------------------------
    def start_solve(self):
        if self.won:
            return
        # Solve from the CURRENT position, not from the start of the level.
        lv = copy.copy(self.level)
        lv.start_boxes = self.boxes
        lv.start_player = self.player
        job = self.job_id
        self.solving = True
        self.solve_result = None

        def work():
            result = Solver(lv).solve(time_limit=30)
            frames = replay(lv, result.moves)[0] if result.solved else None
            self.solve_result = (result, frames, job)

        threading.Thread(target=work, daemon=True).start()

    def cancel_ai(self):
        self.job_id += 1
        self.solving = False
        self.solve_result = None
        self.anim = None
        self.msg = "AI stopped."

    # -- input ---------------------------------------------------------------
    def handle_key(self, key):
        """Returns False when the game should quit."""
        if self.busy:
            if key in (pygame.K_ESCAPE, pygame.K_s):
                self.cancel_ai()
            return True
        if key == pygame.K_ESCAPE:
            return False
        if key in (pygame.K_UP, pygame.K_w):
            self.try_move("u")
        elif key == pygame.K_DOWN:
            self.try_move("d")
        elif key in (pygame.K_LEFT, pygame.K_a):
            self.try_move("l")
        elif key in (pygame.K_RIGHT, pygame.K_d):
            self.try_move("r")
        elif key == pygame.K_z:
            self.undo()
        elif key == pygame.K_r:
            self.load_level(self.index)
        elif key == pygame.K_n:
            self.load_level(self.index + 1)
        elif key == pygame.K_p:
            self.load_level(self.index - 1)
        elif key == pygame.K_s:
            self.start_solve()
        return True

    # -- per-frame update ----------------------------------------------------
    def update(self, dt):
        # 1. Did the background solver finish?
        if self.solving and self.solve_result is not None:
            result, frames, job = self.solve_result
            self.solving = False
            self.solve_result = None
            if job != self.job_id:
                return
            if result.solved and frames and len(frames) > 1:
                self.history.append((self.boxes, self.player, self.moves, self.pushes))
                self.anim = {"frames": frames, "i": 0, "t": 0, "pushes": result.pushes}
            elif result.solved:
                self.msg = "Already solved."
            else:
                self.msg = "AI: no solution from here. Try Z (undo) or R (restart)."

        # 2. Play the AI's solution one frame at a time.
        if self.anim:
            a = self.anim
            a["t"] += dt
            while a["t"] >= ANIM_MS and self.anim:
                a["t"] -= ANIM_MS
                a["i"] += 1
                if a["i"] >= len(a["frames"]):
                    self.anim = None
                    self.msg = ""
                else:
                    boxes, player = a["frames"][a["i"]]
                    if boxes != self.boxes:
                        self.pushes += 1
                    self.moves += 1
                    self.boxes, self.player = boxes, player

    # -- drawing -------------------------------------------------------------
    def draw(self):
        s = self.screen
        lv = self.level
        t = self.tile
        s.fill(BG)

        # Top bar
        title = f"Level {self.index + 1} / {len(self.levels)}"
        if lv.title:
            title += f"  -  {lv.title}"
        s.blit(self.font_big.render(title, True, TEXT), (16, 10))
        stats = f"Moves: {self.moves}     Pushes: {self.pushes}"
        s.blit(self.font.render(stats, True, TEXT_DIM), (16, 42))

        status = self.msg
        if self.solving:
            dots = "." * (1 + pygame.time.get_ticks() // 400 % 3)
            status = "AI is thinking" + dots
        elif self.anim:
            a = self.anim
            status = f"AI solving: step {a['i']}/{len(a['frames']) - 1}   (S or Esc to stop)"
        if status:
            img = self.font.render(status, True, ACCENT)
            s.blit(img, (s.get_width() - img.get_width() - 16, 42))

        # Board: walls and floor
        for r in range(lv.height):
            for c in range(self.cols):
                p = r * lv.width + c
                rect = pygame.Rect(self.ox + c * t, HUD_TOP + r * t, t, t)
                if p in lv.walls:
                    pygame.draw.rect(s, WALL, rect)
                    pygame.draw.rect(s, WALL_DARK, rect, 2)
                    pygame.draw.line(s, WALL_DARK, rect.midleft, rect.midright, 2)
                elif p in lv.floor:
                    pygame.draw.rect(s, FLOOR, rect)
                    pygame.draw.rect(s, FLOOR_LINE, rect, 1)
                    if p in lv.goals:
                        pygame.draw.circle(s, GOAL, rect.center, max(4, t // 6))

        # Boxes
        for p in self.boxes:
            r, c = divmod(p, lv.width)
            rect = pygame.Rect(self.ox + c * t, HUD_TOP + r * t, t, t).inflate(-t // 7, -t // 7)
            done = p in lv.goals
            pygame.draw.rect(s, BOX_DONE if done else BOX, rect, border_radius=6)
            pygame.draw.rect(s, BOX_DONE_DARK if done else BOX_DARK, rect, 3, border_radius=6)
            pygame.draw.line(s, BOX_DONE_DARK if done else BOX_DARK, rect.topleft, rect.bottomright, 2)
            pygame.draw.line(s, BOX_DONE_DARK if done else BOX_DARK, rect.topright, rect.bottomleft, 2)

        # Player
        r, c = divmod(self.player, lv.width)
        center = (self.ox + c * t + t // 2, HUD_TOP + r * t + t // 2)
        pygame.draw.circle(s, PLAYER, center, int(t * 0.34))
        pygame.draw.circle(s, (20, 70, 140), center, int(t * 0.34), 3)
        for dx in (-1, 1):
            pygame.draw.circle(s, (255, 255, 255), (center[0] + dx * t // 9, center[1] - t // 12), max(2, t // 14))

        # Bottom help
        y = HUD_TOP + lv.height * t + 8
        s.blit(self.font_small.render(
            "Arrows / WASD: move     Z: undo     R: restart     S: AI solve", True, TEXT_DIM), (16, y))
        s.blit(self.font_small.render(
            "N / P: next / previous level     Esc: quit (or stop the AI)", True, TEXT_DIM), (16, y + 24))

        # Win banner
        if self.won and not self.busy:
            board = pygame.Rect(0, HUD_TOP, s.get_width(), lv.height * t)
            veil = pygame.Surface(board.size, pygame.SRCALPHA)
            veil.fill((0, 0, 0, 150))
            s.blit(veil, board.topleft)
            big = self.font_big.render("Solved!", True, ACCENT)
            small = self.font.render(
                f"{self.moves} moves, {self.pushes} pushes.   Press N for the next level, R to replay.",
                True, TEXT)
            panel = pygame.Rect(0, 0, small.get_width() + 48, 90)
            panel.center = board.center
            pygame.draw.rect(s, (30, 33, 42), panel, border_radius=12)
            pygame.draw.rect(s, ACCENT, panel, 2, border_radius=12)
            s.blit(big, big.get_rect(center=(panel.centerx, panel.centery - 18)))
            s.blit(small, small.get_rect(center=(panel.centerx, panel.centery + 18)))

    # -- main loop -----------------------------------------------------------
    def run(self):
        clock = pygame.time.Clock()
        pygame.key.set_repeat(170, 70)    # hold an arrow key to keep walking
        held = set()
        running = True
        while running:
            dt = clock.tick(60)
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    running = False
                elif e.type == pygame.KEYUP:
                    held.discard(e.key)
                elif e.type == pygame.KEYDOWN:
                    movement = e.key in (pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT,
                                         pygame.K_w, pygame.K_a, pygame.K_d)
                    # Key-repeat is fine for walking, but must not re-trigger S, R, N, ...
                    if movement or e.key not in held:
                        if not self.handle_key(e.key):
                            running = False
                    held.add(e.key)
            self.update(dt)
            self.draw()
            pygame.display.flip()


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Sokoban game with an A* AI solver")
    ap.add_argument("level", nargs="?", type=int, default=1, help="level to start on (1-based)")
    ap.add_argument("--file", default=os.path.join(here, "levels.txt"), help="levels file")
    args = ap.parse_args()

    levels = load_levels(args.file)
    if not 1 <= args.level <= len(levels):
        sys.exit(f"Pick a level between 1 and {len(levels)}")

    pygame.init()
    Game(levels, args.level - 1).run()
    pygame.quit()


if __name__ == "__main__":
    main()
