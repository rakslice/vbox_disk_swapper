import argparse
import os
import sys

import time

from common import get_default_vboxmanage
from textreader import TextReader
from vmm import VBoxManage

"""
A semi-automated script to feed numbered floppy disk images to VirtualBox.
"""


def parse_args():
    default_vboxmanage = get_default_vboxmanage()

    parser = argparse.ArgumentParser()
    parser.add_argument("vm_name",
                        help="Name of the VirtualBox VM to swap disks on")
    parser.add_argument("--disk-path",
                        help="A path to look for disk image files in",
                        )
    parser.add_argument("--extension", "-e",
                        help="Extension to expect on disk files",
                        default=".img")
    parser.add_argument("--vboxmanage",
                        help="VBoxManage program to use",
                        default=default_vboxmanage)
    parser.add_argument("--no-keypress",
                        help="Don't press a key in the VM after switching disk images",
                        default=True,
                        action="store_false",
                        dest="keypress",
                        )
    parser.add_argument("--scancode",
                        help="Key-down scancode (0 < code < 0x80) for the key to press in the VM after switching disks (default: Enter)",
                        type=int,
                        default=0x1c,
                        )
    parser.add_argument("--disk",
                        help="disk device to swap",
                        default="Floppy-0-0",
                        dest="disk_device")
    parser.add_argument("--ocr",
                        help="OCR for restore next volume prompt",
                        default=False,
                        action="store_true")
    return parser.parse_args()


def pairs_get(pairs, key):
    """
    Lookup the value with the given key in a list of pairs
    :type pairs: list of (str, ?)
    :param key: str
    :return: str or None
    """
    for cur_key, cur_value in pairs:
        if key == cur_key:
            return cur_value
    return None


def get_numbered_disks(disk_path, extension):
    """
    Get a sorted list of numbered disk image files in the given directory.
    :param disk_path: directory to search
    :param extension: extension to look for, with leading dot (or empty string to find files without extension)
    :return: A list of disk image tuples (filename prefix, num, filename_proper), sorted by filename prefix and then by number
    :rtype: list of (str, int, str)
    """
    disks = []
    for filename_proper in os.listdir(disk_path):
        filename_prefix = filename_proper
        if not filename_prefix.lower().endswith(extension.lower()):
            continue
        if extension != "":
            filename_prefix = filename_prefix.rsplit(".", 1)[0]

        digits = []
        while len(filename_prefix) > 0:
            last_ch = filename_prefix[-1]
            if last_ch.isdigit():
                digits.insert(0, last_ch)
                filename_prefix = filename_prefix[:-1]
            else:
                break
        if len(digits) == 0:
            continue
        trailing_num = int("".join(digits))
        disks.append((filename_prefix, trailing_num, filename_proper))
    disks.sort()
    return disks


def main():
    options = parse_args()

    vm_name = options.vm_name
    disk_path = options.disk_path
    extension = options.extension
    vboxmanage = options.vboxmanage
    disk_device = options.disk_device
    keypress = options.keypress
    scancode = options.scancode
    ocr = options.ocr

    if extension != "" and not extension.startswith("."):
        extension = "." + extension

    if vboxmanage != "VBoxManage":
        print "Using VBoxManage at %s" % vboxmanage

    vm = VBoxManage(vboxmanage, vm_name)

    # subprocess.check_call([vboxmanage, vm_name, "--help"])
    vm_info = vm.get_info()

    current_disk_image = pairs_get(vm_info, disk_device)
    print "Current disk image: %s" % current_disk_image

    if disk_path is None:
        disk_path = os.path.dirname(current_disk_image)
    assert os.path.isdir(disk_path)

    numbered_disks = get_numbered_disks(disk_path, extension)
    numbered_disk_filenames = [os.path.join(disk_path, e[2]) for e in numbered_disks]

    try:
        pos = numbered_disk_filenames.index(current_disk_image)
    except ValueError:
        pos = -1
    pos += 1

    if ocr:
        tr = TextReader()
    else:
        tr = None

    while pos < len(numbered_disks):

        prefix, num, filename_proper = numbered_disks[pos]

        if ocr:
            print "Watching for prompt for volume %d: %s" % (num, filename_proper)
            while True:
                lines = tr.read(vm)
                if lines[-1].startswith("...and press Enter to continue") and \
                    lines[-2].startswith("Please mount volume %d on /dev/" % num):
                    break
                else:
                    time.sleep(2)
        else:
            print "Press Enter to switch to %s" % filename_proper
            sys.stdin.readline()

        vm.insert_floppy_image(disk_device, os.path.join(disk_path, filename_proper))

        if keypress:
            vm.send_key_to_virtualbox(scancode)

        pos += 1


if __name__ == "__main__":
    main()
