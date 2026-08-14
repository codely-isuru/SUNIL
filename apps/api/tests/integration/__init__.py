"""Reserved for QA-owned integration tests (docs/M1_BUILD_PLAN.md T18: QA owns
`tests/{integration,exit}/**` exclusively).

Empty for now: the T18 brief's primary deliverable is the ET-1..ET-12 exit-test
harness in `tests/exit/`, which is where all fault-injection and contract-level
coverage currently lives. This package exists so ownership of the directory is
established and no other lane writes here; QA will add narrower, component-level
integration tests here as individual backend components (router, tool manager, plan
validator) land and stabilise, if the exit suite's own coverage leaves a gap.
"""
