"""The SUNIL-owned model routing layer (C2 §2 "Router stays SUNIL").

``capability × privacy_class → (model alias, provider name)`` from
``config/models.yaml``, plus the one retry policy in the system (C2 §4) and the
SUNIL-side cost arithmetic (C2 §2).

**This package must never read the ADR-033 transport lane flag** (named in
ADR-033 and read only by ``providers/registry.py``), directly or through an
import: privacy/capability policy runs before provider selection precisely so
that no transport setting can widen which workloads reach a cloud provider. The
rule is enforced mechanically by
``tests/unit/routing/test_lane_flag_tripwire.py`` — which greps these modules
for the variable's very name — and not by this docstring.
"""
