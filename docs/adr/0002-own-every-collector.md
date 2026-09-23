# Own every collector

Upstream parity needs Metrics the packaged Omarchy Claude and Codex collectors never request (Extra Usage, Rate Limit Resets, Codex Spark, multi-account, Spend), so this repo owns all eleven Provider collectors, ported from upstream's providers. Credentials are read only inside collectors; they never pass through QML or command arguments. Spend comes from local logs as totals only; conversation content never leaves the collector. This reverses ADR-0001's reliance on packaged collectors and its removal of local log scans.
