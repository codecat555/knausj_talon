app: ubuntu
app: windows_terminal
and win.title: /Ubuntu/
-
tag(): user.file_manager
tag(): terminal
tag(): user.git
tag(): user.kubectl
tag(): terminal
^go <user.letter>$: user.file_manager_open_volume("/mnt/{letter}")
