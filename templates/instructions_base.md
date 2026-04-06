# Coding Standards & Preferences

## Naming Conventions
- Never use single-character variable names — always use descriptive, multi-word names
- Function and method names should clearly communicate their purpose
- Constants should be UPPER_SNAKE_CASE with meaningful names

## Code Style — Go
- Comment every 3 lines to explain intent, not mechanics
- Godoc comments on all exported functions, types, and constants
- Prefer explicit error handling over panics

## Code Style — Python
- Type hints on all function signatures
- Docstrings on all public functions and classes
- Prefer explicit imports over wildcard imports

## Commenting Etiquette
- Every 3rd line of code should have a comment — more comments than code is the goal
- Comments should explain the **why** over the **what** — the code itself shows what is happening, comments explain the reasoning and intent behind it
- Every function, method, and class must have a doc comment explaining its purpose and any non-obvious behavior
- Inline comments should provide context that a future reader (or agent) would need to understand design decisions
- When in doubt, add a comment — over-commenting is always preferred over under-commenting

## Code Style — General
- Keep functions short and focused on a single responsibility
- Prefer composition over inheritance
- Avoid over-engineering — solve the current problem, not hypothetical future ones

## Architecture Context
This project is part of the Bridgit → Krax → Harness pipeline:
- **Bridgit** handles repository existence (sync, provision, guardrails)
- **Krax** handles construction (project setup, source upload, code generation)
- **Harness** handles evolution (benchmarks, self-improvement loops)

Inter-service communication flows through **ThePostalService** (RabbitMQ daemon).
