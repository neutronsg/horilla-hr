"""Render Neutron mark assets (favicons, fallback logos) from vector polygons traced from the wordmark."""
import sys
from PIL import Image, ImageDraw
NAVY, CYAN = (5, 28, 151, 255), (8, 217, 214, 255)
# Three slanted bars in an 82 x 56 box (traced from neutron-email-logo.png); rounded by stroking edges.
SHAPES = [
    (NAVY, [(11, 3), (15, 3), (25, 21), (17.5, 53), (13.5, 53), (1, 35)]),
    (CYAN, [(31, 3), (36, 3), (55, 35), (52, 53), (47.5, 53), (27.5, 21)]),
    (NAVY, [(66.5, 3), (70.5, 3), (81, 21), (74.5, 53), (70.5, 53), (57, 35)]),
]
R = 4.2  # corner radius in box units
def _inset(pts, k=0.82):
    cx = sum(x for x, _ in pts) / len(pts); cy = sum(y for _, y in pts) / len(pts)
    return [(round(cx + (x - cx) * k, 2), round(cy + (y - cy) * k, 2)) for x, y in pts]
SHAPES = [(c, _inset(p)) for c, p in SHAPES]

def svg(view=(-2, -15, 86, 86)):
    paths = []
    for color, pts in SHAPES:
        hexc = '#%02x%02x%02x' % color[:3]
        d = 'M' + ' L'.join(f'{x:g} {y:g}' for x, y in pts) + ' Z'
        paths.append(f'<path d="{d}" fill="{hexc}" stroke="{hexc}" stroke-width="{2*R:g}" stroke-linejoin="round"/>')
    v = ' '.join(f'{n:g}' for n in view)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{v}">{"".join(paths)}</svg>\n'

def render(size, pad=0.14, bg=None, box=None):
    ss = 8; W = H = size * ss
    im = Image.new('RGBA', (W, H), bg or (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    bw, bh = 82 + 2 * R, 56 + 2 * R
    scale = (W * (1 - 2 * pad)) / max(bw, bh)
    ox = (W - bw * scale) / 2 + R * scale; oy = (H - bh * scale) / 2 + R * scale
    for color, pts in SHAPES:
        P = [(ox + x * scale, oy + y * scale) for x, y in pts]
        dr.polygon(P, fill=color); r = R * scale
        for i, (x, y) in enumerate(P):
            x2, y2 = P[(i + 1) % len(P)]
            dr.line([(x, y), (x2, y2)], fill=color, width=int(2 * r))
            dr.ellipse([x - r, y - r, x + r, y + r], fill=color)
    return im.resize((size, size), Image.LANCZOS)

out = sys.argv[1]
open(f'{out}/favicon.svg', 'w').write(svg())
open(f'{out}/logo.svg', 'w').write(svg((-2, -2, 86, 60)))
for n in (16, 32):
    render(n, pad=0.04).save(f'{out}/favicon-{n}x{n}.png')
ico = render(256, pad=0.04); ico.save(f'{out}/favicon.ico', sizes=[(16, 16), (32, 32), (48, 48)])
render(180, pad=0.16, bg=(255, 255, 255, 255)).convert('RGB').save(f'{out}/apple-touch-icon.png')
for n in (192, 512):
    render(n, pad=0.18, bg=(255, 255, 255, 255)).convert('RGB').save(f'{out}/android-chrome-{n}x{n}.png')
# company-logo fallback (was the gorilla, 500x528): mark on transparent
mark = render(500, pad=0.08); canvas = Image.new('RGBA', (500, 528), (0, 0, 0, 0)); canvas.alpha_composite(mark, (0, 14)); canvas.save(f'{out}/horilla-logo.png')
# auth wordmark (was grey "Horilla", 200x54): Neutron wordmark centred
wm = Image.open(sys.argv[2]).convert('RGBA'); h = 30; wm = wm.resize((round(wm.width * h / wm.height), h), Image.LANCZOS)
canvas = Image.new('RGBA', (200, 54), (0, 0, 0, 0)); canvas.alpha_composite(wm, ((200 - wm.width) // 2, (54 - h) // 2)); canvas.save(f'{out}/auth-logo.png')
print('ok')
