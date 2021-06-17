os: linux
tag: user.tmux
-
mux: "tmux "

#session management
mux new session:
    insert('tmux new ')
mux sessions:
    key(ctrl-o)
    key(s)
mux name session:
    key(ctrl-o)
    key($)
mux kill session:
    insert('tmux kill-session -t ')
#window management
mux new window:
    key(ctrl-o)
    key(c)
mux window <number>:
    key(ctrl-o )
    key('{number}')
mux previous window:
    key(ctrl-o)
    key(p)
mux next window:
    key(ctrl-o)
    key(n)
mux rename window:
    key(ctrl-o)
    key(,)
mux close window:
    key(ctrl-o)
    key(&)
#pane management
mux split horizontal:
    key(ctrl-o)
    key(%)
mux split vertical:
    key(ctrl-o)
    key(")
mux next pane:
    key(ctrl-o)
    key(o)
mux move <user.arrow_key>:
    key(ctrl-o)
    key(arrow_key)
mux close pane:
    key(ctrl-o)
    key(x)
#Say a number right after this command, to switch to pane
mux pane numbers:
    key(ctrl-o)
    key(q)
