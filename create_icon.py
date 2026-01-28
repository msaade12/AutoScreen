from PIL import Image, ImageDraw

# Create a 22x22 menu bar icon (camera/screenshot symbol)
size = 22
img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Draw a simple camera icon
# Camera body
draw.rounded_rectangle([2, 6, 20, 18], radius=2, fill=(0, 0, 0, 255))
# Lens
draw.ellipse([7, 8, 15, 16], fill=(255, 255, 255, 255))
draw.ellipse([9, 10, 13, 14], fill=(0, 0, 0, 255))
# Flash bump
draw.rectangle([4, 4, 8, 6], fill=(0, 0, 0, 255))

img.save('/Users/gta/SRC/ScreenshotTaker/icon_menubar.png')
print("Icon created: icon_menubar.png")
