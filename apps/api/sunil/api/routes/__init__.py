"""Route modules. Each router is included explicitly by `create_app`, with no
`include_router(dependencies=…)` anywhere: a dependency attached to a router
silently applies to every path beneath it, which is how a route-scoped credential
stops being route-scoped (ADR-035, C5 contract test 8)."""
