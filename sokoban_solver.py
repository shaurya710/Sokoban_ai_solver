"""
Sokoban solver: A* search over box pushes, plus deadlock detection.

How to run (from a terminal, inside this folder):
    python sokoban_solver.py              # solve every level in levels.txt
    python sokoban_solver.py 2            # solve level 2 only
    python sokoban_solver.py 2 --animate  # solve level 2 and replay it in the terminal

Level symbols (the standard Sokoban text format):
    #  wall            $  box              .  goal
    @  player          *  box on a goal    +  player on a goal
"""

import argparse
import heapq
import itertools
import os
import time
from collections import deque
from dataclasses import dataclass, field


# ----------------------------------------------------------------------------
# PART 1: the level
# ----------------------------------------------------------------------------
# Every cell on the board is stored as ONE integer: row * width + column.
# Moving up/down/left/right is then just adding -width, +width, -1, +1.
# That keeps the code short and fast.

class Level:
    def __init__(self, text, title=""):
        rows = [r for r in text.split("\n") if r.strip() != ""]
        self.title = title
        self.height = len(rows)
        # +1 adds an empty padding column so that "left of column 0" can never
        # accidentally land on the previous row's last real cell.
        self.width = max(len(r) for r in rows) + 1
        w = self.width

        walls, goals, boxes, player = set(), set(), set(), None
        for r, row in enumerate(rows):
            for c, ch in enumerate(row):
                p = r * w + c
                if ch == "#":
                    walls.add(p)
                if ch in ".*+":
                    goals.add(p)
                if ch in "$*":
                    boxes.add(p)
                if ch in "@+":
                    player = p

        if player is None:
            raise ValueError("Level has no player (@)")
        if len(boxes) != len(goals):
            raise ValueError(f"{len(boxes)} boxes but {len(goals)} goals")

        self.walls = walls
        self.goals = frozenset(goals)
        self.start_boxes = frozenset(boxes)
        self.start_player = player

        self.steps = (-w, w, -1, 1)                      # up, down, left, right
        self.letter = {-w: "u", w: "d", -1: "l", 1: "r"}  # step -> move letter
        self.step_of = {v: k for k, v in self.letter.items()}

        self.floor = self._find_floor()

    def _find_floor(self):
        """Flood-fill from the player to find every walkable cell (ignoring boxes)."""
        real_width = self.width - 1
        floor = {self.start_player}
        stack = [self.start_player]
        while stack:
            p = stack.pop()
            for s in self.steps:
                q = p + s
                r, c = divmod(q, self.width)
                inside = 0 <= r < self.height and 0 <= c < real_width
                if inside and q not in self.walls and q not in floor:
                    floor.add(q)
                    stack.append(q)
        return floor

    def render(self, boxes, player):
        """Turn a board state back into text so we can print it."""
        lines = []
        for r in range(self.height):
            row = []
            for c in range(self.width - 1):
                p = r * self.width + c
                if p in self.walls:
                    ch = "#"
                elif p not in self.floor:
                    ch = " "
                elif p == player:
                    ch = "+" if p in self.goals else "@"
                elif p in boxes:
                    ch = "*" if p in self.goals else "$"
                elif p in self.goals:
                    ch = "."
                else:
                    ch = " "
                row.append(ch)
            lines.append("".join(row).rstrip())
        return "\n".join(lines)


def load_levels(path):
    """Read a levels file. Levels are separated by blank lines; ';' lines are titles."""
    with open(path, encoding="utf-8") as f:
        text = f.read().replace("\r\n", "\n")
    levels = []
    for block in text.split("\n\n"):
        title, rows = "", []
        for line in block.split("\n"):
            if line.startswith(";"):
                title = title or line[1:].strip()
            elif line.strip() != "":
                rows.append(line)
        if rows:
            levels.append(Level("\n".join(rows), title))
    return levels


# ----------------------------------------------------------------------------
# PART 2: the result we hand back
# ----------------------------------------------------------------------------

@dataclass
class Result:
    solved: bool
    reason: str = ""
    moves: str = ""            # e.g. "rrUUll..."  (UPPERCASE = a push)
    pushes: int = 0
    nodes_expanded: int = 0
    deadlocks_pruned: int = 0
    seconds: float = 0.0
    pushes_list: list = field(default_factory=list)


# ----------------------------------------------------------------------------
# PART 3: the solver (A* + deadlock detection)
# ----------------------------------------------------------------------------

class Solver:
    def __init__(self, level):
        self.level = level
        self.floor = level.floor
        self.goals = level.goals
        self.steps = level.steps
        self.width = level.width

        # DEAD-SQUARE TABLE and HEURISTIC in one go.
        # self.dist[cell] = the fewest pushes needed to get a box from `cell`
        # to the nearest goal (ignoring other boxes).
        # If a cell is NOT in this dictionary, a box there can never reach any
        # goal, so it is a "dead square" and we never push a box onto it.
        self.dist = self._compute_push_distances()

    # -- precomputation ------------------------------------------------------
    def _compute_push_distances(self):
        """
        Search BACKWARDS from the goals using "pulls".
        If a box sits at b and the player stands at b+s, the player can step to
        b+2s and pull the box to b+s. Running a push in reverse is a pull, so
        every cell reached by pulling is a cell from which a push can get us
        back to a goal.
        """
        dist = {g: 0 for g in self.goals}
        queue = deque(self.goals)
        while queue:
            b = queue.popleft()
            for s in self.steps:
                new_box = b + s      # where the box ends up after the pull
                player_to = b + 2 * s  # where the player must be able to stand
                if new_box in self.floor and player_to in self.floor and new_box not in dist:
                    dist[new_box] = dist[b] + 1
                    queue.append(new_box)
        return dist

    # -- player movement -----------------------------------------------------
    def reachable(self, boxes, player):
        """All cells the player can walk to without pushing anything."""
        seen = {player}
        stack = [player]
        while stack:
            p = stack.pop()
            for s in self.steps:
                q = p + s
                if q in self.floor and q not in boxes and q not in seen:
                    seen.add(q)
                    stack.append(q)
        return seen

    # -- deadlock detection --------------------------------------------------
    def _blocked_on_axis(self, a, b, boxes, visiting):
        """
        Can the box between neighbours a and b be pushed along this axis?
        It is BLOCKED (cannot move along this axis) if:
          1. a wall is on either side (we need both sides free to push), or
          2. both sides are dead squares, or
          3. a neighbouring box on either side is itself completely frozen.
        """
        if a not in self.floor or b not in self.floor:
            return True
        if a not in self.dist and b not in self.dist:
            return True
        for n in (a, b):
            if n in boxes and self.is_frozen(n, boxes, visiting):
                return True
        return False

    def is_frozen(self, box, boxes, visiting):
        """A box is frozen if it is blocked both horizontally AND vertically."""
        if box in visiting:
            # Two boxes holding each other in place: assume frozen while we check.
            return True
        visiting.add(box)
        w = self.width
        frozen = (self._blocked_on_axis(box - 1, box + 1, boxes, visiting) and
                  self._blocked_on_axis(box - w, box + w, boxes, visiting))
        visiting.discard(box)
        return frozen

    def has_deadlock(self, boxes, moved_box):
        """
        After a push, check the moved box and every box touching it.
        A frozen box that is NOT sitting on a goal can never be solved,
        so this whole branch of the search can be thrown away.
        """
        w = self.width
        seen = {moved_box}
        stack = [moved_box]
        while stack:
            b = stack.pop()
            if b not in self.goals and self.is_frozen(b, boxes, set()):
                return True
            for n in (b - 1, b + 1, b - w, b + w):
                if n in boxes and n not in seen:
                    seen.add(n)
                    stack.append(n)
        return False

    # -- the A* search -------------------------------------------------------
    def solve(self, max_nodes=3_000_000, time_limit=60.0):
        t0 = time.time()
        lv = self.level
        start_boxes = lv.start_boxes

        # Quick sanity checks before searching at all.
        if any(b not in self.dist for b in start_boxes):
            return Result(False, "A box starts on a dead square (it can never reach a goal).",
                          seconds=time.time() - t0)
        for b in start_boxes:
            if b not in self.goals and self.is_frozen(b, start_boxes, set()):
                return Result(False, "A box starts out frozen (stuck forever).",
                              seconds=time.time() - t0)

        h0 = sum(self.dist[b] for b in start_boxes)

        # nodes[i] = (parent_node, box_pushed, direction). Used to rebuild the path.
        nodes = [(None, None, None)]
        counter = itertools.count()  # tie-breaker so the heap never compares sets

        # Heap entry: (f, h, tie, g, node_id, boxes, player)
        #   g = pushes made so far, h = estimated pushes left, f = g + h
        heap = [(h0, h0, next(counter), 0, 0, start_boxes, lv.start_player)]
        closed = set()  # states already expanded
        expanded = pruned = 0

        while heap:
            f, h, _, g, node, boxes, player = heapq.heappop(heap)

            reach = self.reachable(boxes, player)
            # Two states are the SAME if the boxes match and the player can walk
            # to the same area. min(reach) is a stable name for that area.
            key = (boxes, min(reach))
            if key in closed:
                continue
            closed.add(key)

            if h == 0:  # every box is on a goal
                pushes = []
                n = node
                while nodes[n][0] is not None:
                    parent, box, step = nodes[n]
                    pushes.append((box, step))
                    n = parent
                pushes.reverse()
                moves = pushes_to_moves(lv, pushes)
                return Result(True, moves=moves, pushes=len(pushes),
                              nodes_expanded=expanded, deadlocks_pruned=pruned,
                              seconds=time.time() - t0, pushes_list=pushes)

            expanded += 1
            if expanded > max_nodes or time.time() - t0 > time_limit:
                return Result(False, "Gave up: search limit reached.",
                              nodes_expanded=expanded, deadlocks_pruned=pruned,
                              seconds=time.time() - t0)

            for box in boxes:
                for s in self.steps:
                    if box - s not in reach:        # player can't get behind the box
                        continue
                    target = box + s
                    if target not in self.floor or target in boxes:
                        continue
                    if target not in self.dist:      # dead square
                        pruned += 1
                        continue
                    new_boxes = (boxes - {box}) | {target}
                    if self.has_deadlock(new_boxes, target):
                        pruned += 1
                        continue
                    new_h = h - self.dist[box] + self.dist[target]
                    nodes.append((node, box, s))
                    heapq.heappush(heap, (g + 1 + new_h, new_h, next(counter), g + 1,
                                          len(nodes) - 1, new_boxes, box))

        return Result(False, "Search finished: this level has no solution.",
                      nodes_expanded=expanded, deadlocks_pruned=pruned,
                      seconds=time.time() - t0)


# ----------------------------------------------------------------------------
# PART 4: turning pushes into walking moves, and checking the answer
# ----------------------------------------------------------------------------

def find_walk(level, boxes, start, goal):
    """Shortest walk (BFS) from start to goal that doesn't touch any box. Returns letters."""
    if start == goal:
        return ""
    parent = {start: None}
    queue = deque([start])
    while queue:
        p = queue.popleft()
        for s in level.steps:
            q = p + s
            if q in level.floor and q not in boxes and q not in parent:
                parent[q] = (p, s)
                if q == goal:
                    path = []
                    while parent[q] is not None:
                        p2, s2 = parent[q]
                        path.append(level.letter[s2])
                        q = p2
                    return "".join(reversed(path))
                queue.append(q)
    raise RuntimeError("no walking path found")


def pushes_to_moves(level, pushes):
    """The search only knows pushes. Add the walking in between. Pushes are UPPERCASE."""
    boxes = set(level.start_boxes)
    player = level.start_player
    out = []
    for box, s in pushes:
        out.append(find_walk(level, boxes, player, box - s))
        out.append(level.letter[s].upper())
        boxes.remove(box)
        boxes.add(box + s)
        player = box
    return "".join(out)


def replay(level, moves):
    """
    Play the moves by the real game rules, completely separate from the solver.
    Returns (list_of_frames, solved?). Raises an error on any illegal move.
    """
    boxes = set(level.start_boxes)
    player = level.start_player
    frames = [(frozenset(boxes), player)]
    for ch in moves:
        s = level.step_of[ch.lower()]
        nxt = player + s
        if nxt not in level.floor:
            raise ValueError("illegal move: walked into a wall")
        if nxt in boxes:
            beyond = nxt + s
            if beyond not in level.floor or beyond in boxes:
                raise ValueError("illegal move: push is blocked")
            boxes.remove(nxt)
            boxes.add(beyond)
        player = nxt
        frames.append((frozenset(boxes), player))
    return frames, boxes == set(level.goals)


# ----------------------------------------------------------------------------
# PART 5: command-line interface
# ----------------------------------------------------------------------------

def run_level(number, level, animate, time_limit):
    name = f"Level {number}" + (f" - {level.title}" if level.title else "")
    print("=" * 60)
    print(name)
    print(level.render(level.start_boxes, level.start_player))

    result = Solver(level).solve(time_limit=time_limit)

    if not result.solved:
        print(f"\nNO SOLUTION FOUND: {result.reason}")
        print(f"(expanded {result.nodes_expanded} states in {result.seconds:.2f}s)")
        return

    frames, ok = replay(level, result.moves)
    print(f"\nSolved: {result.pushes} pushes, {len(result.moves)} total moves")
    print(f"Verified by replaying the moves: {'OK' if ok else 'FAILED'}")
    print(f"States expanded: {result.nodes_expanded}   "
          f"Deadlock branches pruned: {result.deadlocks_pruned}   "
          f"Time: {result.seconds:.3f}s")
    print(f"Moves (UPPERCASE = push): {result.moves}")

    if animate:
        for i, (boxes, player) in enumerate(frames):
            print(f"\nstep {i}/{len(frames) - 1}")
            print(level.render(boxes, player))
            time.sleep(0.25)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Sokoban solver (A* + deadlock detection)")
    ap.add_argument("level", nargs="?", type=int, help="level number (1-based); omit for all")
    ap.add_argument("--file", default=os.path.join(here, "levels.txt"), help="levels file")
    ap.add_argument("--animate", action="store_true", help="replay the solution step by step")
    ap.add_argument("--time-limit", type=float, default=60.0, help="seconds per level")
    args = ap.parse_args()

    levels = load_levels(args.file)
    if args.level is not None:
        if not 1 <= args.level <= len(levels):
            raise SystemExit(f"Pick a level between 1 and {len(levels)}")
        run_level(args.level, levels[args.level - 1], args.animate, args.time_limit)
    else:
        for i, lv in enumerate(levels, start=1):
            run_level(i, lv, args.animate, args.time_limit)


if __name__ == "__main__":
    main()
