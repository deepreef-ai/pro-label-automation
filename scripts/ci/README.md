# scripts/ci

CI guard scripts (owner: Vinay). This folder is **locked**: change it only in a `[ci]` PR.

## `integrity.py`: what it checks

The `integrity` job runs first in CI. If it fails, nothing else runs.

**a. Locked paths go in their own PR.**
Locked paths are `tests/`, `apps/web/e2e/`, `.github/`, `scripts/ci/`, `contract/`,
`pyproject.toml` and `requirements-dev.txt`.
- A PR that changes a locked path **and** any other file fails. Split it in two.
- A PR that changes only locked paths must have a title starting with `[tests]`, `[ci]`
  or `[contract]` (for example `[tests] add MSME due-date edge case`).
- `[foundation]` may touch anything. It was used once, for the first foundation PR.

**b. No client data or secrets.** Fails if a PR adds or changes anything under `data/`,
a `.env` / `.env.*` file (`.env.example` is fine), or any `.xlsx`, `.xls`, `.db`,
`.sqlite` file. The repo is public.

**c. No skipped or focused tests.** Every changed file in `tests/` and `apps/web/e2e/`
is read in full. It fails on `pytest.mark.skip`, `pytest.skip(`, `xfail`, `.only(`,
`test.skip(`, `describe.skip` or `it.skip`. Fix the code, not the test.

**d. Coverage cannot go down.** `--cov-fail-under` in `.github/workflows/ci.yml` must
stay at 90 or higher (rules engine `apps/api/core/rules`).

On a push to `main` it runs in **scan** mode: rules b, c and d over every tracked file.

## Run it locally

```bash
git fetch origin
PR_TITLE="my PR title" python scripts/ci/integrity.py --base origin/main
python scripts/ci/integrity.py --scan
```
