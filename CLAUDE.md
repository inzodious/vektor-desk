# Vektor Desk: working rules for Claude threads

Read `docs/project-plan.md` first. It names the workstreams and the files each one owns.

- Only change files your workstream owns. Need a change elsewhere? Message the owning thread.
- Branch from the latest `main`. One phase is one PR. Re-merge `main` before review; never force-push a shared branch.
- No GitHub Actions minutes. Run lint, tests and build locally (`scripts/check.sh` runs them all; paste its summary), plus Playwright screenshots at 1920, 1440 and 390 wide in light and dark for anything visual, and list what ran in the PR body.
- Never commit personal figures, balances, account numbers, statements, tokens or keys. Use synthetic fixtures.
- Nothing may hold broker credentials or place trades. Nothing may write to Escape Vektor's Firestore.
- Model calls go through the Claude Code CLI (`claude -p`) runner only.
- Docs: short, plain, tables over paragraphs. Code: no inline comments except section labels.
- Don't edit `CHANGELOG.md` or `ROADMAP.md` (they conflict on every parallel PR). Put a `Changelog:` line in the PR body and list the roadmap items it delivers; Lead writes both in when the phase is cut.
