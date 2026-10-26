# Sokoban AI Solver

A Sokoban (warehouse box-pushing) puzzle solver written in Python, plus a playable game window.
The solver uses **A\* search** and **deadlock detection** to find a solution with the fewest possible box pushes.

In Sokoban you control a worker in a warehouse and push boxes onto goal squares. Boxes can only be pushed, never pulled, so one careless push can make a puzzle impossible to finish. That is what makes it a good problem for AI search.

## Features

- **A\* solver** that finds a solution with the minimum number of pushes.
- **Deadlock detection** that throws away hopeless moves early (see below).
- **Playable game window** (pygame): play with the keyboard, undo, restart, switch levels.
- **"AI solve" button**: press `S` and watch the AI solve the level from wherever you currently are.
- **Self-checking**: every solution found is replayed by a separate piece of code that follows the real game rules, to confirm it works.
- **Plain-text levels**: add your own puzzles to `levels.txt`.

## How the AI works

**1. Searching over pushes, not steps.**
The search decides which box to push in which direction. Walking between pushes is worked out separately with a simple flood fill. This keeps the number of states small. Two board states count as the same if the boxes are in the same places and the player can walk to the same area.

**2. A\* search.**
States are explored in order of `f = g + h`:
- `g` = pushes made so far
- `h` = estimate of pushes still needed (each box's push distance to its nearest goal, summed)

The estimate never overestimates, so the first solution found has the fewest pushes.

**3. Dead-square detection.**
Before searching, the program works backwards from the goals (using "pulls") to find every square a box could be pushed from. Any square not reached is a dead square: a box there can never reach a goal, so the AI never pushes a box onto one. The same table gives the distances used in the heuristic.

**4. Freeze-deadlock detection.**
After every push, the program checks whether the moved box (or a box touching it) is frozen: blocked in both directions by walls, dead squares, or other frozen boxes. If a frozen box is not on a goal, that branch of the search is discarded.

**5. Verification.**
The final answer (a string of `u/d/l/r` moves, with capital letters for pushes) is replayed by an independent function that applies the real rules. The result is reported as `Verified ... OK`.

## Requirements

- Python 3.8 or newer
- The terminal solver needs nothing else (standard library only).
- The game window needs pygame:

```
pip install pygame
```

> On very new Python versions (for example Python 3.14 on Windows) `pip install pygame` can fail because no prebuilt package exists yet. Use `pip install pygame-ce` instead. It is a drop-in replacement and the code works unchanged.

## How to run

Keep all files in the same folder.

**Game window**

```
python sokoban_game.py        # start at level 1
python sokoban_game.py 4      # start at level 4
```

| Key | Action |
| --- | --- |
| Arrow keys / WASD | Move (walk into a box to push it) |
| Z | Undo the last move |
| R | Restart the level |
| S | Let the AI solve the level from the current position |
| N / P | Next / previous level |
| Esc | Stop the AI, or quit |

**Terminal solver**

```
python sokoban_solver.py              # solve every level in levels.txt
python sokoban_solver.py 4            # solve level 4 only
python sokoban_solver.py 4 --animate  # also replay the solution step by step
```

On Mac or Linux, use `python3` instead of `python` if `python` is not found.

## Adding your own levels

Open `levels.txt` and add a level using the standard Sokoban symbols. Separate levels with a blank line, and start a line with `;` to give a level a title.

| Symbol | Meaning |
| --- | --- |
| `#` | Wall |
| `@` | Player |
| `$` | Box |
| `.` | Goal |
| `*` | Box on a goal |
| `+` | Player on a goal |

Every level needs exactly one player and the same number of boxes as goals.

## Example results

| Level | Pushes | Total moves | States expanded |
| --- | --- | --- | --- |
| Level 2 | 8 | 33 | 14 |
| Level 3 | 3 | 10 | 5 |
| Level 4 | 13 | 41 | 45 |

Level 5 is deliberately impossible (a box starts in a corner), and the solver correctly reports that there is no solution.

## Project files

| File | Purpose |
| --- | --- |
| `sokoban_solver.py` | The AI: level parsing, dead squares, deadlock detection, A\* search, solution checker, terminal interface |
| `sokoban_game.py` | The pygame window that uses the solver |
| `levels.txt` | The puzzles |

## Limitations and ideas for future work

- The heuristic lets every box pick its nearest goal. Matching boxes to goals one-to-one would give a better estimate and a faster search.
- Freeze-deadlock detection helped only slightly on the small test levels. Its benefit should be larger on big, crowded puzzles, but that has not been tested here.
- Other deadlock types (such as corral deadlocks) are not detected yet.
- Very large puzzles may take a long time. The solver has a time limit per level.
- The game does not save progress between sessions.

## Team

Built by:

- [Shaurya Srivastava] (https://github.com/shaurya710)
  
