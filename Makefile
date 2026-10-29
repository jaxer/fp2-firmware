PYTHON ?= python3
.PHONY: fast area gate firmware cards radar ui
fast:
	mkdir -p .tools
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v
	npm --prefix ha-card test
area: fast
	npm --prefix ha-card run build
	$(PYTHON) tools/audit_public_tree.py
ui:
	npm --prefix ha-card run build
	npm --prefix ha-card run test:ui
gate: area ui
	uv run --python 3.13 --with esphome==2026.8.2 python tools/build_firmware.py
firmware:
	uv run --python 3.13 --with esphome==2026.8.2 python tools/build_firmware.py
cards:
	npm ci --prefix ha-card
	npm --prefix ha-card run build
radar:
	$(PYTHON) firmware/radar_export/build.py
