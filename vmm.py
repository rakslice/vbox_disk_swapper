import os
import subprocess
import tempfile

import time
from PIL import Image


def dequote(s):
    """
    Convert a potentially double-quoted string, removing the quotes and backslash-unescaping quoted contents
    :type s: str
    :rtype: str
    """
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
        s = s.replace('\\"', '"')
        s = s.replace("\\\\", "\\")
    return s


def deprefix(s, prefix):
    """
    Remove the given prefix from the string s if present
    :type s: str
    :type prefix: str
    :return: str
    """
    if s.startswith(prefix):
        s = s[len(prefix):]
    return s


def read_vbox_pairs(output_str):
    """
    Read VirtualBox --machinereadable output as a list of key-value pairs
    :type output_str: str
    :rtype: list of (str, str)
    """
    pairs = []
    for line in output_str.split("\n"):
        if line == "":
            continue
        if line.endswith("\r"):
            line = line[:-1]
        key, value = line.split("=", 1)
        key = dequote(key)
        value = dequote(value)
        pairs.append((key, value))
    return pairs


SCANCODE_ENTER = 0x1c
SCANCODE_DOWN = 0x50
SCANCODE_UP = 0x48
SCANCODE_LEFT = 0x4b
SCANCODE_RIGHT = 0x4d
SCANCODE_N = 0x31
SCANCODE_Y = 0x15
SCANCODE_SPACE = 0x39
SCANCODE_SHIFT = 0x2a

SCANCODE_PAGE_DOWN = 0x51  # keypad 3
SCANCODE_PAGE_UP = 0x49  # keypad 9

SCANCODE_F_BASE = 0x3a
SCANCODE_F1 = SCANCODE_F_BASE + 1
SCANCODE_F2 = SCANCODE_F_BASE + 2
SCANCODE_F3 = SCANCODE_F_BASE + 3
SCANCODE_F4 = SCANCODE_F_BASE + 4
SCANCODE_F5 = SCANCODE_F_BASE + 5
SCANCODE_F6 = SCANCODE_F_BASE + 6
SCANCODE_F7 = SCANCODE_F_BASE + 7
SCANCODE_F8 = SCANCODE_F_BASE + 8
SCANCODE_F9 = SCANCODE_F_BASE + 9
SCANCODE_F10 = SCANCODE_F_BASE + 10
SCANCODE_F11 = SCANCODE_F_BASE + 11
SCANCODE_F12 = SCANCODE_F_BASE + 12

STATE_POWEROFF = "poweroff"


class VBoxManage(object):
    def __init__(self, vboxmanage, vm_name):
        self.vboxmanage = vboxmanage
        self.vm_name = vm_name
        self.ascii_to_code_and_shift = None
        self.init_scan_codes_map()

    def get_info(self):
        """
        :rtype: list of (str, str)
        """
        vm_info_raw = subprocess.check_output([self.vboxmanage, "showvminfo", self.vm_name, "--machinereadable"])
        vm_info = read_vbox_pairs(vm_info_raw)
        return vm_info

    def insert_floppy_image(self, disk_device, image_filename):
        assert os.path.isfile(image_filename)
        storagectl_name, storage_port, storage_dev = disk_device.split("-")
        subprocess.check_call([self.vboxmanage, "storageattach", self.vm_name,
                               "--storagectl", storagectl_name, "--port", storage_port, "--device", storage_dev,
                               "--type", "fdd", "--medium", image_filename])

    def remove_floppy_image(self, disk_device):
        storagectl_name, storage_port, storage_dev = disk_device.split("-")
        subprocess.check_call([self.vboxmanage, "storageattach", self.vm_name,
                               "--storagectl", storagectl_name, "--port", storage_port, "--device", storage_dev,
                               "--type", "fdd", "--medium", "emptydrive"])

    def send_key_to_virtualbox(self, scan_code_value, sleep_time=0.1):
        """
        Simulate a press and release of the given key in a VirtualBox VM.

        :param vboxmanage: Path & filename of VBoxManage.exe
        :param vm_name: Name of the VirtualBox VM to interact with
        :param vboxmanage: str
        :type vm_name: str

        :param scan_code_value: Scan code of the key to press.
        This should be the key-down scan code (0 < code < 0x80)
        For details see:
        https://msdn.microsoft.com/en-us/library/aa299374(v=vs.60).aspx
        https://www.win.tue.nl/~aeb/linux/kbd/scancodes-1.html

        :type scan_code_value: int
        """
        assert isinstance(scan_code_value, int)
        assert 0 <= scan_code_value <= 0x80
        make_scancode = scan_code_value
        break_scancode = scan_code_value + 0x80
        self._send_scancodes([make_scancode, break_scancode])
        if sleep_time > 0:
            time.sleep(sleep_time)

    def _send_scancodes(self, scan_codes):
        """:type scancodes: list of int"""
        scan_code_params = ["%02x" % code for code in scan_codes]
        subprocess.check_call([self.vboxmanage, "controlvm", self.vm_name, "keyboardputscancode"] + scan_code_params)

    def get_screenshot(self):
        """:rtype: (Image.Image, str)"""
        screenshot_filename = tempfile.mktemp()
        subprocess.check_call([self.vboxmanage, "controlvm", self.vm_name, "screenshotpng", screenshot_filename])
        image = Image.open(screenshot_filename)
        return image, screenshot_filename

    def start(self):
        subprocess.check_call([self.vboxmanage, "startvm", self.vm_name])

    def reset(self):
        subprocess.check_call([self.vboxmanage, "controlvm", self.vm_name, "reset"])

    def init_scan_codes_map(self):
        ascii_to_code_and_shift = {}

        upper_codes = {0x02: "!@#$%^&*()_+"}

        uppers_map = {'[': '{',
                      ']': '}',
                      ';': ':',
                      '\\': '|',
                      ',': '<',
                      '.': '>',
                      '/': '?',
                      '\'': '"',
                      '`': '~',
                      }

        for s, start_code in [("qwertyuiop[]", 0x10),
                              ("asdfghjkl;'`", 0x1e),
                              ("\\", 0x2b),
                              ("zxcvbnm,./", 0x2c),
                              ("1234567890-=", 0x02),
                              ("\n", SCANCODE_ENTER),
                              (" ", SCANCODE_SPACE),
                              ]:
            code = start_code
            for i, ch in enumerate(s):
                ascii_to_code_and_shift[ch] = (code, False)
                if ch in uppers_map:
                    ch_upper = uppers_map[ch]
                elif start_code in upper_codes:
                    ch_upper = upper_codes[start_code][i]
                else:
                    ch_upper = ch.upper()
                if ch_upper != ch:
                    ascii_to_code_and_shift[ch_upper] = (code, True)

                code += 1
        self.ascii_to_code_and_shift = ascii_to_code_and_shift

    def scan_codes_for_text(self, s):
        m = self.ascii_to_code_and_shift
        out = []
        last_shift = False
        for ch in s:
            code, shift = m[ch]
            if shift != last_shift:
                if shift:
                    out.append(SCANCODE_SHIFT)
                else:
                    out.append(SCANCODE_SHIFT | 0x80)
                last_shift = shift
            out.append(code)
            out.append(code | 0x80)
        if last_shift:
            # leave the input unshifted
            out.append(SCANCODE_SHIFT | 0x80)
        return out

    def type_text(self, s):
        self._send_scancodes(self.scan_codes_for_text(s))
