.PHONY: check fmt lint type test

check: fmt lint type test

fmt:
	uv run ruff format --check .

lint:
	uv run ruff check .

type:
	uv run mypy git_feature

test:
	uv run pytest -q
