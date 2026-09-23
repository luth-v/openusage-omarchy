# Layout lives outside shell.json

Every write to `~/.config/omarchy/shell.json` rewrites the whole file and reloads the shell, and that file is often tracked in dotfiles. So only Settings preferences live there; the Customize layout (Metric order, Always Visible/On Demand, Stars, open carets) lives in a versioned plugin-owned state file. Provider API keys go to the Secret Service keyring via libsecret, falling back to a 0600 file when no keyring runs.
