# these commands are enabled via the tag below whenever a continuous window move/resize is running
tag: user.window_tweak_running
-

# WIP - could later add more commands here, e.g. 'pause', 'continue', 'cancel', 'faster', 'slower'
# WIP - 'cancel' would both stop and revert in one operation
# WIP - could add directional commands here to affect the window move/resize in mid flight.

win stop$:
    user.win_stop()