.PHONY: help app test lint format clean

help:
	@echo "Warehouse AI Operational Platform"
	@echo "---------------------------------"
	@echo "make app       - Run the Streamlit operations copilot dashboard"
	@echo "make test      - Run full pytest test suite"
	@echo "make lint      - Run ruff code quality checks"
	@echo "make format    - Auto-format code with ruff"
	@echo "make clean     - Clean python caches and temporary artifacts"

app:
	streamlit run app/streamlit_app.py

test:
	pytest

lint:
	ruff check .

format:
	ruff format .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

