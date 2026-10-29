# Contributing

Keep domain rules independent of ESPHome/HA. Pass measurements and time into
state machines; keep I/O in adapters and views thin. Preserve unknown states and
reject unsupported versions before mutation.

```sh
npm ci --prefix ha-card
make fast
make area
```

`make ui` checks real browser rendering against explicitly synthetic isolated data.
Install Chromium first: `ha-card/node_modules/.bin/playwright install chromium --only-shell`.
`make gate` includes these UI checks and additionally requires private configuration and the pinned ESPHome
build. Tests never access hardware. Use isolated synthetic fixtures or small
sanitized protocol examples with provenance; never commit household recordings,
zone maps, credentials, dumps or combined vendor images.

For protocol changes, document the supported firmware identity, byte grammar,
evidence and remaining uncertainty. Keep both translations complete. Include
screenshots for UI changes and distinguish isolated demonstrations from hardware
observations. A successful build, ACK or reset is not hardware acceptance.
