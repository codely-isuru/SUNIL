# 2026-09-12 - Wave 1 merged (c474baa)

Six lanes built in parallel against the frozen contracts, integrated on a dedicated branch that
exposed 15 integration-only failures (event-loop collision, five wiring gaps, a missing column,
bearer asymmetry), all fixed with evidence. Alembic linearised - which surfaced a latent
duplicate-table defect that would have failed every fresh deploy. Security APPROVE-w-conditions
(C-1/C-3 -> wave 2, C-2 fixed in-wave with a call-counted timing proof). QA PASS after one real
blocker (C4 route awaited a wider service than the frozen contract declares - realigned to the
read-model pattern). Six SA rulings (R1-R6). QA R5 sign-off with mutation evidence. Suite
912/0/4 SQLite, 951/0/4 Postgres. Wave-2 requirements inherited by name in THREAT_MODEL para 9.
