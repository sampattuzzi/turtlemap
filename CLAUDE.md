# Turtlemap

Browse a Python, JavaScript or TypeScript codebase as dependency maps and
Unreal-style dataflow blueprints, in the browser. See [README.md](README.md) for what it does and how
it is put together.

## Running and testing

```bash
poetry install --with dev
poetry run mypy .
poetry run pytest tests
poetry run code-blueprints .
```

[.github/workflows/ci.yml](.github/workflows/ci.yml) is the source of truth for
what CI runs.

## Conventions

- **No comments or docstrings** in code you add. Make the code explain itself
  through names and structure.
- **mypy strict** must pass. Don't add `Any` where a real type is known.
- **No `__init__.py` files.** Packages are implicit namespace packages and
  imports use full module paths.
- **Format with Black**, only the files you changed.
- **Tests** are plain pytest, named by the behaviour they check
  (`test_links_subclass_to_its_base`). Arrange helpers are `make_*`, assertion
  helpers `expect_*`.
- **Private helpers go below the public functions** that use them.
- **The analysis never imports or runs the code it reads.** Each language's
  front end in `languages/` parses it (`ast` for Python, tree-sitter for
  JavaScript and TypeScript) into the model in `analysis/model.py`, and the
  rest of the analysis works only on that model.
- **Check UI changes in a real browser.** `poetry run code-blueprints . --no-open`
  prints the address; drive it with Playwright and look at the result, and try
  a large project as well as a small one.
