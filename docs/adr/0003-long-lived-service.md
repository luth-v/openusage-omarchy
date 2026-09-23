# One long-lived service owns refresh

Upstream is a single app process; a bar widget's processes die on every Omarchy hot-reload. So the plugin ships an Omarchy `service` that owns refresh, pricing, notifications, the update check, the loopback-only HTTP API on 127.0.0.1:6736, and the state the CLI reads. The bar widget and its panels are views over that state. A timer-driven updater script was rejected: it cannot hold an hourly pricing cache, serve the API, or dedupe notifications across runs.

The Omarchy `service` kind is a QML entry point, not a Python process: `Service.qml` runs in-process and owns a Python child over a stdin command pipe (JSON lines, EOF means exit). The child holds an `flock` on its runtime lock so a second instance exits cleanly. The service is not `keepLoaded`, so a plugin update reloads it; all durable state (cache, pricing, dedup keys, update timestamp, snooze) lives on disk to make restarts cheap.

Upstream treats a cached value as fresh only when fetched during the current running session. That rule is keyed to a login-session id stored in `$XDG_RUNTIME_DIR/openusage-omarchy/session`, not to the daemon PID, so a hot-reload does not re-hit the provider APIs. The runtime dir clears at logout, which gives the same first-pass-after-login refresh upstream has.
