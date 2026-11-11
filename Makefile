.PHONY: install test lint typecheck check evaluate run clean

PYTHON ?= python
TOPIC ?= Iran Iranian Tehran

install:  ## install the package with every optional feature, plus the NER model
	$(PYTHON) -m pip install -e ".[dev,nlp,pdf]"
	$(PYTHON) -m spacy download en_core_web_sm

test:  ## run the tests (no network needed)
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy

check: lint typecheck test  ## everything CI runs

evaluate:  ## score name extraction and the tone word lists on labeled articles
	$(PYTHON) -m osint_monitor evaluate

run:  ## collect now and write the report and brief to output/
	$(PYTHON) -m osint_monitor --db data/articles.db collect
	$(PYTHON) -m osint_monitor --db data/articles.db report --keywords $(TOPIC) --out output

clean:
	rm -rf output .pytest_cache .mypy_cache .ruff_cache .coverage dist build *.egg-info
