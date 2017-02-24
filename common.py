import os
import sys


def get_default_vboxmanage():
    if sys.platform == "win32":
        program_files_path = os.environ.get("ProgramFilesW6432", r"C:\Program Files")
        default_vboxmanage = os.path.join(program_files_path, r"Oracle\VirtualBox\VBoxManage.exe")
    else:
        default_vboxmanage = "VBoxManage"
    return default_vboxmanage
