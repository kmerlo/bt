# Advisor Plans Index

**Base commit**: `bd5650a`  
**Date**: 2026-08-23  
**Audit level**: standard  
**Package manager**: uv (migrating from pip)

---

## Execution Order & Dependencies

| # | Plan | Depends On | Priority | Status |
|---|------|------------|----------|--------|
| 01 | fix-cython-costmodel-export | — | P0 | ✅ DONE |
| 02 | validate-commissions-signature | — | P0 | ✅ DONE |
| 03 | migrate-to-uv | — | P0 | ✅ DONE |
| 04 | fix-hatch-cython-editable | 03 | P1 | ✅ DONE |
| 05 | add-mypy-type-checking | 03 | P1 | READY |
| 06 | design-strategy-serialization | — | P2 | READY |
| 07 | design-plugin-system | — | P2 | READY |
| 08 | numby-2-compatibility-spike | — | P2 | READY |
| 09 | split-core-god-module | — | P3 | READY |

---

## Summary

| Category | Count | Total Effort |
|----------|-------|--------------|
| Correctness / Bugs | 2 | 2S |
| DX & Tooling | 2 | 1S |
| Dependencies & Migrations | 2 | 1S + 1M |
| Direction | 3 | 3M (design plans) |
| Tech Debt | 1 | 1L (design only) |

**Estimated total**: 5S + 3M + 1L

---

## Plan Details

### P0 — High-leverage, low-effort fixes

- **01** `fix-cython-costmodel-export` — Add missing `AlmgrenChrissCostModel` to Cython export list. Fix: 1 line in `setup.cfg` or pyproject.toml. Risk: LOW. Effort: S.
- **02** `validate-commissions-signature` — Add runtime check that `commissions` is callable with `(q, p)` signature. Risk: LOW. Effort: S.
- **03** `migrate-to-uv` — Replace `pip` with `uv` in Makefile and CI. Risk: LOW. Effort: S.

### P1 — Productivity improvements

- **04** `fix-hatch-cython-editable` — Use `uv` to resolve Cython build isolation. Blocked by 03. Risk: MED. Effort: M.
- **05** `add-mypy-type-checking` — Add mypy config + baseline. Blocked by 03. Risk: LOW. Effort: M.

### P2 — Direction & design plans

- **06** `design-strategy-serialization` — Design JSON/YAML strategy format for reproducibility and GUI support. Effort: M.
- **07** `design-plugin-system` — Design extension point for custom algos without modifying core. Effort: M.
- **08** `numpy-2-compatibility-spike` — Test and document NumPy 2.x migration path. Effort: M.

### P3 — Major refactor (design only)

- **09** `split-core-god-module` — Design submodule boundary for `core.py` (Node, Strategy, Security, CostModel). Effort: L (design).

---

## Notes

- All plans use `uv` as the package manager per user request.
- Design plans (DIR-01, DIR-02) are scoped as investigation + spec, not implementation.
- Plan 09 (god module split) is a design plan only — execution deferred.
- The `plans/` directory contains the bt-gui GUI spec; this `advisor-plans/` is for bt core improvements.