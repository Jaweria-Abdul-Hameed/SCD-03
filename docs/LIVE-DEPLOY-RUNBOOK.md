# Live-deploy runbook (superseded)

This file was the Friday 2026-11-06 plan for the first live deployment. That deployment has been done;
the runbook is replaced by tested, current documents - use these instead:

| You want to ... | Use |
|---|---|
| deploy from a clean clone | `README.md` ("Apply order") and, for the in-cluster Ollama mode, README "Alternative: Ollama inside the cluster" |
| rebuild everything on Windows in one command | `scripts/rebuild-from-scratch.ps1` (about 1 hour) |
| bring the stack back after a reboot | `scripts/demo-up.ps1` (then `scripts/demo-check.ps1`) |
| run the demo | `docs/DEMO.md` |
| see what was measured on the live cluster | `docs/evidence/README.md` |
