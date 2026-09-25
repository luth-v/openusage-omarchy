# Agent notes

- Verify with `tests/run.sh`.
- After changing any QML or JS, run `dev/install.sh` before asking the user
  to test. It copies the workspace into the installed plugin and runs
  `omarchy-restart-shell`. The shell's hot reload logs "Local plugin
  changed, reloading" but keeps serving old nested QML, so a copy without
  the restart looks like the fix did nothing.
- Open the Dashboard without the pointer:
  `qs ipc --pid "$(pgrep -f 'quickshell.*omarchy/shell')" call luth-v.openusage-omarchy toggle`.
