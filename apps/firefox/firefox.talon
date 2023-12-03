app: firefox
-
tag(): browser
tag(): user.tabs

tab search:
  browser.focus_address()
  sleep(10ms)
  insert("% ")
tab search <user.text>$:
  browser.focus_address()
  sleep(10ms)
  insert("% {text}")
  sleep(10ms)
  key(down)

(sidebar | panel) bookmarks: user.firefox_bookmarks_sidebar()
(sidebar | panel) history: user.firefox_history_sidebar()
