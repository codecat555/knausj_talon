from talon import Context, Module, actions, imgui, settings, ui, app
from talon.debug import log_exception
import os
import subprocess
import logging
import sys
import re

mod = Module()

ctx = Context()

wsl_distros = []

key_event = None
registry_key_handle = None

#distros_alternation = '|'.join(['ubuntu', 'debian'])
distros_alternation = 'Ubuntu'

def _close_key():
    print(f"_close_key(): {registry_key_handle}")
    if registry_key_handle:
        win32api.RegCloseKey(registry_key_handle)
#
def atexit():
    _close_key()

if app.platform == "windows":
    import win32api
    import win32event
    import win32con
    import atexit

def _initialize_key():
    global key_event, registry_key_handle

    try:
        if registry_key_handle:
            _close_key()
    
        #key_event = win32event.CreateEvent(win32event.SYNCHRONIZE, True, True, None)
        key_event = win32event.CreateEvent(None, True, True, None)
        #print(f"KEY_EVENT: {key_event}")

        registry_key_handle = win32api.RegOpenKeyEx(
            win32con.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Lxss", 0, win32con.KEY_READ | win32con.KEY_WOW64_64KEY)
        #print(f"registry_key_handle: {registry_key_handle}")

        #print(f"VERSION: {win32api.GetVersionEx()}")
        win32api.RegNotifyChangeKeyValue(
                registry_key_handle,
                True,
                win32api.REG_NOTIFY_CHANGE_LAST_SET,
                key_event,
                True
            )

        # trigger reading the list for the first time
        win32event.SetEvent(key_event)

#####
        result = win32event.WaitForSingleObjectEx(key_event, 0, False)
        #print(f'WAIT - {result=} (looking for {win32con.WAIT_OBJECT_0})')
        #print(f'WAIT - {win32con.WAIT_OBJECT_0=})')
        #print(f'WAIT - {win32con.WAIT_ABANDONED=})')
        #print(f'WAIT - {win32con.WAIT_TIMEOUT=})')
#####
    except WindowsError:
        # WIP - handle this
        raise

if False:
    mod.apps.ubuntu = """
    os: windows
    and app.name: ubuntu.exe
    """
elif False:
    # Note: these context matches are specific to ubuntu, but there are other
    # distros one can run under wsl, e.g. docker. for that matter, there are
    # multiple ubuntu distros available. we need a more general way of detecting
    # the current distro, and a way for the user to specify which distro to use
    # for any particular operation. perhaps implement a generic_wsl module and
    # then layer various distros on top of that?
    mod.apps.ubuntu = """
    os: windows
    and app.name: ubuntu.exe
    """

def context_matcher():
    update_wsl_distros()
    #distros_alternation = '|'.join(get_distros())
    distros_alternation = '|'.join(wsl_distros)
    return fr"""
    app: ubuntu
    app: windows_terminal
    and win.title: /@({distros_alternation}):/ 
    """

ctx.matches = fr"""
app: windows_terminal
and tag: user.wsl
tag: user.wsl
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

def get_win_path(wsl_path, distro=None):
    # for testing
    #wsl_path = 'Ubuntu-20.04'
    #wsl_path = '/mnt/qube/woobee/woobee/woobit'
    print(f"WINPATH: {wsl_path}")
    return run_wslpath(["-w"], wsl_path, distro)

def get_usr_path(distro=None):
    print(f'USRPATH: {"~"}')
    return run_wslpath(["-a"], "~", distro)

def get_wsl_path(win_path, distro=None):
    print(f"WSLPATH: {win_path}")
    return run_wslpath(["-u"], "'{}'".format(win_path), distro)

# this command fails every once in a while, with no indication why.
# so, when that happens we just retry.
MAX_ATTEMPTS = 2
def run_wslpath(args, in_path, in_distro=None):
    path = ""
    loop_num = 0

    while loop_num < MAX_ATTEMPTS:
        (distro, path, error) = run_wsl(['wslpath', *args, in_path], in_distro)
        if error:
            if in_path == distro and error.endswith('No such file or directory'):
                # for testing
                #print(f"run_wslpath(): - ignoring expected failure.")

                # this is expected. happens when running after the window is created
                # but before the default title has been changed. no need to spam the
                # console for this case, just let it pass.
                pass
            else:
                logging.error(f'run_wslpath(): failed to translate given path - attempt: {loop_num}, error: {error}')

            path = ""
        elif path:
            # got it, no need to loop and try again
            break

        loop_num += 1

    return path

# Note: seems WSL itself generates utf-16-le errors, whereas your guest os probably does not.
# - see https://github.com/microsoft/WSL/issues/4607 and related issures. Not sure how this
# behavior might differ when the system locale has been changed from the default.
#
# Anyways, these WSL errors require special handling so they are logged clearly. This is presumably
# worthwhile given the likely importance of any such messages. For example, which would you rather
# see in the log?
#
#   1. Nothing at all, even though there might be serious problems.
#
#   2. b'T\x00h\x00e\x00 \x00W\x00i\x00n\x00d\x00o\x00w\x00s\x00 \x00S\x00u\x00b\x00s\x00y\x00s\x00t\x00e\x00m\x00 \x00f\x00o\x00r\x00 \x00L\x00i\x00n\x00u\x00x\x00 \x00i\x00n\x00s\x00t\x00a\x00n\x00c\x00e\x00 \x00h\x00a\x00s\x00 \x00t\x00e\x00r\x00m\x00i\x00n\x00a\x00t\x00e\x00d\x00.\x00\r\x00\r\x00\n\x00'
#
#   3. The Windows Subsystem for Linux instance has terminated.
#
# The error above indicates the WSL distro is hung and this result detection mechanism is offline. When
# that happens, it takes a while for the command to return and the talon watchdog generates messages
# in the log that indicate a hang but we can provide more contextual detail. The prime thing to do here
# is to get word to the user that WSL is not responding normally. Note that, even after reaching this
# state, existing interactive wsl sessions continue to run and so the user may be unaware of the true
# source of their "talon problems". For more information, see https://github.com/microsoft/WSL/issues/5110
# and https://github.com/microsoft/WSL/issues/5318.
#
def _decode(value: bytes) -> str:
    if (len(value) % 2 == 0) and sum(value[1::2]) == 0:
        # looks like utf-16-le, see https://github.com/microsoft/WSL/issues/4607 (and related issues).
        decoded = value.decode('UTF-16-LE')
    else:
        decoded = value.decode()
    #print(f"_decode(): value is {value}")
    #print(f"_decode(): decoded is {decoded}.")
    return decoded.strip()

def _run_cmd(command_line):
    result = error = ""
    #print(f"_run_cmd(): RUNNING - command line is {command_line}.")
    try:
        # for testing
        #raise subprocess.CalledProcessError(-4294967295, command_line, 'The Windows Subsystem for Linux instance has terminated.'.encode('UTF-16-LE'))

        tmp = subprocess.check_output(command_line, stderr=subprocess.STDOUT)
        result = _decode(tmp)
        #print(f"RESULT: command: {' '.join(command_line)}, result: {result}")
    except subprocess.CalledProcessError as exc:
        result = ""

        # decode the error
        error = _decode(exc.output)

        # log additional info for this particular case
        if error == 'The Windows Subsystem for Linux instance has terminated.':
            logging.error(f'_run_cmd(): failed to run command - error: {error}')
            logging.error(f'_run_cmd(): - wsl path detection is offline')
            logging.error(f'_run_cmd(): - you need to restart your wsl session, e.g. "wsl --terminate <distro>; wsl"')
    except:
        result = ""
        log_exception(f'[_run_cmd()] {sys.exc_info()[1]}')

    # return results for the last attempt
    #print(f'_run_cmd(): RETURNING - result: {result}, error: {error}')
    return [result, error]

def run_wsl(args, distro=None):
    # for testing
    if False:
        wsl_cmd_str = "nosuchcommand"
    else:
        wsl_cmd_str = "wsl"

    # for testing
    #distro = "Debian"
    #distro = 'Ubuntu-20.04-ms-0'

    if not distro:
        # fetch the (default) distro first
        result = _run_cmd([wsl_cmd_str, "echo", "$WSL_DISTRO_NAME"])
        distro = result[0]
        if not distro:
            # if we can't fetch the distro, then the user's command is not likely to work
            # either. so, we just return any error information we have to the caller.
            #print(f'run_wsl(): RETURNING EARLY (no distro) - distro: {distro}, result: {result}')
            return [ None ] + result

    # now run the caller's command
    command_line = [ wsl_cmd_str, "--distribution", distro ] + args
    result = _run_cmd(command_line)
    #print(f'run_wsl(): RETURNING - distro: {distro}, result: {result}')
    return [ distro ] + result

def get_distro():
    #return run_wsl(["echo"])[0]
    return run_wsl(["\n"])[0]

def get_distros():
    distros = []

    (result, error) = _run_cmd(["wsl", "-l"])
    if error:
        logging.error(f'get_distros(): - command failed: {error}')
    else:
        #print(f'get_distros(): - result: {result}')
        # skip the first line
        lines = result.split('\n')[1:]
        for line in lines:
            name = line.split(' ')[0].rstrip()
            if line.endswith(' (Default)'):
                # the default distro is always first in the list
                distros.insert(0, name)
            else:
                distros.append(name)

    return distros

wsl_title_regex = re.compile(r'^.*@([^:]+):\s*(.*)$')

def update_wsl_distros():
    global ctx, registry_key_handle, wsl_distros

    if not registry_key_handle:
        _initialize_key()

    try:
        result = win32event.WaitForSingleObjectEx(key_event, 0, False)
#        print(f'WAIT - {result=}')
#        print(f'WAIT - {win32con.WAIT_OBJECT_0=})')
#        print(f'WAIT - {win32con.WAIT_ABANDONED=})')
#        print(f'WAIT - {win32con.WAIT_TIMEOUT=})')
        if result == win32con.WAIT_OBJECT_0:
            # registry has changed since we last read it, load the distros
            subkeys = win32api.RegEnumKeyEx(registry_key_handle)
            for index,subkey in enumerate(subkeys):
                #print(f'{index=}, {subkey=}')

                distro_handle = win32api.RegOpenKeyEx(
                    registry_key_handle, subkey[0], 0, win32con.KEY_READ | win32con.KEY_WOW64_64KEY)
                #print(f"{distro_handle=}")
                distro_name = win32api.RegQueryValueEx(distro_handle, 'DistributionName')[0]
                wsl_distros.append(distro_name)
                win32api.RegCloseKey(distro_handle)
                
                #print(f'{subkey=}, {distro_name=}')

            # reset the event, will be set by system if reg key changes
            win32event.ResetEvent(key_event)

            # update context match
            distros_alternation = '|'.join(wsl_distros)
#            ctx.matches = fr"""
#            app: ubuntu
#            app: windows_terminal
#            and win.title: /@({distros_alternation}):/ 
#            """
#            ctx.matches = (fr"""
#            app: ubuntu
#            app: windows_terminal
#            and win.title: /@({distros_alternation}):/ 
#            """)
        elif result != win32con.WAIT_TIMEOUT:
            raise Exception('howdy duty')
    except WindowsError:
        # WIP - handle this
        raise

    print(f'{wsl_distros=}')

@ctx.action_class('user')
class UserActions:
    def file_manager_refresh_title(): actions.skip()
    def file_manager_open_parent():
        actions.insert('cd ..')
        actions.key('enter')
# WIP - need to review file_manager_current_path() in apps/win/windows_terminal/windows_terminal.py,
# because it is called if context matching fails in this module and then the results are not right -
# the full window title was being returned by that module rather than just the path or nothing. that
# file assumes powershell (I think), which is not right imo - and how does this all fit in with the
# generic_terminal stuff?
    def file_manager_current_path():
        path = ui.active_window().title

        update_wsl_distros()

        distro = None
        try:
            (distro, path) = re.match(wsl_title_regex, path).groups()
            if distro not in wsl_distros:
                #logger.warning(f'Unknown wsl distro: {distro}')
                raise Exception(f'Unknown wsl distro: {distro}')
        except:
            try:
                # select line tail following the last colon in the window title
                path = path.split(":")[-1].lstrip()
            except:
                path = ""

        print(f'TITLE PARSE - distro is {distro}, path is {path}')

        if "~" in path:
            # the only way I could find to correctly support the user folder:
            # get absolute path of ~, and strip /mnt/x from the string
            abs_usr_path = get_usr_path(distro)
            abs_usr_path = abs_usr_path[abs_usr_path.find("/home") : len(abs_usr_path)]
            path = path.replace("~", abs_usr_path)

        path = get_win_path(path, distro)

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
