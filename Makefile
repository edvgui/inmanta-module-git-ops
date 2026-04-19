SOURCE_DIRS = inmanta_plugins tests docs/example/inmanta_plugins

isort = isort $(SOURCE_DIRS)
black_preview = black --preview $(SOURCE_DIRS)
black = black $(SOURCE_DIRS)
flake8 = flake8 $(SOURCE_DIRS)
pyupgrade = pyupgrade --py312-plus $$(find $(SOURCE_DIRS) -type f -name '*.py')

format:
	$(black_preview)
	$(black)
	$(isort)
	$(flake8)
	$(pyupgrade)

install:
	uv pip install -U -r requirements.dev.txt -c requirements.txt -e .
