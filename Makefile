.PHONY: test test-cov lint typecheck

test:
	pytest

test-cov:
	pytest --cov --cov-report=term-missing --cov-report=html

lint:
	ruff check .

typecheck:
	ty check src/