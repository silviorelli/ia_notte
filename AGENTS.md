# Agent Guidelines for Python Code Quality

This document provides guidelines for maintaining high-quality Python code. These rules MUST be followed by all AI coding agents and contributors.

## Critical Rules
1. Document the whole architecture in ./documentation/architecture.md keep it updated and hold it in the context
2. Document the technial choices in ./documentation/technical_choices.md keep it updated and hold it in the context
3. Document the API contracts in ./documentation/api.json in swagger format, keep it updated and read it when relevant
4. Document the main commands in ./documentation/commands_cheatsheet.md, keep it updated
5. Keep also the main README.md up to date
6. If present, import project specific instructions from @AGENTS_PROJECT_SPECIFIC.md Such instructions can override what told in AGENTS.md

## Your Core Principles

All code you write MUST be appropriately optimized.

"appropriately optimized" includes:

- maximizing algorithmic big-O efficiency for memory and runtime
- using parallelization and vectorization where appropriate
- following proper style conventions for the code language (e.g. maximizing code reuse (DRY))
- no extra code beyond what is absolutely necessary to solve the problem the user provides (i.e. no technical debt)
  - If a Python library can be imported to significantly reduce the amount of new code required to implement a function at optimal performance, and the library itself is small and does not have much overhead, ALWAYS use the library instead.
- Ask, don't assume. If something is unclear, ask before writing a single line. Never make silent assumptions about intent, architecture, or requirements.
- Simplest solution first. Always implement the simplest thing that could work. Do not add abstractions or flexibility that weren't explicitly requested.
- Don't touch unrelated code. If a file or function is not directly part of the current task, do not modify it, even if you think it could be improved.
- Flag uncertainty explicitly. If you are not confident about an approach or technical detail, say so before proceeding. Confidence without certainty causes more damage than admitting a gap.


## Preferred Tools

- Use `uv` for Python package management and to create a `.venv` if it is not present.
- When reporting error to the console, use `logger.error` instead of `print`.

## Code Style and Formatting

- **MUST** use meaningful, descriptive variable and function names
- **MUST** follow PEP 8 style guidelines
- **MUST** use 4 spaces for indentation (never tabs), except in json files where 2 spaces must be used
- **NEVER** use emoji, or unicode that emulates emoji (e.g. ✓, ✗). The only exception is when writing tests and testing the impact of multibyte characters.
- Use snake_case for functions/variables, PascalCase for classes, UPPER_CASE for constants
- Limit line length to 100 characters (ruff formatter standard)
- **MUST** avoid including redundant comments which are tautological or self-demonstating (e.g. cases where it is easily parsable what the code does at a glance so the comment does)
- **MUST** avoid including comments which leak what this file contains, or leak the original user prompt, ESPECIALLY if it's irrelevant to the output code.
- **MUST** run the linter at the end of every code change and make sure the linting finishes without errors

## Documentation

- **MUST** include docstrings for all public functions, classes, and methods
- **MUST** document function parameters, return values, and exceptions raised
- Keep comments up-to-date with code changes
- Include examples in docstrings for complex functions
- Add comments where intent, trade-offs, or non-obvious behavior aren't clear from the code itself. Do not comment self-evident code.

Example docstring:

```python
def calculate_total(items: list[dict], tax_rate: float = 0.0) -> float:
    """Calculate the total cost of items including tax.

    Args:
        items: List of item dictionaries with 'price' keys
        tax_rate: Tax rate as decimal (e.g., 0.08 for 8%)

    Returns:
        Total cost including tax

    Raises:
        ValueError: If items is empty or tax_rate is negative
    """
```

## Type Hints

- **MUST** use type hints for all function signatures (parameters and return values)
- **NEVER** use `Any` type unless absolutely necessary
- Use `T | None` for nullable types

## Error Handling

- **NEVER** silently swallow exceptions without logging
- **MUST** never use bare `except:` clauses
- **MUST** catch specific exceptions rather than broad exception types
- **MUST** use context managers (`with` statements) for resource cleanup
- Provide meaningful error messages

## Function Design

- **MUST** keep functions focused on a single responsibility
- **NEVER** use mutable objects (lists, dicts) as default argument values
- Limit function parameters to 5 or fewer
- Return early to reduce nesting

## Class Design

- **MUST** keep classes focused on a single responsibility
- **MUST** keep `__init__` simple; avoid complex logic
- Use dataclasses for simple data containers
- Prefer composition over inheritance
- Avoid creating additional class functions if they are not necessary
- Use `@property` for computed attributes

## Testing

- **MUST** write unit tests for all new functions and classes
- **MUST** mock external dependencies (APIs, databases, file systems)
- **MUST** use pytest as the testing framework
- **NEVER** run tests you generate without first saving them as their own discrete file
- **NEVER** delete files created as a part of testing.
- Ensure the folder used for test outputs is present in `.gitignore`
- Follow the Arrange-Act-Assert pattern
- Do not commit commented-out tests
- **MUST** run the full test suite at the end of every code change and make sure the tests pass without errors

## Imports and Dependencies

- **MUST** avoid wildcard imports (`from module import *`)
- **MUST** document dependencies in `pyproject.toml`
- Use `uv` for fast package management and dependency resolution
- Organize imports: standard library, third-party, local imports

## Python Best Practices

- **NEVER** use mutable default arguments
- **MUST** use context managers (`with` statement) for file/resource management
- **MUST** use `is` for comparing with `None`, `True`, `False`
- **MUST** use f-strings for string formatting
- Use list comprehensions and generator expressions
- Use `enumerate()` instead of manual counter variables

## Security & privacy checklist (must consider)

- **NEVER** store secrets, API keys, or passwords in code. Only store them in `.env`
  - Ensure `.env` is declared in `.gitignore`.
  - **NEVER** print or log URLs to console if they contain an API key
- **MUST** use environment variables for sensitive configuration
- **NEVER** log sensitive information (passwords, tokens, PII)
- Input validation at boundaries (HTTP handlers, CLIs, file reads, message queues), using Pydantic where applicable
- No `eval/exec`
- Safe filesystem access (no path traversal; careful with temp files)
- Safe subprocess usage (no shell=True unless strictly necessary and safely parameterized)
- Secrets not exposed in logs/errors/tests
- Access control / authorization considered where applicable on "frontier" services
- Dependencies are justified and reviewed

If threat/risk is non-trivial, include a short “Security Notes” section in the PR description.

## Dependency policy

- Prefer standard library or existing deps.
- New deps require:
  - clear justification
  - maintenance/health consideration
  - license compatibility consideration
  - pinning according to repo tooling
  - test coverage demonstrating necessity
