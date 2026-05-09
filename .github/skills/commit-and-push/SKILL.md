---
name: commit-and-push
description: 'Stage, commit, and push local Git changes to the current branch on the remote. Use when the user says "commit and push", "commit my changes", "push the changes", "ship it", "save to git", or asks to create a commit. Generates a Conventional Commits message from the diff when no message is provided. Confirms before pushing.'
argument-hint: '[optional commit message]'
---

# Commit and Push Changes

Stage all working-tree changes, create a commit with a meaningful message, and push to the current branch's upstream.

## When to Use

- User says: "commit and push", "commit my changes", "push the changes", "ship it", "save to git", "git push"
- After completing a logical chunk of work the user wants persisted to the remote
- Do **not** use for: reverting commits, force-pushing, rewriting history, or pushing to a different branch (ask first in those cases)

## Inputs

- **$ARGUMENTS** (optional): commit message provided by the user. If empty, generate one from the staged diff.

## Procedure

Run each step sequentially. Use the terminal tool for all git commands.

### 1. Inspect the working tree

```powershell
git status --short --branch
```

- If output shows "nothing to commit, working tree clean" → tell the user there is nothing to commit and stop.
- Note the current branch and whether an upstream is configured (look for `## branch...origin/branch`).

### 2. Review the diff

```powershell
git diff --stat
git diff --staged --stat
```

If the diff is small, also run `git diff` (and `git diff --staged`) to read the actual changes — you need this to write a good commit message.

**Safety check**: Scan the diff for accidental secrets (API keys, passwords, `.env` contents, private keys). If any are found, **stop and warn the user** before proceeding.

### 3. Stage changes

```powershell
git add -A
```

This stages new, modified, and deleted files in the whole repo. If the user asked to commit only specific files, stage only those instead.

### 4. Build the commit message

If `$ARGUMENTS` is non-empty, use it verbatim.

Otherwise, generate a [Conventional Commits](https://www.conventionalcommits.org/) message from the staged diff:

- **Format**: `<type>(<scope>): <subject>` (subject ≤ 72 chars, imperative mood, no trailing period)
- **Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`
- **Scope**: short module/area name derived from the changed paths (e.g. `app`, `scheduler`, `db`); omit if changes span many areas
- Add a body (blank line, then wrapped at ~72 cols) only when the change isn't self-explanatory from the subject

Examples:
- `fix(app): silence chatty Azure Cosmos SDK loggers`
- `feat(scheduler): add per-location progress reporting`
- `docs: clarify scheduler vs manual run behavior in README`

### 5. Confirm with the user before committing

Show the user:
- The branch name
- The list of changed files (`git status --short`)
- The proposed commit message

Ask: *"Commit and push with this message? (yes / edit / cancel)"*

- **yes** → continue to step 6
- **edit** → take the new message and re-confirm
- **cancel** → run `git reset` to unstage and stop

### 6. Commit

```powershell
git commit -m "<subject>" [-m "<body>"]
```

Use a second `-m` for the body when present. **Never** use `--no-verify` (do not bypass pre-commit hooks).

### 7. Push

Determine the push command:

```powershell
git rev-parse --abbrev-ref --symbolic-full-name '@{u}'
```

- Exit code 0 → upstream exists → `git push`
- Non-zero → no upstream → `git push -u origin <current-branch>`

Get the current branch with `git branch --show-current` if needed.

**Never** use `--force` or `--force-with-lease` unless the user explicitly asks for it.

### 8. Report the result

Show the user:
- The commit SHA (`git log -1 --oneline`)
- The remote branch and a note that the push succeeded
- If push failed (e.g. non-fast-forward), report the error and suggest `git pull --rebase` — do **not** auto-resolve.

## Anti-patterns

- Committing without reading the diff (you can't write a useful message blind)
- Pushing without user confirmation
- Using `git add .` from a sub-directory (use `git add -A` from repo root, or stage explicit paths)
- Bypassing hooks with `--no-verify`
- Force-pushing on shared branches
- Committing files matching `.env*`, `*.pem`, `*_rsa`, `secrets.*` without asking
