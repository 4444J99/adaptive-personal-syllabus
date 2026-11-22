# Handoff schema — adaptive-personal-syllabus #36 (MTR-010)

The minimum a handoff carries, per #36 question 3 and ADR 006. Anything
less is not a handoff: the receiving agent re-derives nothing, and a
handoff that fails this checklist is refused with a receipt citing the
missing item. Unpublished work is captured first, per BRANCHES.md: a
patch/bundle or a durable remote branch in its proper privacy boundary —
never a bare "it is on my machine".

## Checklist

- [ ] **Issue:** the issue number this handoff continues (e.g. #36).
- [ ] **Lease owner:** the grantee named in the lease record, and the
  lease sequence (e.g. sequence 1, grantee `ranked-queue-build`).
- [ ] **Base/head:** the main head the work was verified against (base
  SHA) and the work head (branch head SHA) at handoff time.
- [ ] **Write scope:** the exact repo-relative paths this claim may
  change, as recorded in the lease. Shared contracts count as overlap:
  a scope that touches a shared contract must name it.
- [ ] **Expiry:** the lease expiry (ISO-8601). Past expiry, the scope is
  free and the handoff is void — re-grant before resuming.
- [ ] **Receipt:** the grant receipt (the #21 lease-grant comment id) and
  the evaluation receipt from `agent_claims.py`, if one was produced.
- [ ] **Capture location:** where the unpublished work lives — a
  patch/bundle path, or a durable remote branch name. If nothing is
  unpublished, say so explicitly; silence is not a capture.

## Worked example (this PR, #36)

- Issue: #36 (MTR-010).
- Lease owner: `ranked-queue-build`, sequence 1.
- Base/head: base `8dc861bc` (main at grant); head is the PR head at merge.
- Write scope: `docs/adr/006-agent-claims.md`, `docs/claims/leases.yaml`,
  `docs/claims/handoff.md`, `src/adaptive_personal_syllabus/agent_claims.py`,
  `tests/test_agent_claims.py`, `.github/workflows/ci.yml`,
  `AGENTS.md`, `docs/privacy-classification.yaml`, `BRANCHES.md` (#36 row).
- Expiry: `2026-11-29T12:00:00Z`.
- Receipt: lease grant on #21 (comment 7078376585).
- Capture location: nothing unpublished — all work is on the branch
  `work/mentor/agent-claims`, pushed to the remote.
