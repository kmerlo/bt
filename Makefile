TMPREPO=/tmp/docs/bt

default: build_dev

.PHONY: dist upload docs pages serve klink notebooks test benchmark lint fix develop
.PHONY: build_dev

develop:
	uv sync --all-groups --all-extras

test:
	uv run pytest -vvv tests --cov=bt --junitxml=python_junit.xml --cov-report=xml --cov-branch --cov-report term

benchmark:
	uv run pytest -vv benchmarks --benchmark-only

lint:
	uv run ruff check bt docs/source/conf.py
	uv run ruff format --check bt docs/source/conf.py

fix:
	uv run ruff check --fix bt docs/source/conf.py
	uv run ruff format bt docs/source/conf.py

dist:
	uv run python -m build --sdist --wheel
	uv run twine check dist/*

upload: dist
	uv run twine upload dist/* --skip-existing

docs:
	$(MAKE) -C docs/ clean
	$(MAKE) -C docs/ html

pages:
	rm -rf $(TMPREPO)
	git clone -b gh-pages git@github.com:pmorissette/bt.git $(TMPREPO)
	rm -rf $(TMPREPO)/*
	cp -r docs/build/html/* $(TMPREPO)
	cd $(TMPREPO);\
	git add -A ;\
	git commit -a -m 'auto-updating docs' ;\
	git push

serve:
	cd docs/build/html; \
	uv run python -m http.server 9087

build_dev:
	uv run pip install -e . --no-build-isolation

clean:
	rm -rf build dist
	rm -rf dist
	rm -rf bt.egg-info
	find . -name '*.so' -delete
	find . -name '*.c' -delete

klink:
	git subtree pull --prefix=docs/source/_themes/klink --squash klink master

notebooks:
	cd docs/source; \
	uv run jupyter notebook --no-browser --ip=*
