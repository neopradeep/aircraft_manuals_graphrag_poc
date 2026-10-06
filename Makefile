PY := ./.venv/bin/python

.PHONY: setup dry-run ingest eval ask models

setup:            ## create venv + install deps
	python3 -m venv .venv
	$(PY) -m pip install -r requirements.txt

dry-run:          ## parse manuals only (no DB / OpenAI)
	$(PY) -m src.ingest --dry-run

ingest:           ## build the graph (wipes target DB)
	$(PY) -m src.ingest --reset

eval:             ## score vector / graph / hybrid
	$(PY) -m src.evaluate

ask:              ## make ask M=hybrid Q="your question"
	$(PY) -m src.retrieve $(M) "$(Q)"

models:           ## list models for your key + test configured ones (make models F=embed)
	$(PY) -m src.list_models $(F)
