run:
	@# Create virtual enviroment
	@python -m venv .venv
	@
	@# install deps
	@.venv/bin/pip install rich
	@.venv/bin/pip install textual
	@
	@# run from venv
	@.venv/bin/python tree.py

