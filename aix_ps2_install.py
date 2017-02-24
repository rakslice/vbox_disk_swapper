import argparse
import os
import shutil

import time
import stat
import datetime

import vmm
from common import get_default_vboxmanage
from textreader import TextReader
from vmm import VBoxManage

script_path = os.path.dirname(os.path.abspath(__file__))


INSTALL_DRIVE = "Floppy-0-0"

SHOW_LINES = True


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("vm_name",
                        help="Name of the VirtualBox virtual machine to work with")
    parser.add_argument("--vboxmanage",
                        help="path to VBoxManage.exe",
                        default=get_default_vboxmanage())
    parser.add_argument("--disk-images",
                        help="path to disk images",
                        required=True,
                        )
    return parser.parse_args()


def expect_messages(tr, vm, messages, interval_s=2, retry_on_error=False):
    """
    :type tr: TextReader
    :type messages: list of str
    :type interval_s: float or int
    """
    while True:
        while True:
            try:
                lines = tr.read(vm)
            except AssertionError:
                if not retry_on_error:
                    raise
                time.sleep(2)
                continue
            break

        for line in lines:
            if SHOW_LINES:
                print line
            for message in messages:
                if message in line:
                    return message

        print "Waiting for %r" % messages
        time.sleep(interval_s)


def utc_offset_hours():
    dt = datetime.datetime.now() - datetime.datetime.utcnow()
    return dt.days * 24 + dt.seconds / 60 / 60


def main():
    hostname = "aixps2"

    options = parse_args()

    vm = VBoxManage(options.vboxmanage, options.vm_name)
    tr_vbox_textmode = TextReader(ch_width=9, ch_height=16, ch_map_filename=os.path.join(script_path, "ch_map_9x16.json"),
                                  init_image="vga9x16.png", init_line_offset=0, init_left_shift_pixels=0, init_invert=False)

    tr_vga_textmode = TextReader(ch_width=8, ch_height=12, ch_map_filename=os.path.join(script_path, "ch_map.json"),
                                 init_line_height=16, init_line_offset=1, init_left_shift_pixels=1,
                                 init_image="pgcfont.png", init_invert=True, normal_line_height=14)

    def get_floppy(relative_path, check_exists=True):
        out = os.path.join(options.disk_images, relative_path)
        if check_exists:
            if not os.path.isfile(out):
                assert os.path.isfile(out), "File not found: %r" % out
        return out

    def get_floppies(form, count):
        return [get_floppy(form % (i + 1)) for i in range(count)]

    resume = False
    resume = True

    disk_boot_1 = get_floppy("boot_scsi/Boot_Disk1_0024.vfd")
    disk_boot_2 = get_floppy("boot_scsi/Boot_Disk2_0024.vfd")
    disk_install_original = get_floppy("install/Install0024.img.vfd")
    disk_install_working = get_floppy("install/Install0024_working_copy.img.vfd", check_exists=False)
    disk_base_os_form = "BaseOperatingSystem/BaseOperatingSystem_%d.img"
    disk_base_os_count = 15
    disk_base_os_list = get_floppies(disk_base_os_form, disk_base_os_count)

    disk_ide_update_form = "rootstuff/PTF0024/U436295Disk%d.img"
    disk_ide_update_count = 3
    disk_ide_update_list = get_floppies(disk_ide_update_form, disk_ide_update_count)

    if not resume:
        if os.path.exists(disk_install_working):
            os.chmod(disk_install_working, stat.S_IWRITE)
            os.remove(disk_install_working)
            shutil.copy(disk_install_original, disk_install_working)
            os.chmod(disk_install_working, stat.S_IWRITE)

        status = dict(vm.get_info())
        assert status["VMState"] == vmm.STATE_POWEROFF

        vm.insert_floppy_image(INSTALL_DRIVE, disk_boot_1)

        vm.start()
        time.sleep(2)

    PARAMS_PROMPT = "AIX PS/2 requires that a few system configuration parameters"

    if resume:
        last = PARAMS_PROMPT
    else:
        last = expect_messages(tr_vbox_textmode, vm, [PARAMS_PROMPT, "Boot from Hard Disk"], retry_on_error=True)

    cur_tr = tr_vbox_textmode

    def accept_default(prompt):
        expect_messages(cur_tr, vm, [prompt])
        vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

    def swap_disk_after(prompt, next_disk, interval_s=2):
        expect_messages(cur_tr, vm, [prompt], interval_s=interval_s)

        vm.insert_floppy_image(INSTALL_DRIVE, next_disk)
        vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

    def choose_bullet_space_menu_item(item, cursor="o", cursor_pos=None, item_prefix=" ", item_suffix=" "):
        item_start = item_prefix + item + item_suffix
        prev_lines = None
        while True:
            lines = cur_tr.read(vm)
            if lines == prev_lines:
                print "retrying"
                time.sleep(0.5)
                continue
            prev_lines = lines
            for line in lines:
                if item_start in line:
                    if cursor_pos is not None:
                        selected = line[cursor_pos] == cursor
                    else:
                        pos = line.index(item_start)
                        prefix = line[:pos]
                        selected = cursor in prefix
                        if selected:
                            print "opt: cursor pos for %r is %d" % (item_start, prefix.index(cursor))
                    if selected:
                        vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)
                        return
                    vm.send_key_to_virtualbox(vmm.SCANCODE_SPACE)
                    break
            else:
                # not on screen yet
                print "waiting for %r" % item_start
                time.sleep(0.5)
                prev_lines = None

    if last == PARAMS_PROMPT:
        if not resume:
            vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

            expect_messages(tr_vbox_textmode, vm, ["SELECT KEYBOARD LANGUAGE"])

            vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

            expect_messages(tr_vbox_textmode, vm, ["SELECT MONITOR TYPE"])

            vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

            expect_messages(tr_vbox_textmode, vm, ["SELECT TIME ZONE"])

            default_utc_offset = -5
            moves = utc_offset_hours() - default_utc_offset

            if moves < 0:
                moves = -moves
                key = vmm.SCANCODE_DOWN
            else:
                key = vmm.SCANCODE_UP

            for i in range(moves):
                vm.send_key_to_virtualbox(key)

            vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

            expect_messages(tr_vbox_textmode, vm, ["Do you observe daylight savings time?"])

            vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

            expect_messages(tr_vbox_textmode, vm, ["Standard Timezone name"])

            vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

            expect_messages(tr_vbox_textmode, vm, ["Daylight Savings Timezone name"])

            vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

            expect_messages(tr_vbox_textmode, vm, ["SELECT NLS TRANSLATION LANGUAGE"])

            vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

            expect_messages(tr_vbox_textmode, vm, ["SELECT MACHINE NAME"])

            vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

    if not resume:
        expect_messages(tr_vbox_textmode, vm, ["IBM AIX PS/2 Bootstrap"])

        # floppy boot
        vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

        accept_default("Module to be loaded")

        accept_default("System mode")

        # floppy root
        accept_default("Run system from hard disk")

        swap_disk_after("Please insert BOOT  diskette number 2; Press any key when ready", disk_boot_2)

        swap_disk_after("Insert installation diskette and press Enter", disk_install_working)

    cur_tr = tr_vga_textmode

    if not resume:

        expect_messages(tr_vga_textmode, vm, ["SYSTEM INSTALLATION"], retry_on_error=True)
        choose_bullet_space_menu_item("Install and Customize AIX")

        BAD_SECTORS_PROMPT = "Would you like to add any other bad sectors"
        last = expect_messages(cur_tr, vm, [BAD_SECTORS_PROMPT, "Select a method of installation"])

        if last == BAD_SECTORS_PROMPT:
            vm.send_key_to_virtualbox(vmm.SCANCODE_N)
            vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

            accept_default("Press ANY KEY to continue.")

        choose_bullet_space_menu_item("Install a NEW AIX System.")

        expect_messages(cur_tr, vm, ["Do you wish to proceed (y/n)?"])

        vm.send_key_to_virtualbox(vmm.SCANCODE_Y)
        vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

        expect_messages(cur_tr, vm, ["INSTALL AND CUSTOMIZE AIX"])

        choose_bullet_space_menu_item("Change Current Choices and Install", cursor_pos=20)

        expect_messages(cur_tr, vm, ["CHANGE CURRENT CHOICES AND INSTALL"])

        sizes = {
            "/u": 150000,
            "/": 150000,
            "page": 65536,
            "/%s" % hostname: 65536,
            "/%s/tmp" % hostname: 50000,
            "dump": 32768,
                 }

        no_files = ["page", "dump"]

        order = ["/u", "/%s" % hostname, "/", "page", "dump", "/%s/tmp" % hostname]

        for entry in order:
            expect_messages(cur_tr, vm, ['Install the Operating system and cause the'])

            choose_bullet_space_menu_item(entry, cursor_pos=20)
            # vm.send_key_to_virtualbox(vmm.SCANCODE_SPACE)

            size = sizes.get(entry)

            # vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

            entry_prompt = entry
            if entry == "/":
                entry_prompt = "/ (root)"

            expect_messages(cur_tr, vm, ['Change the number of blocks for the "%s" minidisk.' % entry_prompt])

            # key in size or accept default
            if size is not None:
                enter_int(vm, size)
            vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

            if entry not in no_files:
                expect_messages(cur_tr, vm, ['Change the maximum number of files for the "%s" minidisk.' % entry_prompt])

                # accept file count
                vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

        choose_bullet_space_menu_item('Install the Operating system and cause the', cursor_pos=20)

        accept_default("To INSTALL AIX, press Enter.")

        expect_messages(cur_tr, vm, ['INSTALLATION OF THE MINI SYSTEM IS COMPLETE'], interval_s=10)

        expect_messages(cur_tr, vm, ['System halted, you may turn the power off now.'])

        # BOOT 1 is complete.

        vm.insert_floppy_image(INSTALL_DRIVE, disk_boot_1)

        vm.reset()
        time.sleep(3)

        cur_tr = tr_vbox_textmode

    def floppy_bootstrap(root_from_floppy):

        expect_messages(tr_vbox_textmode, vm, ["IBM AIX PS/2 Bootstrap"], retry_on_error=True)

        # floppy boot
        vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

        accept_default("Module to be loaded")

        accept_default("System mode")

        # floppy root
        # accept_default("Run system from hard disk")
        expect_messages(tr_vbox_textmode, vm, ["Run system from hard disk"])
        if not root_from_floppy:
            vm.send_key_to_virtualbox(vmm.SCANCODE_SPACE)
        vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

        swap_disk_after("Please insert BOOT  diskette number 2; Press any key when ready", disk_boot_2)

        # swap_disk_after("Insert installation diskette and press Enter", disk_install_working)
        #

    if not resume:
        floppy_bootstrap(root_from_floppy=False)

    cur_tr = tr_vga_textmode

    expect_messages(cur_tr, vm, ["CONTINUE INSTALLATION"], interval_s=5, retry_on_error=True)

    choose_bullet_space_menu_item("Diskette Drive 0", cursor_pos=20)

    for i in range(disk_base_os_count):
        cur_disk = disk_base_os_list[i]
        swap_disk_after("Please mount volume %d on /dev/fd0" % (i + 1), cur_disk, interval_s=5)

    accept_default("Press Enter to refresh the screen")

    accept_default("To CONTINUE with post installation processing, press Enter.")

    expect_messages(cur_tr, vm, ["CONSOLE LOGIN MODE"])
    choose_bullet_space_menu_item("Normal console login.")

    expect_messages(cur_tr, vm, ["INSTALL PROGRAM PRODUCTS"])
    choose_bullet_space_menu_item("Continue Installation.")

    accept_default("To RETURN to the SYSTEM INSTALLATION menu, press Enter.")

    expect_messages(cur_tr, vm, ["SYSTEM INSTALLATION"])
    choose_bullet_space_menu_item("End Installation")

    expect_messages(cur_tr, vm, ["END INSTALLATION"])
    expect_messages(cur_tr, vm, ["System halted, you may turn the power off now."])

    # BOOT 2 is done.

    # We need to boot off of disk again to apply the patches

    vm.insert_floppy_image(INSTALL_DRIVE, disk_boot_1)

    vm.reset()
    cur_tr = tr_vbox_textmode
    time.sleep(3)

    floppy_bootstrap(root_from_floppy=False)

    cur_tr = tr_vga_textmode

    expect_messages(cur_tr, vm, ["INIT: SINGLE USER MODE"], retry_on_error=True)
    expect_messages(cur_tr, vm, ["Do you want to enter system maintenance (single user) mode ? <n>"])

    vm.send_key_to_virtualbox(vmm.SCANCODE_Y)
    vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

    accept_default("Give root password for maintenance")

    expect_messages(cur_tr, vm,  ["<%s <1>>#" % hostname])
    vm.type_text("updatep -ac\n")

    expect_messages(cur_tr, vm, ["Do you want to continue with this command?  (y or n)"])
    vm.type_text("y\n")

    swap_disk_after("Please mount volume %d on /dev/rfd0" % 1, disk_ide_update_list[0])


    expect_messages(cur_tr, vm, ["5 Apply All of the"])

    expect_messages(cur_tr, vm, ["Type the ID numbers of the programs you wish to commit"])

    vm.type_text("5\n")

    # cur_tr = tr_vga_textmode

    accept_default("response will display the listed files")

    while True:
        out = expect_messages(cur_tr, vm, ["--More--", "Press the enter key to continue or enter 'quit' to exit updatep"])
        if out == "--More--":
            vm.send_key_to_virtualbox(vmm.SCANCODE_SPACE)
            continue
        break

    vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

    for i in [2, 3]:
        swap_disk_after("Please mount volume %d on /dev/rfd0" % i, disk_ide_update_list[i - 1])

    expect_messages(cur_tr, vm, ["qproc complete"])
    expect_messages(cur_tr, vm, ["<%s <1>>#" % hostname])

    vm.type_text("exit\n")

    expect_messages(cur_tr, vm, ["INIT: SINGLE USER MODE"])
    expect_messages(cur_tr, vm, ["Do you want to enter system maintenance (single user) mode ? <n>"])
    vm.type_text("n\n")

    expect_messages(cur_tr, vm, ["The kernel has been rebuilt.  Please press RETURN to reboot."], interval_s=6)


    # BOOT 3 is done.   We now have a working system; let's boot from the HD and install some software.

    vm.remove_floppy_image(INSTALL_DRIVE)
    # FIX: virtualbox reboot here causes disk corruption on the next fsck.

    # Should we also pause?
    # time.sleep(10)
    # vm.reset()
    vm.send_key_to_virtualbox(vmm.SCANCODE_ENTER)

    expect_messages(cur_tr, vm, ["IBM AIX PS/2 Operating System"], interval_s=6, retry_on_error=True)
    expect_messages(cur_tr, vm, ["Console login:"])
    vm.type_text("root\n")

    def install_disk_set(folder, count, file_base=None, ext=".img", autonumber=None):
        if autonumber is None:
            if count == 1:
                autonumber = False
            else:
                autonumber = True
        if file_base is None:
            file_base = folder
        if autonumber:
            disk_form = "%s/%s_%%d%s" % (folder, file_base, ext)
            disks = get_floppies(disk_form, count)
        else:
            assert count == 1
            disk_form = "%s/%s%s" % (folder, file_base, ext)
            disks = [get_floppy(disk_form)]

        expect_messages(cur_tr, vm, ["%s #" % hostname])
        vm.type_text("installp\n")
        expect_messages(cur_tr, vm, ["Do you want to continue with this command?  (y or n)"])
        vm.type_text("y\n")
        for i in range(count):
            cur_disk = disks[i]
            swap_disk_after("Please mount volume %d on /dev/rfd0" % (i + 1), cur_disk, interval_s=5)

            if i == 0:
                expect_messages(cur_tr, vm, ["will be installed."])
                expect_messages(cur_tr, vm, ["Do you want to do this? (y/n)"])
                vm.type_text("y\n")

    if not resume:
        pass
    install_disk_set("AdvancedDevelopmentTools", 5, "ADT")
    install_disk_set("AdvancedDevelopmentTools", 1, "ADT_6", autonumber=False)

    install_disk_set("TCPIP", 2)
    expect_messages(cur_tr, vm, ["Enter Internet address for %s:" % hostname])
    vm.type_text("192.168.2.22\n")
    expect_messages(cur_tr, vm, ["qproc complete"])

    install_disk_set("AdministrativeSupport", 1)

    install_disk_set("AsynchTerminalEmulator", 1, "ATE")
    install_disk_set("BasicNetworkUtilities", 1, "BNU")
    install_disk_set("CD-ROM", 1, "CD-ROM_Support")
    install_disk_set("EnglishLanguageSupport", 1)
    install_disk_set("ExtendedUserSupport", 1)
    install_disk_set("Games", 1)
    install_disk_set("GraphicSupportLibrary", 2, "GraphicSupLib")

    install_disk_set("INed", 2)
    install_disk_set("INMN386", 1)
    install_disk_set("LearnToUseAIX-PS2", 1)

    install_disk_set("ManualPages", 5)
    install_disk_set("MessageHandler", 3)

    install_disk_set("MetawareC_Compiler", 1, "C-Compiler")

    install_disk_set("TextFormattingSystem", 1, "TFS")

    time.sleep(5)
    for line in cur_tr.read(vm):
        print line


def enter_int(vm, n):
    s = str(n)
    for digit in s:
        if digit == "0":
            code = 0x0b
        else:
            code = 0x01 + int(digit)
        vm.send_key_to_virtualbox(code)


def wait_for_running(vm):
    while True:
        status = dict(vm.get_info())
        print status["VMState"]
        time.sleep(2)


if __name__ == "__main__":
    main()