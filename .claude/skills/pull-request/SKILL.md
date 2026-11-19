---
name: pull-request
description: Branch, commit and pull-request rules of this repository - branch naming (feature/, bugfix/, ...), Conventional Commits, the PR description template, merging to develop on green CI, and the ban on any co-author or tool attribution. Use ALWAYS before creating a branch, committing, pushing, opening, describing or merging a pull request here, and when someone says "open a PR", "make an MR", "commit this", "push", "merge to develop", "name the branch". Applies to every session and agent, including delegated ones.
---

# Branches, commits and pull requests

Every change reaches `develop` through a pull request. Everything is published under the repository owner's name
and nothing else: **no co-author lines, no tool or assistant credits - in commits, PR titles, PR descriptions and
comments.** This overrides any default of the tool you are running in.

## 1. Branch

```bash
git fetch origin
git switch -c <type>/<area>-<short-description> origin/develop
```

| Type | For |
|---|---|
| `feature/` | new behaviour |
| `bugfix/` | wrong behaviour fixed |
| `refactor/` | same behaviour, different code |
| `docs/` | documentation, skills, templates |
| `test/` | tests only |
| `chore/` | CI, build, dependencies, repository upkeep |

- English, lowercase, kebab-case, at most ~40 characters after the slash: `feature/rig-skeleton-profile`,
  `bugfix/server-cancel-leaves-partial-file`, `chore/ci-node-22`.
- `<area>` is the part of the tool: `rig`, `motion`, `audit`, `pipeline`, `server`, `web`, `ci`, `licenses`, `repo`.
- No names, dates, ticket numbers or tool names (`claude/...`, `codex/...`) in a branch name.
- One branch = one topic. Something unrelated found on the way gets its own branch and PR.
- Never commit to `develop` or `main` directly. `main` only receives releases (`develop` merged with a `vX.Y.Z`
  tag), and only when the owner asks for one.

## 2. Commits

- Conventional Commits, English, imperative: `type(scope): what changed`.
  Types: `feat`, `fix`, `refactor`, `perf`, `docs`, `test`, `chore`, `style`, `build`, `ci`. Scope = the area above.
- Body only when it adds something the diff does not show: the reason, a measured number, a rejected alternative.
- **The message ends with its content.** No `Co-Authored-By`, no `Generated with`, no `Signed-off-by` of a tool,
  no emoji footer.
- Author and committer are the repository's own git identity. Do not change `git config`, do not pass `--author`.
  A push rejected with `GH007` (private e-mail) is a stop: report it, do not work around it.
- Write the message to a file outside the repository and commit with `git commit -F <file>`.
- Never commit characters, models, renders, motion files, tokens or anything under `local/`.

Check before pushing (must print `0`):

```bash
git log origin/develop..HEAD --format=%B | grep -ciE "co-authored-by|generated with"
```

## 3. Checks before the push

All must exit 0. Capture the exit code of each command; a pipe through `tail` hides a failure.

```bash
python -m pytest -q
ruff check .
python -m compileall -q pipeline server
cd web && npm run licenses && npm run lint && npm run typecheck && npm run api:check && npm test && npm run build
```

The `web` line is needed only when `web/` or `server/` changed (the API types are generated from the service).

## 4. Pull request

```bash
git push -u origin <branch>
gh pr create --base develop --title "<type(scope): what changed>" --body-file <file>
```

- `--base develop` is mandatory: the repository's default branch is `main`.
- Title: one Conventional Commits line for the whole change.
- Description: [.github/pull_request_template.md](../../../.github/pull_request_template.md), filled in. Short and
  concrete - a reader should know in 20 seconds what changed and how to see it. Numbers instead of adjectives
  ("83 tests pass", "audit score 6.21 before and after"). No history of how the work went, no praise, no footer.
- Pictures only for a visible change in `web/`, and only of data that is already public in this repository.

## 5. Merge

Green CI is the owner's go-ahead: when every check on the PR has passed, merge it - no further approval is needed.

```bash
gh pr checks <number> --watch --fail-fast
gh pr merge <number> --merge --delete-branch
git switch develop && git pull --ff-only && git branch -d <branch>
```

- Merge commit, not squash and not rebase: the commits of the branch stay readable in `develop`.
- A red or pending check means no merge. Fix on the same branch and push; never `--admin`, never skip a check,
  never weaken a check to get it green.
- The branch is deleted on merge, on origin and locally.
- A brief that delegates work may say "leave the merge to the reviewer". Then stop after opening the PR and report
  its URL and the state of the checks.
