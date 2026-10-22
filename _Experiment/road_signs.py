"""
Road signs drawn with CARLA's debug lines: CARLA has no sign props with text, and debug text
(draw_string) does not show in camera images, but debug lines do.

A sign is a board filled with colored lines, with text and arrows on it, also lines. Debug lines
cannot be removed, so they are drawn with a short life time and redrawn before it ends
(RoadSigns.tick): they disappear by themselves a few seconds after the program stops.
"""

import collections

import carla

# Stroke font on a 4 x 6 grid (x right, y up), one list of polylines per character.
FONT = {
    ' ': [],
    'A': [[(0, 0), (0, 4), (2, 6), (4, 4), (4, 0)], [(0, 3), (4, 3)]],
    'C': [[(4, 6), (0, 6), (0, 0), (4, 0)]],
    'D': [[(0, 0), (0, 6), (3, 6), (4, 5), (4, 1), (3, 0), (0, 0)]],
    'E': [[(4, 6), (0, 6), (0, 0), (4, 0)], [(0, 3), (3, 3)]],
    'I': [[(2, 0), (2, 6)], [(1, 6), (3, 6)], [(1, 0), (3, 0)]],
    'K': [[(0, 0), (0, 6)], [(4, 6), (0, 2)], [(1.5, 3.5), (4, 0)]],
    'L': [[(0, 6), (0, 0), (4, 0)]],
    'M': [[(0, 0), (0, 6), (2, 3), (4, 6), (4, 0)]],
    'N': [[(0, 0), (0, 6), (4, 0), (4, 6)]],
    'O': [[(0, 0), (0, 6), (4, 6), (4, 0), (0, 0)]],
    'R': [[(0, 0), (0, 6), (4, 6), (4, 3), (0, 3), (4, 0)]],
    'S': [[(4, 6), (0, 6), (0, 3), (4, 3), (4, 0), (0, 0)]],
    'T': [[(0, 6), (4, 6)], [(2, 6), (2, 0)]],
    'W': [[(0, 6), (1, 0), (2, 3), (3, 0), (4, 6)]],
    'X': [[(0, 0), (4, 6)], [(0, 6), (4, 0)]],
    'k': [[(0, 0), (0, 6)], [(3, 4), (0, 1.5)], [(1, 2.2), (3, 0)]],
    'm': [[(0, 0), (0, 4), (2, 4), (2, 0)], [(2, 4), (4, 4), (4, 0)]],
    '0': [[(0, 0), (0, 6), (4, 6), (4, 0), (0, 0)]],
    '1': [[(1, 5), (2, 6), (2, 0)], [(1, 0), (3, 0)]],
    '2': [[(0, 6), (4, 6), (4, 3), (0, 3), (0, 0), (4, 0)]],
    '3': [[(0, 6), (4, 6), (4, 0), (0, 0)], [(1, 3), (4, 3)]],
    '4': [[(3, 0), (3, 6), (0, 2), (4, 2)]],
    '5': [[(4, 6), (0, 6), (0, 3), (4, 3), (4, 0), (0, 0)]],
    '6': [[(4, 6), (0, 6), (0, 0), (4, 0), (4, 3), (0, 3)]],
    '7': [[(0, 6), (4, 6), (1, 0)]],
    '8': [[(0, 0), (0, 6), (4, 6), (4, 0), (0, 0)], [(0, 3), (4, 3)]],
    '9': [[(4, 3), (0, 3), (0, 6), (4, 6), (4, 0), (0, 0)]],
}
ADVANCE = 5.5        # grid units from one character to the next
# Debug lines are self-lit and very bright: a color of a few units already looks like a sunlit
# painted sign, more than about 10 glows white and smears the letters.
WHITE = carla.Color(6, 6, 6)
GREEN = carla.Color(0, 2, 0)         # highway direction sign
ORANGE = carla.Color(5, 1, 0)        # work zone sign
POST = carla.Color(1, 1, 1)
FILL = 0.22          # m between the lines that fill the board
LIFE = 3.0           # seconds a drawn line lasts
REDRAW = 2.0         # seconds between redraws (before LIFE ends, so the signs never blink)


def text_width(text):
    return (len(text) * ADVANCE - (ADVANCE - 4)) if text else 0.0


class Sign(object):
    """A sign facing the traffic on `waypoint`, `offset` m right of its center, its bottom
    `height` m above the road. Lines of text are centered; 'arrow' draws an arrow instead.
    letter: letter height in m."""

    def __init__(self, waypoint, offset, height, lines, color, letter=1.05, arrow=None):
        self.segments = []   # (start, end, thickness, color)
        transform = waypoint.transform
        self._origin = transform.location
        self._right = transform.get_right_vector()
        self._forward = transform.get_forward_vector()
        self._offset = offset
        unit = letter / 6.0
        gap = 0.45 * letter
        widths = [text_width(line) * unit for line in lines]
        arrow_height = 1.2 * letter if arrow else 0.0
        width = max(widths + [arrow_height * 1.6]) + 2 * gap
        rows = len(lines) * letter + (len(lines) - 1) * gap + (arrow_height + gap if arrow else 0.0)
        total = rows + 2 * gap
        bottom = height
        # the board: filled with horizontal lines, behind the text
        y = bottom
        while y <= bottom + total:
            self._add((-width / 2, y), (width / 2, y), FILL, color, depth=-0.05)
            y += FILL
        # posts down to the road
        for x in (-width / 2 + 0.3, width / 2 - 0.3):
            self._add((x, 0.0), (x, bottom), 0.15, POST)
        top = bottom + total - gap
        for line, line_width in zip(lines, widths):
            left = -line_width / 2
            base = top - letter
            for i, char in enumerate(line):
                for stroke in FONT[char]:
                    points = [(left + (i * ADVANCE + x) * unit, base + y * unit) for x, y in stroke]
                    for a, b in zip(points, points[1:]):
                        self._add(a, b, 0.08, WHITE)
            top = base - gap
        if arrow:
            self._arrow(arrow, top - arrow_height, arrow_height)

    def _arrow(self, kind, bottom, size):
        """'right': pointing right; 'up_right': up and to the right (exit); 'left': merge left."""
        cx = 0.0
        if kind == 'up_right':
            a, b = (cx - 0.35 * size, bottom), (cx + 0.35 * size, bottom + size)
            head = [(b[0] - 0.45 * size, b[1]), b, (b[0], b[1] - 0.45 * size)]
        elif kind == 'right':
            a, b = (cx - 0.8 * size, bottom + size / 2), (cx + 0.8 * size, bottom + size / 2)
            head = [(b[0] - 0.4 * size, b[1] + 0.4 * size), b, (b[0] - 0.4 * size, b[1] - 0.4 * size)]
        else:  # left
            a, b = (cx + 0.8 * size, bottom + size / 2), (cx - 0.8 * size, bottom + size / 2)
            head = [(b[0] + 0.4 * size, b[1] + 0.4 * size), b, (b[0] + 0.4 * size, b[1] - 0.4 * size)]
        self._add(a, b, 0.105, WHITE)
        self._add(head[0], head[1], 0.105, WHITE)
        self._add(head[1], head[2], 0.105, WHITE)

    def _add(self, a, b, thickness, color, depth=0.05):
        self.segments.append((self._point(a, depth), self._point(b, depth), thickness, color))

    def _point(self, xy, depth):
        """Sign coordinates (x right as seen by the driver, y up) to the world, `depth` m toward the driver."""
        x, y = xy
        o, r, f = self._origin, self._right, self._forward
        side = self._offset + x
        return carla.Location(o.x + r.x * side - f.x * depth, o.y + r.y * side - f.y * depth, o.z + y)


class RoadSigns(object):
    """Keeps signs drawn: add() them, call tick() every frame.

    Every debug line is a call to the server, so the lines are redrawn a few per frame, each
    one REDRAW s after it was last drawn, instead of all at once (a visible hitch).
    """

    MAX_PER_FRAME = 60

    def __init__(self, sim_world):
        self._debug = sim_world.debug
        self._queue = collections.deque()  # (due time, segment), oldest first

    def add(self, sign):
        for segment in sign.segments:
            self._queue.appendleft((0.0, segment))  # due now

    def tick(self, now):
        drawn = 0
        while self._queue and self._queue[0][0] <= now and drawn < self.MAX_PER_FRAME:
            _, (start, end, thickness, color) = self._queue.popleft()
            self._debug.draw_line(start, end, thickness=thickness, color=color, life_time=LIFE)
            self._queue.append((now + REDRAW, (start, end, thickness, color)))
            drawn += 1
