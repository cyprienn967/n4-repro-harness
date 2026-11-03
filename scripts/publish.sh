#!/usr/bin/env bash
# Run locally, from anywhere. This publishes source; it never runs experiments.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
repo_name="${1:-aig-exact}"
if ! command -v gh >/dev/null; then
  echo 'Install GitHub CLI from https://cli.github.com/ first.' >&2
  exit 1
fi
gh auth status
if [[ ! -d .git ]]; then
  git init -b main
fi
if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  git add README.md pyproject.toml .gitignore LICENSE src tests configs docs scripts
  git commit -m 'Add exact AIG synthesis and Boolean-function research harness'
fi
if git remote get-url origin >/dev/null 2>&1; then
  echo 'An origin remote already exists. Inspect it and push manually.' >&2
  exit 1
fi
gh repo create "$repo_name" --private --source=. --remote=origin --push
