import time
from talon import Context, Module, actions, clip, ui, ctrl

ctx = Context()
mod = Module()


@ctx.action_class("edit")
class edit_actions:
    def selected_text() -> str:
        with clip.capture() as s:
            actions.edit.copy()
        try:
            return s.get()
        except clip.NoChange:
            return ""


@mod.action_class
class Actions:
    def paste(text: str):
        """Pastes text and preserves clipboard"""

        with clip.revert():
            clip.set_text(text)
            actions.edit.paste()
            # sleep here so that clip.revert doesn't revert the clipboard too soon
            actions.sleep("150ms")

    def words_left(n: int):
        """Moves left by n words."""
        for _ in range(n):
            actions.edit.word_left()

    def words_right(n: int):
        """Moves right by n words."""
        for _ in range(n):
            actions.edit.word_right()

    def go_top():
        """Goes to top of page even wihle scrolling"""
        print(f"GO TOP - START - mouse pos: {ctrl.mouse_pos()}")
        actions.user.mouse_scroll_pause()
        print(f"GO TOP - PAUSED - mouse pos: {ctrl.mouse_pos()}")
        actions.edit.file_start()
        print(f"GO TOP - NEW - mouse pos: {ctrl.mouse_pos()}")
        actions.user.mouse_scroll_resume()
        print(f"GO TOP - RESUMED - mouse pos: {ctrl.mouse_pos()}")

    def go_bottom():
        """Goes to bottom of page even wihle scrolling"""
        actions.user.mouse_scroll_pause()
        actions.edit.file_end()
        actions.user.mouse_scroll_resume()


