.PHONY: test test-cov lint typecheck analysis

test:
	pytest

test-cov:
	pytest --cov --cov-report=term-missing --cov-report=html

lint:
	ruff check .

typecheck:
	ty check src/

arch:
	zip -r /tmp/analysis.zip src tests Dockerfile docker-compose.yml docker-compose.dev.yml pyproject.toml alembic.ini Caddyfile -x "**/__pycache__/*" "**/*.pyc"