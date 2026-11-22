<!-- ORGANVM:AUTO:START -->
## Agent Context (auto-generated — do not edit)

This repo participates in the **ORGAN-VI (Community)** swarm.

### Active Subscriptions
- Event: `governance.updated` → Action: Check compliance with updated governance rules
- Event: `curriculum.created` → Action: Update available learning modules

### Production Responsibilities
- **Produce** `learning_path` for unspecified

### External Dependencies
- **Consume** `package` from `unspecified`

### Governance Constraints
- Adhere to unidirectional flow: I→II→III
- Never commit secrets or credentials

*Last synced: 2026-04-14T21:32:11Z*
<!-- ORGANVM:AUTO:END -->

## Repository stewardship

Read [BRANCHES.md](BRANCHES.md) before creating or changing branches. Preserve the auto-generated block above.

- Verify → Heal → Expand → Evolve. Do not expand on unverified or dishonest default behavior.
- One intention per PR, one successor per shared-root-cause family. Recover unique residue before consolidation.
- Use one worktree per claimed working branch. Main receives reviewed PRs only.
- Keep credentials, populated learner profiles/databases and private source archives outside public git.
- Record the issue, lease owner, base/head, write scope, expiry, evidence and handoff before implementation.
- Agent claims are recorded in [docs/claims/leases.yaml](docs/claims/leases.yaml) and enforced by the claim check (see [ADR 006](docs/adr/006-agent-claims.md)); a claim in a comment alone still provides no technical lock. A PR whose changed files fall inside another grantee's active lease fails CI until a lease is granted.
- Merge evidence is evaluated by [docs/merge-evidence.md](docs/merge-evidence.md) (see [ADR 007](docs/adr/007-merge-evidence.md)); a merge requires the six required checks at the exact head plus an independent review at the head, and no approval binds a head it was not recorded at.
- Review/check evidence binds the current head and relevant base. Infrastructure non-execution is not a pass or a code-test failure.
- Close only after the finish line is verified on default, with intention, evidence, successor and no-unique-loss verdict.
- The current coordination contract and dependency queue are in [roadmap #21](https://github.com/organvm/adaptive-personal-syllabus/issues/21). Claims in comments are procedural; they do not provide technical locks.
