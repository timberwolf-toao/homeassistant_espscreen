"""Album covers for the renders and the README (tools/render/run.py, the media stage): drawn here, so no real record's
artwork is ever shown. Each seed is another cover in one of a few calm styles (a low sun over hills, waves, an aurora,
rings, rain on a city), in colours that read as a record shelf and give the media card a ground of their own.

    python3 tools/render/media_art.py out/      writes a sheet of every cover, to look at them
"""
import io
import math
import random
import sys

from PIL import Image, ImageDraw, ImageFilter

# (sky top, sky bottom, accent, dark) per palette; a cover takes one by its seed.
PALETTES = [
    ((28, 19, 72), (222, 98, 76), (252, 196, 112), (34, 18, 40)),
    ((10, 40, 70), (40, 140, 160), (230, 240, 230), (8, 30, 48)),
    ((20, 24, 40), (60, 40, 110), (90, 230, 170), (12, 14, 26)),
    ((240, 196, 150), (226, 120, 100), (90, 40, 70), (60, 30, 50)),
    ((16, 60, 52), (120, 180, 120), (250, 230, 160), (12, 40, 34)),
    ((30, 30, 34), (90, 90, 100), (240, 80, 90), (16, 16, 20)),
    ((70, 30, 90), (220, 110, 160), (255, 220, 150), (40, 16, 50)),
    ((200, 220, 230), (120, 160, 200), (30, 60, 110), (20, 40, 80)),
]

# What the renders call them: titles and artists of no real record.
ALBUMS = [('Low Sun', 'Nova Coast'), ('Tidal Rooms', 'Harbour Lights'), ('Northern Hours', 'Aurora Field'),
          ('Paper Moons', 'The Quiet Kind'), ('Green Fold', 'Willow & Fern'), ('City Rain', 'Night Tram'),
          ('Velvet Hours', 'Juno Bay'), ('Glass Garden', 'Winter Arcade'), ('Slow Orbit', 'Satellite Choir'),
          ('Afterglow', 'Nova Coast'), ('Small Rooms', 'Lena Vos'), ('Static Bloom', 'Paper Planes'),
          ('Salt & Cedar', 'Harbour Lights'), ('Blue Hour', 'Juno Bay'), ('Open Water', 'Aurora Field'),
          ('Late Bloomers', 'The Quiet Kind'), ('Copper Sky', 'Night Tram'), ('Field Notes', 'Willow & Fern'),
          ('Lanterns', 'Winter Arcade'), ('Sea Glass', 'Lena Vos'), ('Neon Harbour', 'Satellite Choir'),
          ('Morning Tide', 'Paper Planes'), ('Quiet Engines', 'Night Tram'), ('Snowline', 'Aurora Field')]
# One title long enough to need two lines, the way real ones do.
LONG_ALBUM = 'Songs for the Long Way Home, Part Two'
PLAYLISTS = ['Sunday Morning', 'Deep Focus', 'Dinner Party', 'Road Trip', 'Rainy Day', 'Late Night Jazz', 'Workout', 'Wind Down']


def _gradient(size, top, bottom):
    image = Image.new('RGB', (1, 256))
    for y in range(256):
        t = y / 255
        image.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return image.resize((size, size))


def cover(seed, size=640):
    """One cover as a PIL image, the same for the same seed."""
    rng = random.Random(seed * 7919 + 13)
    top, bottom, accent, dark = PALETTES[seed % len(PALETTES)]
    image = _gradient(size, top, bottom)
    draw = ImageDraw.Draw(image, 'RGBA')
    style = seed % 5
    s = size
    if style == 0:   # a low sun over hills
        r = s * rng.uniform(0.18, 0.26)
        cx, cy = s * rng.uniform(0.35, 0.65), s * rng.uniform(0.5, 0.62)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=accent + (235,))
        for layer, shade in enumerate((0.55, 0.35, 0.0)):
            base = s * (0.62 + 0.12 * layer)
            points = [(0, s)]
            for x in list(range(0, s, s // 16)) + [s]:
                points.append((x, base - rng.uniform(0, s * 0.12)))
            points.append((s, s))
            colour = tuple(round(d + (b - d) * shade) for d, b in zip(dark, bottom))
            draw.polygon(points, fill=colour)
    elif style == 1:  # waves
        for n in range(9):
            y = s * (0.35 + n * 0.08)
            amp, phase = s * rng.uniform(0.02, 0.05), rng.uniform(0, math.tau)
            points = [(x, y + amp * math.sin(x / s * math.tau * 1.5 + phase)) for x in range(0, s + 1, 8)]
            colour = tuple(round(a + (d - a) * n / 9) for a, d in zip(accent, dark))
            draw.polygon(points + [(s, s), (0, s)], fill=colour + (200,))
    elif style == 2:  # an aurora over a dark line of trees
        glow = Image.new('RGBA', (s, s))
        g = ImageDraw.Draw(glow)
        for n in range(5):
            x0 = s * rng.uniform(-0.2, 0.6)
            g.ellipse((x0, s * rng.uniform(0.05, 0.3), x0 + s * 0.8, s * rng.uniform(0.45, 0.6)), fill=accent + (70,))
        image.paste(glow.filter(ImageFilter.GaussianBlur(s // 14)), (0, 0), glow.filter(ImageFilter.GaussianBlur(s // 14)))
        draw = ImageDraw.Draw(image, 'RGBA')
        for x in range(0, s, s // 24):
            h = s * rng.uniform(0.12, 0.24)
            draw.polygon([(x, s), (x + s // 48, s * 0.82 - h), (x + s // 24, s)], fill=dark)
        draw.rectangle((0, s * 0.92, s, s), fill=dark)
        for _ in range(60):
            x, y = rng.uniform(0, s), rng.uniform(0, s * 0.5)
            draw.ellipse((x, y, x + 2, y + 2), fill=(255, 255, 255, 160))
    elif style == 3:  # rings
        cx, cy = s * 0.5, s * 0.5
        for n in range(7, 0, -1):
            r = s * 0.07 * n
            colour = accent if n % 2 else dark
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=colour + (220,), width=max(2, s // 60))
        draw.ellipse((cx - s * 0.05, cy - s * 0.05, cx + s * 0.05, cy + s * 0.05), fill=accent)
    else:            # rain on a city
        for n in range(14):
            w = s * rng.uniform(0.05, 0.11)
            x = rng.uniform(-w, s)
            h = s * rng.uniform(0.25, 0.6)
            draw.rectangle((x, s - h, x + w, s), fill=dark + (235,))
            for wy in range(int(s - h + 10), s - 6, max(6, s // 40)):
                if rng.random() < 0.35:
                    draw.rectangle((x + 4, wy, x + w - 4, wy + max(2, s // 120)), fill=accent + (200,))
        for _ in range(140):
            x, y = rng.uniform(0, s), rng.uniform(0, s)
            draw.line((x, y, x - s * 0.01, y + s * 0.05), fill=(255, 255, 255, 60), width=1)
    return image


def png(seed, size=640):
    out = io.BytesIO()
    cover(seed, size).save(out, 'PNG')
    return out.getvalue()


if __name__ == '__main__':
    sheet = Image.new('RGB', (4 * 200, 3 * 200))
    for n in range(12):
        sheet.paste(cover(n, 200), ((n % 4) * 200, (n // 4) * 200))
    target = sys.argv[1] if len(sys.argv) > 1 else '.'
    sheet.save(f'{target}/media-art-sheet.png')
