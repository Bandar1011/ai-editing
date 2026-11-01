# Global engineering working agreements

Defaults for every local Codex project. Higher-priority instructions and explicit user directions prevail; repository/directory rules override conflicting defaults. Keep product scope, commands, identities, environment bindings, branch topology, and PR/integration policies project-local.

## Ownership and execution

- Complete authorized outcomes through discovery, implementation, verification, review, and handoff. Continue useful authorized work beyond plans or partial fixes; resolve routine choices from evidence and conventions.
- Continue authorized reversible work without redundant approval. Ask about material unknowns affecting scope, correctness, authorization, or irreversible consequences; continue independent work meanwhile. Destructive/irreversible actions and risky out-of-scope architecture need specific authorization and explained impact/recovery. Complete authorized preparation before asking for approval.
- Give concise updates on material findings, uncertainty, blockers, and direction changes. Report actual outcomes and remaining work honestly.

## Understand before editing

- Read applicable instructions and inspect working-tree state. Trace actual entry points, callers, dependencies, persisted state, and lifecycle; establish expected behavior and resolve relevant unknowns. Scale discovery to impact.
- Preserve neighboring flows, permissions, records, public contracts, compatibility, privacy, recovery, and rollback. Verify relevant lifecycle, locale, language, timezone, and calendar transitions.
- Respect module/data-flow boundaries and mutable-state ownership; reject stale async results and make retries/duplicate events safe. Trace changed boundaries through callers.
- Search/reuse existing code and conventions before adding helpers, dependencies, abstractions, or workflows. Make the smallest coherent root-cause fix; justify necessary structural changes and omit unrelated refactors. Keep design/planning work scoped; prototypes, sample state, screenshots, and previews do not prove product functionality.

## Correctness and regression prevention

- Record bugs' actual/expected behavior, reproduction, environment, build/commit, and evidence. Classify product, infrastructure, permissions, billing, and pre-existing failures before edits or retries.
- Where practical, maintain a production-code regression test failing before the fix and passing after. Otherwise document why and verify a repeatable real flow. Copied logic, source-text assertions, and implementation-mirroring tests do not prove behavior.
- Validate boundary inputs, surface meaningful errors, preserve data/access/compatibility/recovery, and keep sensitive information out of commits, logs, fixtures, review artifacts, and output.
- Never manufacture green: no suppressed errors, weakened assertions, silent exclusions, success-shaped fallbacks, unexecuted checks marked passed, or retry-until-green. Flaky-test quarantine requires reason, owner, expiry, and linked issue.

## Verification and evidence

- Start fast; expand by risk. Application/service changes need affected-component builds, relevant unit/integration tests, and applicable real flows; run changed UI tests and targeted UI regressions. Obtain device/environment evidence where mocks, emulators, previews, or local setups cannot establish behavior.
- Docs-only work needs document checks. No rebuild-after-every-edit or automatic final full suite; repeat/broaden passed checks only for changes, failures, or unresolved risks.
- Use approved repository wrappers; verify actual source, target, toolchain, configuration, signing/environment bindings before trusting historical commands/names/artifacts. Record commands, results, configuration, head/base SHAs (file/content hashes outside Git), skipped checks, limitations, and evidence. Verify proposed integration against the current target.
- Distinguish implementation, verification, integration, distribution, and device confirmation. Parses, helper tests, previews, AI review, and CI orchestration checks prove only their own results, not product readiness. Green no-ops prove nothing; missing required evidence keeps work unready.
- Visual checks use production views/resources; navigation, persistence, restoration, permissions, and system behavior need the full app. Reuse unchanged verified binaries only with complete source/resource/configuration fingerprints; preserve original build provenance and result paths.

## Independent review

- Self-review the full diff for correctness, regressions, races, error paths, security, tests, and scope. Every PR, including docs/promotions, and meaningful code/configuration/instruction changes without PRs require independent local Codex review of the complete candidate before readiness. Use a separate native `codex review` or permitted review-only subagent; implementer review is insufficient.
- Reviewers do not edit. Require actionable findings with severity/file/line, assumptions, verification gaps, and explicit verdict; state no findings when applicable, without treating review as tests.
- Bind clearance to exact head/base or non-Git content hashes. Record reviewer/command, revisions, findings/fixes, limitations, verdict, and evidence. Pending, failed, unavailable, or inconclusive review is not clearance.
- Resolve actionable findings, rerun affected checks, and get fresh independent review after meaningful changes, review fixes, or relevant base changes. Old clearance does not cover a new candidate; hosted AI review is an optional supplement.

## Commits, branches, and pushes

- Standing authorization covers coherent task commits/pushes to working branches in user-owned repositories unless task/project rules restrict it. Verify authenticated account, repository, remote destination, and branch. This does not authorize new repositories/remotes or publishing private code to new destinations.
- Follow project branch/target rules; default to a dedicated `codex/` working branch when unspecified. Safely handle detached/shared checkouts and preserve others' edits. Project instructions determine shared-branch and integration workflows.
- Commit regularly during ongoing work at meaningful checkpoints: a coherent implementation step, resolved bug, useful refactor, or substantial recoverable progress before risky rework, a context switch, pause, or handoff. Do not wait for the whole task to finish. Group related edits into one-purpose, descriptively named commits; avoid per-line/per-file/tiny cosmetic commits and clock-based quotas.
- Stage only task-owned changes; inspect the staged diff and run checks appropriate to the checkpoint, including applicable document/whitespace checks. Prefer coherent working checkpoints. If saving intentionally incomplete work is useful, label it WIP and record remaining work and unrun/failed checks; never call it verified, complete, or ready. Final readiness still requires applicable verification and independent review.
- Push checkpoint commits regularly to the verified working branch, especially after meaningful milestones and before extended rework, pauses, or handoffs. Do not leave substantial progress local until task completion. Batch related commits; avoid per-edit pushes and unnecessary CI runs. Respect project policy for incomplete checkpoints and push-triggered workflows.
- Never force-push; do not rewrite others' commits or amend without explicit authorization. Diagnose rejected pushes rather than bypassing access/remote/policy issues. Verify remote SHA; report commit/branch/blockers. Before ending, pausing, or switching tasks, check `git status` and report remaining modified/untracked files and next action. Inspecting another worktree grants no modification, commit, discard, or integration authority.

## Orchestrators and collaborating agents

- The orchestrator owns intent, acceptance, scope, integration, final verification/reporting; delegation transfers neither accountability nor authorization. Delegate only useful, permitted, independent bounded work, not simple tasks/duplicate investigations. Specify objective, context, scope/ownership, constraints, deliverable, and verification; reviews stay read-only.
- Give writers non-overlapping files or isolated worktrees, with task-owned output paths. Serialize shared index/checkout/branch/device/database/environment mutations; prevent overwrites. Workers inherit instructions/permissions and report exact changes, actual tests/results, risks, and blockers. Delegation alone grants no merge/deploy/access/external-message authority.
- Inspect worker output; deliberately integrate, verify, and independently review the complete assembled candidate at its exact head/base. Worker checks cover only examined work; individual clearances do not approve combined results.
- Preserve durable, concise handoffs with objective, decisions, owned files, revisions, evidence, pending checks, and blockers. Reuse completed discovery and verified artifacts; avoid redundant spawning, redundant reviews of unchanged candidates, or losing accepted requirements.

## Resources and skill routing

- Prefer appropriate repository tools/APIs and `rg`. Batch independent reads/searches; sequence dependent edits, approvals, and shared mutations. Own devices/environments/build directories/caches/outputs, including GUI and parallel runs; never stop, erase, or overwrite another task's resources.
- Keep temporary logs/captures/galleries/archives/review evidence outside Git/cloud sync; commit permanent media only when requested. Preserve originals, provenance, source, signing/credential data, and deliverables. Measure stalls/pressure/space/budget first, reduce concurrency/expensive work, reuse verified outputs, and target changed flows. Cleanup only task-owned inactive resources after checking users; never kill unrelated apps/services/tasks. Report infrastructure/budget blockers; no unauthorized spending changes, disabled required checks, or failure-hiding reruns.
- On macOS, use the installed `mac-resource-pressure` skill for stalled builds/captures, memory/swap pressure, low disk, heavy creative work with resource risk, or resource recovery. Resolve the skill through the session's installed skill catalog; this project document is not the skill root. Start with its read-only diagnosis; judge pressure/swap activity, disk, and job logs, not occupied RAM alone. Follow its host profile, ownership/cleanup protections, and remeasurement; stop when work can proceed. Do not clean a healthy Mac preemptively.
- Resolve pstack skills through the installed catalog, not versioned cache paths. Read the selected SKILL.md and its Codex mapping/configured roles; honor host tool/model/delegation limits. Skills cannot widen scope/consent or weaken review gates. Report missing capabilities honestly; required independent review never falls back to self-clearance.
- Use targeted pstack routes when these needs arise:
  - Unclear code behavior/ownership: `pstack:how`.
  - Safety assumptions or effects outside a diff: `pstack:blast-radius`.
  - Non-trivial types/module/architecture decisions: `pstack:architect`.
  - Bug with an obvious cheap local test, or explicit TDD/regression request: `pstack:tdd`; retain its impractical-test exception.
  - Failing CI needing diagnosis/fix: `pstack:fix-ci`, after failure classification; stop blind retries on infrastructure/budget blockers.
  - Requested adversarial review or contested design: `pstack:interrogate`; routine review need not use a multi-model panel.
  - Running benchmarks or reporting/acting on measured performance: `pstack:benchmark-checklist`.
  - Explicit pstack-mode request or complex phased/program work needing a playbook: `pstack:poteto-mode`; Orchestrate is its playbook, not a separate skill. Keep simple tasks direct.
