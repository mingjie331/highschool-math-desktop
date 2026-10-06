from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
root = Path(__file__).resolve().parents[1]
image = Image.new('RGBA', (256,256), (244,241,234,255))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((8,8,248,248), radius=52, fill='#135d54')
font = ImageFont.truetype('C:/Windows/Fonts/timesbd.ttf', 180)
draw.text((59,8), 'Σ', font=font, fill='#f7e9be')
draw.line((63,214,195,214),fill='#b98a3d',width=7)
image.save(root / 'desktop/icon.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
image.save(root / 'desktop/icon.png')
