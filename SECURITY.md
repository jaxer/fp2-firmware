# Security and private data

Keep device backups, radar dumps, network credentials, API keys, OTA passwords
and household captures private. Ignored files are still sensitive; back them up
separately. Public CI uses disposable build-only credentials.

The native HA API is encrypted and OTA requires a password. The radar monitor
is a privileged memory interface on the internal UART; do not expose a raw bridge
to the network. Only run research tools on hardware you own or may modify.

When reporting an issue, include software versions and a minimal sanitized
protocol example. Do not attach a full dump or configuration export containing
private values. Open a public issue with a non-sensitive summary first if a
private report channel has not been configured.
