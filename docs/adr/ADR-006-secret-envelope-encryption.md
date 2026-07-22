# ADR-006 — Secret envelope-encryption scheme

_Status: Accepted · Owner: Solution Architect · Phase: 1_

## Context

FR-040–FR-044 and SECURITY_MODEL §2: AES-256-GCM envelope encryption behind a swappable
`SecretStore` interface; unique IV per encryption; auth tag verified on read; master key from
the environment with hard startup validation; rotation without changing the reference;
"APIs never return a secret" as an invariant. The open design points were the exact envelope
construction, key versioning for rotation, IV/AAD handling, and how the never-returned
invariant is made structural.

## Decision

- **Two-tier envelope.** Per-secret 32-byte DEK encrypts the plaintext (AES-256-GCM, fresh
  12-byte IV, 16-byte tag). The DEK is wrapped by the KEK (AES-256-GCM, own fresh IV + tag).
  Row stores: ciphertext, iv, authTag, wrappedDek, dekIv, dekAuthTag, version,
  masterKeyVersion, fingerprint (see `PHASE1_ARCHITECTURE.md` §5.3/§8).
- **AAD binding.** Value encryption uses AAD `${secretId}:${version}`; DEK wrap uses AAD
  `${secretId}`. A ciphertext copied between rows or versions fails authentication — this
  closes the ciphertext-swap gap that plain GCM leaves open.
- **KEK sourcing and versioning.** `SUNIL_MASTER_KEY` (base64, exactly 32 bytes — boot fails
  otherwise, no fallback or generated key), `SUNIL_MASTER_KEY_VERSION`, optional
  `SUNIL_MASTER_KEY_PREVIOUS` enabling lazy re-wrap on read/rotate. KEK rotation therefore
  never requires bulk re-encryption downtime.
- **Value rotation (FR-044).** New DEK + IV + ciphertext overwrite the old columns in one
  update; `version`++; prior ciphertext is retained nowhere, making it structurally
  unretrievable.
- **Structural never-return invariant.** `get()` returns a `SecretValue` wrapper (plaintext
  reachable only via `.use(fn)`; `toJSON`/`toString`/inspect yield `"[REDACTED]"`);
  DTO-allowlisted secret endpoints; a serialisation interceptor that throws on any
  `SecretValue` in a response; a dependency-cruiser fence limiting `get()` call sites to
  server-side packages; ET-5 sentinel scans as the standing regression.

## Rejected alternatives

- **Single-key direct encryption (no DEK).** Simpler, but KEK rotation would require
  re-encrypting every secret in one migration event, and a KEK compromise exposes all
  ciphertexts with one key. Envelope structure is also what makes the interface swappable
  for KMS/Vault later (they wrap DEKs; the calling code shape stays identical).
- **AES-256-CBC + HMAC (encrypt-then-MAC).** Sound when composed correctly, but composition
  is the failure mode; GCM is AEAD in one primitive and is what SECURITY_MODEL mandates
  anyway.
- **XChaCha20-Poly1305.** Larger nonce removes IV-collision anxiety, but SECURITY_MODEL §2
  names AES-256-GCM; with fresh random 12-byte IVs per write and per-secret DEKs, collision
  probability is cryptographically negligible at any realistic write volume. No grounds to
  deviate from the binding document.
- **Deriving per-secret keys from the KEK (HKDF) instead of storing wrapped DEKs.** Avoids
  wrap columns but couples every ciphertext directly to the KEK, reintroducing the bulk
  re-encryption problem on rotation.
- **Managed vault (AWS/Azure/HashiCorp) now.** Phase 1 is local-only (assumption A-01); the
  interface is explicitly shaped so a vault can replace the implementation later without
  touching callers (FR-040) — building the integration now is scope creep.

## Consequences

- Stored rows satisfy ET-5 5.2/5.3/5.9 by construction (plaintext absent; unique IVs ⇒
  differing ciphertexts; any single-byte tamper ⇒ loud authenticated failure, audited).
- Losing the master key means losing every secret — LOCAL_SETUP.md documents generation and
  the consequence (risk R-07); no recovery path exists by design.
- The `SecretValue` wrapper imposes a slightly awkward `.use(fn)` call shape on engineers —
  that friction is the control.
