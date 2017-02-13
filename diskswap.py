import argparse
import os
import subprocess
import sys


"""
A semi-automated script to feed numbered floppy disk images to VirtualBox.
"""


def parse_args():
    if sys.platform == "win32":
        program_files_path = os.environ.get("ProgramFilesW6432", r"C:\Program Files")
        default_vboxmanage = os.path.join(program_files_path, r"Oracle\VirtualBox\VBoxManage.exe")
    else:
        default_vboxmanage = "VBoxManage"

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
    return parser.parse_args()


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


def send_key_to_virtualbox(vboxmanage, vm_name, scan_code_value):
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
    make_scancode = deprefix(hex(scan_code_value), "0x")
    break_scancode = deprefix(hex(scan_code_value + 0x80), "0x")
    subprocess.check_call([vboxmanage, "controlvm", vm_name, "keyboardputscancode", make_scancode, break_scancode])


def main():
    options = parse_args()

    vm_name = options.vm_name
    disk_path = options.disk_path
    extension = options.extension
    vboxmanage = options.vboxmanage
    disk_device = options.disk_device
    keypress = options.keypress
    scancode = options.scancode

    if extension != "" and not extension.startswith("."):
        extension = "." + extension

    if vboxmanage != "VBoxManage":
        print "Using VBoxManage at %s" % vboxmanage

    # subprocess.check_call([vboxmanage, vm_name, "--help"])
    vm_info_raw = subprocess.check_output([vboxmanage, "showvminfo", vm_name, "--machinereadable"])
    vm_info = read_vbox_pairs(vm_info_raw)

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

    while pos < len(numbered_disks):
        storagectl_name, storage_port, storage_dev = disk_device.split("-")

        prefix, num, filename_proper = numbered_disks[pos]
        print "Press Enter to switch to %s" % filename_proper
        sys.stdin.readline()

        subprocess.check_call([vboxmanage, "storageattach", vm_name,
                               "--storagectl", storagectl_name, "--port", storage_port, "--device", storage_dev,
                               "--type", "fdd", "--medium", os.path.join(disk_path, filename_proper)])

        if keypress:
            send_key_to_virtualbox(vboxmanage, vm_name, scancode)

        pos += 1


if __name__ == "__main__":
    main()
