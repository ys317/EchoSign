"""Regenerate the small EchoSign waveform icon with Pillow."""
from pathlib import Path

from PIL import Image, ImageDraw


def main():
    image = Image.new("RGBA", (256, 256))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((12, 12, 244, 244), radius=56, fill="#456eb8")
    for index, height in enumerate((64, 128, 94, 150)):
        x = 63 + 35 * index
        draw.rounded_rectangle(
            (x, 128 - height / 2, x + 20, 128 + height / 2),
            radius=8, fill="#ffffff")
    image.save(Path(__file__).with_name("echosign.ico"),
               sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    main()
