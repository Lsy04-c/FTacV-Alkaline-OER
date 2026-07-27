# oer-wf

Reusable computational workflow for the OER-FTAcV project.

**Principle**: engineering steps are reusable; scientific judgement is not automated.

## Quick start

```bash
# install (editable)
cd oer-wf
pip install -e ".[dev]"

# health check
wf doctor

# prepare a commit-specific worktree
wf prepare examples/solver_equiv_01.yaml

# clean intermediate state
wf clean 3f9aad1/solver_equiv_01
wf clean 3f9aad1/solver_equiv_01 --force
```

All commands emit a unified JSON response on stdout:

```json
{
  "status": "pass|fail|warning|running",
  "fail_type": "environment|transport|structure|numerical|scientific|null",
  "checks": [...],
  "data": {...},
  "next_action": "...",
  "message": "..."
}
```

## Status

| Phase | Items | Status |
|-------|-------|--------|
| 1 | SSH ForceCommand + Shim, rsync, archive dir | done |
| 1 | project skeleton, doctor, prepare, clean | done |
| 2 | smoke, run, status | done |
| 3 | sync, verify, git-check | done |
| A7 | real Legion infrastructure smoke | pending |

See `docs/` and the framework document for full design.
