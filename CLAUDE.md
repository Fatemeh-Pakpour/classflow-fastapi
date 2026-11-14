
# ClassFlow — Project Instructions

## Project
ClassFlow is a class management and booking platform
for a sports club with approximately 1,000 members.

## Architecture
- Modular monolith
- Frontend: Next.js + TypeScript
- Backend: FastAPI + Python (if adopted)
- Database: PostgreSQL
- ORM: SQLAlchemy (if adopted)
- Authentication: Auth0

Read existing code before proposing architecture changes.
Treat the actual repository as the source of truth.

## Commands

Backend: Python 3.14, managed with **uv**, `src/` layout. Always run tools through
`uv run` (uses the project `.venv`); never call `pip` directly.

```bash
uv sync                                              # install deps incl. dev group
uv run fastapi dev src/classflow_fastapi/__init__.py # dev server with auto-reload
uv run pytest                                        # all tests
uv run pytest path/to/test_file.py::test_name        # single test
uv run ruff check .                                  # lint
uv run ruff format .                                 # format
uv run mypy src                                      # type-check
uv add <pkg> / uv add --dev <pkg>                    # add a dependency (updates uv.lock)
```

## Engineering principles
- Prefer simple solutions over unnecessary abstractions.
- Keep business rules separate from HTTP handlers.
- Keep database access separate from domain logic.
- Avoid microservices unless explicitly justified.
- Preserve existing behavior when refactoring.
- Consider security, authorization, and concurrency.

## Development workflow
For new features:
1. Use Superpowers brainstorming.
2. Explore requirements and edge cases.
3. Present alternatives with trade-offs.
4. Wait for design approval before implementation.
5. Write a detailed implementation plan.
6. Follow test-driven development:
   RED -> GREEN -> REFACTOR.
7. Run relevant tests and review the diff.
8. Do not commit without explicit approval.

## Important business rules
- Never allow bookings beyond available capacity.
- Prevent duplicate active bookings.
- Do not trust client-provided user or payment state.
- Handle concurrent booking attempts correctly.
- Never log secrets or access tokens.
- Keep payment operations idempotent.

## Agent behavior
- Ask focused questions when requirements are unclear.
- Don't introduce new dependencies without a reason.
- Don't rewrite unrelated files.
- Explain technical trade-offs.
- Report tests actually run and their results.
