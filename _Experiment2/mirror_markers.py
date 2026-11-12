#!/usr/bin/env python

"""
The ArUco markers on the side monitors' bezels (marker_plan.jpg): with them each scene camera frame
of the Glasses 2 gives where the monitor is, so the gaze can be put in the monitor's pixels and the
mirror glances told from the window (the mirrors are where carla_base._mirror_rect draws them),
even with the mirror at or past the frame's edge.

    python _Experiment2/mirror_markers.py         mirror_markers/mirror_markers.pdf (A4, print at 100 %)

MARKERS: the name on marker_plan.jpg -> ArUco id (DICT_4X4_50), the monitor it is on, and where.
Print at 100 % (no "fit to page"): the 10 mm bar on the page must be 10 mm. Matte paper on thin
foam board, the white border kept; the card sticks out past the bezel (not over the screen) and is
fixed to the monitor itself.
"""

from __future__ import print_function

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, 'mirror_markers')
DICTIONARY = 'DICT_4X4_50'
MARKER_MM = 40.0            # the black square, edge to edge
QUIET_MM = 8.0              # white border round it (at least one module, 40 / 6 = 6.7 mm)
DPI = 300
MARKERS = {
    'L1': (0, 'left', 'bottom bezel, outer side'),
    'L2': (1, 'left', 'bottom bezel, under the left mirror'),
    'L3': (2, 'left', 'bottom bezel, inner end (by the middle monitor)'),
    'L4': (3, 'left', 'top bezel, inner end'),
    'R1': (10, 'right', 'top bezel, inner end (above the rear-view mirror)'),
    'R2': (11, 'right', 'top bezel, above the rear-view mirror'),
    'R3': (12, 'right', 'bottom bezel, inner end (by the middle monitor)'),
    'R4': (13, 'right', 'top bezel, outer end'),
    'R5': (14, 'right', 'outer side bezel, by the right mirror'),
    'R6': (15, 'right', 'bottom bezel, under the right mirror'),
}


MONITOR_INDEX = {'left': 0, 'right': 2}     # the experiment window's monitors, left to right
MONITOR_PX = (1920, 1080)                   # each monitor (the window: 3 x 1920 x 1080)


class Detector(object):
    """The markers in a Glasses 2 scene frame (960 x 540: a bezel marker is 16-26 px). The bezel
    markers sit dark against the lit monitors, so the frame is searched three times: at 2x, and at 3x
    after local contrast (CLAHE), plain and histogram-equalised first; the detector's thresholds are
    loose (test 261112_165310: L2-L4, R1-R3 in 80-100 % of the frames, eyes on the mirrors).
    Loose thresholds find other ids in the clutter too: only `ids` are kept, and a found id still
    needs checking against its neighbours (mirror_register, mirror_aoi)."""

    def __init__(self, ids=None):
        import cv2  # pylint: disable=import-outside-toplevel
        self.cv2 = cv2
        params = cv2.aruco.DetectorParameters()
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        params.adaptiveThreshWinSizeMin, params.adaptiveThreshWinSizeMax = 3, 33
        params.minMarkerPerimeterRate = 0.01
        params.adaptiveThreshConstant = 3
        params.minOtsuStdDev = 2.0
        params.polygonalApproxAccuracyRate = 0.05
        params.perspectiveRemovePixelPerCell = 8
        params.perspectiveRemoveIgnoredMarginPerCell = 0.2
        params.maxErroneousBitsInBorderRate = 0.5
        params.errorCorrectionRate = 0.8
        self.detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, DICTIONARY)),
                                                params)
        self.clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        self.ids = set(ids) if ids is not None else None

    def __call__(self, gray):
        """{id: 4 x 2 corners in the frame's px (top left, top right, bottom right, bottom left of the
        marker)}; an id found in more than one pass: the first."""
        cv2 = self.cv2
        found = {}
        passes = ((2, gray), (3, self.clahe.apply(gray)), (3, self.clahe.apply(cv2.equalizeHist(gray))))
        for scale, image in passes:
            corners, ids, _ = self.detector.detectMarkers(
                cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC))
            if ids is None:
                continue
            for c, i in zip(corners, ids.flatten()):
                i = int(i)
                if i not in found and (self.ids is None or i in self.ids):
                    found[i] = c.reshape(4, 2) / float(scale)
        return found


def mm(v):
    return int(round(v / 25.4 * DPI))


def main():
    import cv2  # pylint: disable=import-outside-toplevel
    from PIL import Image, ImageDraw, ImageFont  # pylint: disable=import-outside-toplevel

    os.makedirs(OUT_DIR, exist_ok=True)
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, DICTIONARY))
    page = Image.new('L', (mm(210), mm(297)), 255)
    draw = ImageDraw.Draw(page)
    try:
        font = ImageFont.truetype('arialbd.ttf', mm(5))
        small = ImageFont.truetype('arial.ttf', mm(2.6))
    except OSError:
        font = small = ImageFont.load_default()

    card = MARKER_MM + 2 * QUIET_MM              # the white card to cut out
    cols, cell_w, cell_h = 3, 64.0, 69.0         # 4 rows: the last labels end about 288 mm down
    x_off = (210.0 - cols * cell_w) / 2.0
    y_off = 18.0
    draw.text((mm(x_off), mm(8)), 'Mirror markers (ArUco %s, %d mm) - print at 100 %%, cut along the grey line'
              % (DICTIONARY, MARKER_MM), font=small, fill=0)
    # the scale check: 10 mm
    draw.rectangle([mm(x_off), mm(13), mm(x_off + 10), mm(14.5)], fill=0)
    draw.text((mm(x_off + 12), mm(12.3)), '= 10 mm (check after printing)', font=small, fill=0)

    for k, (name, (mid, monitor, where)) in enumerate(MARKERS.items()):
        col, row = k % cols, k // cols
        x0, y0 = x_off + col * cell_w + (cell_w - card) / 2.0, y_off + row * cell_h
        side = mm(MARKER_MM)
        marker = cv2.aruco.generateImageMarker(dictionary, mid, side, borderBits=1)
        page.paste(Image.fromarray(marker), (mm(x0 + QUIET_MM), mm(y0 + QUIET_MM)))
        # the cut line: light grey, at the card's edge (the white border inside it)
        draw.rectangle([mm(x0), mm(y0), mm(x0 + card), mm(y0 + card)], outline=170, width=2)
        # the name below the card (outside the white border: it is cut off or stays on the card's edge)
        draw.text((mm(x0), mm(y0 + card + 1.0)), '%s  (id %d, %s)' % (name, mid, monitor), font=font, fill=0)
        draw.text((mm(x0), mm(y0 + card + 6.5)), where, font=small, fill=90)

    pdf = os.path.join(OUT_DIR, 'mirror_markers.pdf')
    page.convert('RGB').save(pdf, 'PDF', resolution=DPI)
    page.save(os.path.join(OUT_DIR, 'mirror_markers.png'), dpi=(DPI, DPI))
    with open(os.path.join(OUT_DIR, 'markers.json'), 'w', encoding='utf-8') as handle:
        json.dump({'dictionary': DICTIONARY, 'marker_mm': MARKER_MM,
                   'markers': {n: {'id': i, 'monitor': m, 'where': w} for n, (i, m, w) in MARKERS.items()}},
                  handle, indent=2)
    print('written: %s' % pdf)


if __name__ == '__main__':
    main()
