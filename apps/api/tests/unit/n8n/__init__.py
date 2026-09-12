"""Stream E — the n8n lane's adapter-level tests.

Everything here runs with NO n8n container: the mount is checked against the
repository's own `config/*.yaml`, and the protocol lane is replayed from a
handshake recorded off the live 2.38.5 server (`fixtures/`). The live proof —
that the MCP endpoint enforces its bearer — is evidence in
`docs/tasks/S2-E-n8n.md`, not a CI test, because a test that needs a running
container is a test that gets skipped.
"""
