import argparse
import json
import os

import subprocess

import sys
from PIL import Image
from PIL import ImageOps

from common import get_default_vboxmanage
from vmm import VBoxManage

script_path = os.path.dirname(os.path.abspath(__file__))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("vm_name",
                        help="Name of the VirtualBox virtual machine to work with")
    parser.add_argument("--vboxmanage",
                        help="path to VBoxManage.exe",
                        default=get_default_vboxmanage())
    return parser.parse_args()


def fourbox(x, y, width, height):
    left = x
    right = left + width
    upper = y
    lower = upper + height
    return left, upper, right, lower


def put_box_around(image, border=1, color="white"):
    """
    :type image: Image.Image
    :return: Image.Image
    """
    output = Image.new("RGB", (image.width + border * 2, image.height + border * 2), color)
    output.paste(image, box=fourbox(1, 1, image.width, image.height))
    return output


def cut_up_textmode(image, ch_width=8, ch_height=14, line_height=None, line_offset=0):
    """
    Iterate through the fixed size characters in the given image
    :type image: Image.Image
    :type ch_width: int
    :type ch_height: int
    :type line_height: int or None
    :type line_offset: int
    """

    if line_height is None:
        line_height = ch_height

    assert ch_height + line_offset <= line_height, "went off the bottom of ch -- ch height %s line offset %d line height %d" % (ch_height, line_offset, line_height)

    assert image.width % ch_width == 0, "image width %d is not a multiple of %d" % (image.width, ch_width)
    assert image.height % line_height == 0, "image height %d is not a multiple of %d" % (image.height, line_height)

    text_width = image.width / ch_width
    text_height = image.height / line_height

    print "reading text %dx%d" % (text_width, text_height)

    for row in range(text_height):
        for col in range(text_width):

            ch_image = image.crop(fourbox(col * ch_width, row * line_height + line_offset, ch_width, ch_height))

            yield (row, col, ch_image)

    print image


def inverse_map(d):
    out = {}
    for key, val in d.iteritems():
        out[val] = key
    return out


def not_key(key, ch_width):
    key = list(key)
    return tuple([x ^ ((1 << ch_width) - 1) for x in key])


def read_textmode(image, ch_map, ch_map_filename, ch_width, ch_height, line_height):
    if ch_map is None:
        ch_map = {}

    ch_unmap = inverse_map(ch_map)

    text_lines = []

    prev_row = None
    cur_line = None
    for row, col, ch_image in cut_up_textmode(image, ch_width, ch_height, line_height):
        # ch_image.show()
        key = ch_bit_values(ch_image, ch_width)
        ch = ch_map.get(key)
        if ch is None:
            # check for reverse video
            ch = ch_map.get(not_key(key, ch_width))

        if row != prev_row:
            cur_line = []
            text_lines.append(cur_line)
            prev_row = row

        if ch is None:
            boxed = put_box_around(ch_image)
            while True:
                boxed.show("Unknown character")
                print "%s (%d,%d) Enter character:" % (ch_map_filename, row, col)
                line_of_input = sys.stdin.readline().decode("utf-8")
                assert line_of_input.endswith("\n")
                ch = line_of_input[:-1]
                if len(ch) != 1:
                    continue
                break
            if ch in ch_unmap:
                old_key = ch_unmap[ch]
                print "(%d,%d) %s: old value %r new value %r" % (row, col, ch, old_key, key)
            ch_map[key] = ch
            save_map(ch_map, ch_map_filename)

        cur_line.append(ch)

    return ["".join(chars) for chars in text_lines]


def ch_bit_values(ch_image, ch_width, left_shift_pixels=0):
    """:type ch_image: Image.Image"""
    assert len(ch_image.mode) == 1, "Expected 1-channel image"
    assert ch_image.width == ch_width

    vals = []
    for y in range(ch_image.height):
        value = 0
        mask = 1
        for x in range(ch_width):
            pix = ch_image.getpixel((x, y))
            if pix:
                value = value | mask
            mask <<= 1
        value <<= left_shift_pixels
        vals.append(value)
    return tuple(vals)


def pause():
    print "press return to continue"
    sys.stdin.readline()


def init_textmode(ch_width, ch_height, line_height, line_offset, init_image, ch_map_filename,
                  left_shift_pixels=1, invert=True):
    ch_map = load_map(ch_map_filename, ch_height)

    # sample_image_filename = os.path.join(script_path, "tga-8x14-437.png")
    sample_image_filename = os.path.join(script_path, init_image)
    sample_image = Image.open(sample_image_filename)
    assert isinstance(sample_image, Image.Image)

    # sample = sample_image.crop(fourbox(0, 0, 32 * 8, 8 * 14))
    sample_greyscale = sample_image.convert("L", dither=Image.NONE)
    if invert:
        sample_greyscale = ImageOps.invert(sample_greyscale)
    # sample_greyscale.show()

    show_chars = [ord(x) for x in ""]
    for row, col, ch_image in cut_up_textmode(sample_greyscale, ch_width=ch_width, ch_height=ch_height,
                                              line_height=line_height, line_offset=line_offset):
        ch_num = row * 32 + col
        if ch_num in show_chars:
            print "showing %s" % chr(ch_num)
            ch_image.show()
            pause()
        key = ch_bit_values(ch_image, ch_width, left_shift_pixels=left_shift_pixels)
        if key not in ch_map:
            ch_map[key] = chr(ch_num)
            save_map(ch_map, ch_map_filename)

    return ch_map


def save_map(ch_map, ch_map_filename):
    flat_map = [(key, ord(value)) for key, value in ch_map.iteritems()]
    with open(ch_map_filename, "w") as handle:
        json.dump(flat_map, handle, sort_keys=True, indent=4, separators=(',', ': '))


def load_map(ch_map_filename, ch_height):
    if os.path.exists(ch_map_filename):
        with open(ch_map_filename, "r") as handle:
            flat_map = json.load(handle)
            ch_map = {}
            for key, value in flat_map:
                if len(key) > ch_height:
                    key = key[:ch_height]
                ch_map[tuple(key)] = chr(value)
    else:
        ch_map = {}
    return ch_map


class TextReader(object):
    def __init__(self, ch_width=8, ch_height=14, init_line_height=None, init_line_offset=1, init_image="pgcfont.png",
                 init_left_shift_pixels=1, init_invert=True,
                 ch_map_filename=os.path.join(script_path, "ch_map.json"),
                 normal_line_height=None):

        self.ch_map_filename = ch_map_filename
        self.ch_width = ch_width
        self.ch_height = ch_height

        if init_line_height is None:
            init_line_height = ch_height
        if normal_line_height is None:
            normal_line_height = ch_height

        self.line_height = normal_line_height

        if init_image is not None:
            self.ch_map = init_textmode(ch_width, ch_height, init_line_height, init_line_offset, init_image, ch_map_filename,
                                        init_left_shift_pixels, init_invert)
        else:
            self.ch_map = {}

        # prefer space for empty bitmap
        self.ch_map[tuple([0] * ch_height)] = " "

    def read(self, vm):
        """:type vm: VBoxManage"""

        ss_original, ss_filename = vm.get_screenshot()
        ss = ss_original.convert("L", dither=Image.NONE)

        lines = read_textmode(ss, self.ch_map, self.ch_map_filename, self.ch_width, self.ch_height, self.line_height)

        ss_original.close()
        if os.path.exists(ss_filename):
            os.remove(ss_filename)

        return lines


def main():
    options = parse_args()
    vboxmanage = options.vboxmanage
    vm_name = options.vm_name
    subprocess.check_call([vboxmanage, "list", "screenshotformats"])

    sr = TextReader(init_line_height=16)
    vm = VBoxManage(vboxmanage, vm_name)
    lines = sr.read(vm)
    # for line in lines:
    #     print line


if __name__ == "__main__":
    main()