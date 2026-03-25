from PIL import Image, ImageDraw
import os, sys

base = os.path.dirname(os.path.abspath(__file__))
out  = os.path.join(base, 'web', 'static', 'favicon.ico')

img = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
d   = ImageDraw.Draw(img)

PURPLE = (168, 85,  247, 255)
LPURP  = (192, 132, 252, 255)
PINK   = (236, 72,  153, 255)
DARK   = (26,  16,  48,  255)
DARKER = (18,  13,  32,  255)

d.rounded_rectangle([4, 13, 28, 27], radius=4, fill=DARK,   outline=PURPLE, width=1)
d.rounded_rectangle([8,  5, 24, 15], radius=3, fill=DARKER, outline=PURPLE, width=1)
d.rounded_rectangle([10, 7, 15, 12], radius=1, fill=PURPLE)
d.rounded_rectangle([17, 7, 22, 12], radius=1, fill=PINK)
d.line([16, 5, 16, 2], fill=PURPLE, width=2)
d.ellipse([14, 0, 18, 4], fill=PINK)
d.ellipse([10, 19, 12, 21], fill=PURPLE)
d.ellipse([15, 19, 17, 21], fill=LPURP)
d.ellipse([20, 19, 22, 21], fill=PINK)

img.save(out, format='ICO', sizes=[(32, 32), (16, 16)])
print(f'Favicon saved to {out}')
