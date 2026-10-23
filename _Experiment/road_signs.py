"""
Road signs drawn with CARLA's debug lines: CARLA has no sign props with text, and debug text
(draw_string) does not show in camera images, but debug lines do.

A sign is a board filled with colored lines, with text and arrows on it, also lines. An image
sign (ImageSign) is a picture, e.g. a triangular warning sign, traced into rows of colored lines.
Debug lines cannot be removed, so they are drawn with a short life time and redrawn before it ends
(RoadSigns.tick): they disappear by themselves a few seconds after the program stops.
"""

import collections
import functools

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
LINE_BRIGHTNESS = 6  # debug line color for full 255 (WHITE): image colors are scaled down to it
# Image signs: each pixel becomes the nearest of these standard sign colors, kept if the image
# really uses it (IMAGE_COLOR_SHARE of its close matches), so blended edge pixels add no new colors.
SIGN_PALETTE = [(230, 0, 18), (255, 225, 0), (255, 140, 0), (30, 30, 30), (255, 255, 255), (0, 80, 180),
                (0, 140, 70)]
IMAGE_COLOR_SHARE = 0.02
IMAGE_PIXELS = 72    # image sign: pixels across (rows follow the image's aspect)
FILL = 0.22          # m between the lines that fill the board
LIFE = 3.0           # seconds a drawn line lasts
REDRAW = 2.0         # seconds between redraws (before LIFE ends, so the signs never blink)


def text_width(text):
    return (len(text) * ADVANCE - (ADVANCE - 4)) if text else 0.0


class _Board(object):
    """Something flat facing the traffic on `waypoint`, `offset` m right of its center, drawn in
    sign coordinates (x right as seen by the driver, y up from the road)."""

    def __init__(self, waypoint, offset):
        self.segments = []   # (start, end, thickness, color)
        transform = waypoint.transform
        self._origin = transform.location
        self._right = transform.get_right_vector()
        self._forward = transform.get_forward_vector()
        self._offset = offset

    def _add(self, a, b, thickness, color, depth=0.05):
        self.segments.append((self._point(a, depth), self._point(b, depth), thickness, color))

    def _point(self, xy, depth):
        """Sign coordinates to the world, `depth` m toward the driver."""
        x, y = xy
        o, r, f = self._origin, self._right, self._forward
        side = self._offset + x
        return carla.Location(o.x + r.x * side - f.x * depth, o.y + r.y * side - f.y * depth, o.z + y)


class Sign(_Board):
    """A sign facing the traffic on `waypoint`, `offset` m right of its center, its bottom
    `height` m above the road. Lines of text are centered; 'arrow' draws an arrow instead.
    letter: letter height in m. top: height of the board's top edge."""

    def __init__(self, waypoint, offset, height, lines, color, letter=1.05, arrow=None):
        super(Sign, self).__init__(waypoint, offset)
        unit = letter / 6.0
        gap = 0.45 * letter
        widths = [text_width(line) * unit for line in lines]
        arrow_height = 1.2 * letter if arrow else 0.0
        width = max(widths + [arrow_height * 1.6]) + 2 * gap
        rows = len(lines) * letter + (len(lines) - 1) * gap + (arrow_height + gap if arrow else 0.0)
        total = rows + 2 * gap
        bottom = height
        self.top = bottom + total
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


class ImageSign(_Board):
    """A picture (e.g. a triangular warning sign, PNG) facing the traffic on `waypoint`, `offset`
    m right of its center, `width` m wide, its bottom `height` m above the road, on one post down
    to `post_from` m (the top of a plate under it, or the road). The white around the sign in the
    image (connected to its corners) is left out, so only the sign's own shape shows."""

    def __init__(self, waypoint, offset, height, path, width=2.4, post_from=0.0):
        super(ImageSign, self).__init__(waypoint, offset)
        rows, colors = _trace(path, IMAGE_PIXELS)
        pixel = width / IMAGE_PIXELS
        self.top = height + len(rows) * pixel
        self._add((0.0, post_from), (0.0, height + 0.5 * len(rows) * pixel), 0.12, POST, depth=-0.05)
        for row, runs in enumerate(rows):
            y = self.top - (row + 0.5) * pixel
            for start, end, color in runs:  # one line per run of equal pixels, a little thicker so rows close up
                self._add((start * pixel - width / 2, y), (end * pixel - width / 2, y), pixel * 1.15, colors[color])


@functools.lru_cache(maxsize=None)
def _trace(path, pixels):
    """The image at `path` as rows of runs (start, end, color index) across `pixels` columns,
    and the debug line colors. Needs Pillow; done once per image."""
    from PIL import Image, ImageDraw  # only image signs need it
    source = Image.open(path).convert('RGB')
    key = (255, 0, 255)
    filled = source.copy()
    for corner in ((0, 0), (source.width - 1, 0), (0, source.height - 1), (source.width - 1, source.height - 1)):
        ImageDraw.floodfill(filled, corner, key, thresh=60)  # the white around the sign
    alpha = Image.frombytes('L', source.size, bytes(0 if p == key else 255 for p in filled.get_flattened_data()))
    box = alpha.getbbox()
    source, alpha = source.crop(box), alpha.crop(box)

    def nearest(color, palette):
        return min(range(len(palette)), key=lambda i: sum((color[k] - palette[i][k]) ** 2 for k in range(3)))

    # the standard colors this image really uses
    counts = [0] * len(SIGN_PALETTE)
    sample = source.resize((max(1, source.width // 4), max(1, source.height // 4)))
    for color, a in zip(sample.get_flattened_data(), alpha.resize(sample.size).get_flattened_data()):
        if a >= 128:
            i = nearest(color, SIGN_PALETTE)
            if sum((color[k] - SIGN_PALETTE[i][k]) ** 2 for k in range(3)) < 50 ** 2:
                counts[i] += 1
    palette = [c for c, n in zip(SIGN_PALETTE, counts) if n >= IMAGE_COLOR_SHARE * max(1, sum(counts))]

    height = max(1, round(pixels * source.height / source.width))
    small, small_alpha = source.resize((pixels, height), Image.BOX), alpha.resize((pixels, height), Image.BOX)
    rows = []
    for y in range(height):
        runs, current, start = [], None, 0
        for x in range(pixels + 1):
            color = None
            if x < pixels and small_alpha.getpixel((x, y)) >= 128:
                color = nearest(small.getpixel((x, y)), palette)
            if color != current:
                if current is not None:
                    runs.append((start, x, current))
                current, start = color, x
        rows.append(runs)
    colors = [carla.Color(*(int(round(v * LINE_BRIGHTNESS / 255.0)) for v in c)) for c in palette]
    return rows, colors


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
