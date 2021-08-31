from talon import Context, Module, actions, imgui, settings, ui, app
import os
import subprocess
import logging

mod = Module()
mod.apps.ubuntu = """
os: windows
and app.name: ubuntu.exe
"""

ctx = Context()
ctx.matches = r"""
app: ubuntu
app: windows_terminal
and win.title: /Ubuntu/ 
"""
directories_to_remap = {}
directories_to_exclude = {}

user_path = os.path.expanduser("~")
if app.platform == "windows":
    is_windows = True
    import ctypes

    GetUserNameEx = ctypes.windll.secur32.GetUserNameExW
    NameDisplay = 3

    size = ctypes.pointer(ctypes.c_ulong(0))
    GetUserNameEx(NameDisplay, None, size)

    nameBuffer = ctypes.create_unicode_buffer(size.contents.value)
    GetUserNameEx(NameDisplay, nameBuffer, size)
    one_drive_path = os.path.expanduser(os.path.join("~", "OneDrive"))

    # this is probably not the correct way to check for onedrive, quick and dirty
    if os.path.isdir(os.path.expanduser(os.path.join("~", r"OneDrive\Desktop"))):
        default_folder = os.path.join("~", "Desktop")

        directories_to_remap = {
            "Desktop": os.path.join(one_drive_path, "Desktop"),
            "Documents": os.path.join(one_drive_path, "Documents"),
            "Downloads": os.path.join(user_path, "Downloads"),
            "Music": os.path.join(user_path, "Music"),
            "OneDrive": one_drive_path,
            "Pictures": os.path.join(one_drive_path, "Pictures"),
            "Videos": os.path.join(user_path, "Videos"),
        }
    else:
        # todo use expanduser for cross platform support
        directories_to_remap = {
            "Desktop": os.path.join(user_path, "Desktop"),
            "Documents": os.path.join(user_path, "Documents"),
            "Downloads": os.path.join(user_path, "Downloads"),
            "Music": os.path.join(user_path, "Music"),
            "OneDrive": one_drive_path,
            "Pictures": os.path.join(user_path, "Pictures"),
            "Videos": os.path.join(user_path, "Videos"),
        }


def get_win_path(wsl_path):
    # for testing
    #wsl_path = 'Ubuntu-20.04'
    #wsl_path = '/mnt/qube/woobee/woobee/woobit'
    return _run_wslpath(["-w"], wsl_path)

def get_usr_path():
    return _run_wslpath(["-a"], "~")

def get_wsl_path(win_path):
    return _run_wslpath(["-u"], "'{}'".format(win_path))

MAX_ATTEMPTS = 2
def _run_wslpath(args, in_path):
    command_line = [ "wsl", "wslpath" ] + args + [in_path]

    path = ""
    loop_num = 0
    # this command fails every once in a while, with no indication why. so,
    # when that happens we just retry.
    while loop_num < MAX_ATTEMPTS:
        try:
            path = (
                subprocess.check_output(command_line, stderr=subprocess.STDOUT)
                .strip(b"\n")
                .decode()
            )
        except Exception as exc:
            path = ""

            # check known corner cases
            distro = get_distro()
            if in_path == distro:
                # this is expected. happens when running after the window is created but before the title has been set.
                # no need to spam the console for this case or retry.
                #print(f"_run_wslpath(): attempt {loop_num} - ignoring expected failure.")
                break
            else:
                # decode the error
                #
                # Note: seems WSL itself generates utf-16 errors, whereas your guest os probably does not.
                # - see https://github.com/microsoft/WSL/issues/4607 and related issures.
                #
                # The WSL errors require special handling, adding work to every non-WSL decoding even though
                # they are comparatively rare (one hopes). The extra cost, I think, is justified given the
                # likely importance of any such messages. For example, which would you rather see in the log?
                #
                #   1. Nothing at all - this is what earlier code did (masked the errors)
                #
                #   2. b'T\x00h\x00e\x00 \x00W\x00i\x00n\x00d\x00o\x00w\x00s\x00 \x00S\x00u\x00b\x00s\x00y\x00s\x00t\x00e\x00m\x00 \x00f\x00o\x00r\x00 \x00L\x00i\x00n\x00u\x00x\x00 \x00i\x00n\x00s\x00t\x00a\x00n\x00c\x00e\x00 \x00h\x00a\x00s\x00 \x00t\x00e\x00r\x00m\x00i\x00n\x00a\x00t\x00e\x00d\x00.\x00\r\x00\r\x00\n\x00'
                #
                #   3. The Windows Subsystem for Linux instance has terminated.
                #
                # The error above indicates the WSL distro is hung and this path detection mechanism is offline. When
                # that happens, it takes a while for the command to return and the talon watchdog generates messages
                # in the log that seem ominous but don't explain what the problem really is. The prime thing to do here
                # is to get word to the user that WSL is not responding normally. Note that, even after reaching this
                # state, existing interactive wsl sessions continue to run and so the user may be unaware of the true
                # source of their "talon problems".
                #
                # For the fallback mechanism - that code which runs if utf-16 decoding fails - it may be better to
                # discover the guest os locale for use in decoding - dunno. For now, we preserve the legacy behavior
                # of this code and use the default decoding.
                try:
                    # try windows/wsl encoding first
                    error = exc.output.decode('UTF-16-LE').strip()
                    # tag the error with the actual source
                    error_source = 'WSL'
                except UnicodeDecodeError as decode_exc:
                    # fallback to default encoding
                    error = exc.output.decode().strip()
                    error_source = f'{distro}'

                # error injection, for testing
                if False:
                    error = 'The Windows Subsystem for Linux instance has terminated.'
                    error_source = 'WSL'

                logging.warning(f'_run_wslpath(): failed to translate current path - attempt {loop_num}, source: {error_source}, error: {error}')

                # log an additional warning line for this particular case
                if error == 'The Windows Subsystem for Linux instance has terminated.':
                    logging.warning(f'_run_wslpath(): attempt {loop_num} - seems you need to restart your wsl session, e.g. "wsl --terminate {distro}; wsl"')
        else:
            # no need to loop and try again
            break

        loop_num += 1

    # for testing
    #print(f"_run_wslpath(): in path: '{in_path}', translated path: '{path}'")

    return path

def get_distro():
    distro = None
    try:
        distro = (
            subprocess.check_output(["wsl", "echo", "$WSL_DISTRO_NAME"], stderr=subprocess.STDOUT)
            .strip(b"\n")
            .decode()
        )
    except Exception as exc:
        logging.warning(f"git_distro(): failed to retrieve distro name - {exc.output.decode()}")

    return distro

@ctx.action_class('user')
class UserActions:
    def file_manager_refresh_title(): actions.skip()
    def file_manager_open_parent():
        actions.insert('cd ..')
        actions.key('enter')
    def file_manager_current_path():
        path = ui.active_window().title
        try:
            # select line tail following the last colon in the window title
            path = path.split(":")[-1].lstrip()
        except:
            path = ""

        if "~" in path:
            # the only way I could find to correctly support the user folder:
            # get absolute path of ~, and strip /mnt/x from the string
            abs_usr_path = get_usr_path()
            abs_usr_path = abs_usr_path[abs_usr_path.find("/home") : len(abs_usr_path)]
            path = path.replace("~", abs_usr_path)

        path = get_win_path(path)

        if path in directories_to_remap:
            path = directories_to_remap[path]

        if path in directories_to_exclude:
            path = ""

        return path

    # def file_manager_terminal_here():
    #     actions.key("ctrl-l")
    #     actions.insert("cmd.exe")
    #     actions.key("enter")

    # def file_manager_show_properties():
    #     """Shows the properties for the file"""
    #     actions.key("alt-enter")
    def file_manager_open_user_directory(path: str):
        """expands and opens the user directory"""
        if path in directories_to_remap:
            path = directories_to_remap[path]

        path = os.path.expanduser(os.path.join("~", path))
        if ":" in path:
            path = get_wsl_path(path)

        actions.user.file_manager_open_directory(path)

    def file_manager_open_directory(path: str):
        """opens the directory that's already visible in the view"""
        if ":" in str(path):
            path = get_wsl_path(path)

        actions.insert('cd "{}"'.format(path))
        actions.key("enter")
        actions.user.file_manager_refresh_title()

    def file_manager_select_directory(path: str):
        """selects the directory"""
        actions.insert('"{}"'.format(path))

    def file_manager_new_folder(name: str):
        """Creates a new folder in a gui filemanager or inserts the command to do so for terminals"""
        actions.insert('mkdir "{}"'.format(name))

    def file_manager_open_file(path: str):
        actions.insert(path)
        # actions.key("enter")

    def file_manager_select_file(path: str):
        actions.insert(path)

    def file_manager_open_volume(volume: str):
        actions.user.file_manager_open_directory(volume)

    def terminal_list_directories():
        actions.insert("ls")
        actions.key("enter")

    def terminal_list_all_directories():
        actions.insert("ls -a")
        actions.key("enter")

    def terminal_change_directory(path: str):
        actions.insert("cd {}".format(path))
        if path:
            actions.key("enter")

    def terminal_change_directory_root():
        """Root of current drive"""
        actions.insert("cd /")
        actions.key("enter")

    def terminal_clear_screen():
        """Clear screen"""
        actions.key("ctrl-l")

    def terminal_run_last():
        actions.key("up enter")

    def terminal_kill_all():
        actions.key("ctrl-c")
        actions.insert("y")
        actions.key("enter")
