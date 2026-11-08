#!/usr/bin/env python3
"""RAHBAR submission checker (assignment sec. 8).

Run from the repository root::

    python scripts/check_submission.py

It is a lint, not a grader: it catches the mechanical failures behind
most of the automatic deductions in sec. 8. A clean run does not
guarantee a good mark, but a dirty run nearly guarantees a bad one.

Checks (one PASS/FAIL line each, plus a summary):
  1. Required paths from the sec. 10 repository layout exist.
  2. No secret patterns in git-tracked files (AKIA keys, private-key
     blocks, real api_key assignments, non-placeholder base64 Secrets).
  3. Namespace is `rahbar` everywhere (no `namespace: default`).
  4. Chroma is a StatefulSet with volumeClaimTemplates.
  5. No NodePort/LoadBalancer on Chroma or Redis services.
  6. Every container specifies CPU and memory requests AND limits.
  7. No floating latest image tag in workflows or manifests (deploy by SHA).
  8. `needs:` on every publishing/deploying job.
  9. golden.yaml has >= 15 questions with all 5 mandatory type counts.
 10. ADR 0001 covers all four indexer-as-Job failure modes.
 11. ENGINEERING-NOTES answers all 7 questions (heading check).
 12. .gitignore covers *-secret.yaml.

Exit code 0 only if there are zero failures, non-zero otherwise.
"""

from __future__ import annotations

import base64
import binascii
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a declared dependency
    yaml = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Required paths (assignment sec. 10 layout). Directories end with "/".
# ---------------------------------------------------------------------------
REQUIRED_PATHS = [
    # API
    "api/app/schemas.py",
    "api/Dockerfile",
    "api/.dockerignore",
    # Indexer
    "indexer/pipeline/extract.py",
    "indexer/pipeline/clean.py",
    "indexer/pipeline/chunk.py",
    "indexer/pipeline/embed.py",
    "indexer/pipeline/store.py",
    "indexer/Dockerfile",
    "indexer/.dockerignore",
    # UI
    "ui/Dockerfile",
    "ui/nginx.conf",
    # Corpus
    "corpus/MANIFEST.md",
    "scripts/fetch_corpus.py",
    # Eval
    "eval/golden.yaml",
    "eval/run_eval.py",
    "eval/baseline.json",
    "eval/results.json",
    "eval/fixtures/",
    # Kubernetes — base
    "k8s/base/namespace.yaml",
    "k8s/base/api-deployment.yaml",
    "k8s/base/ui-deployment.yaml",
    "k8s/base/chroma-statefulset.yaml",
    "k8s/base/redis.yaml",
    "k8s/base/indexer-job.yaml",
    "k8s/base/reindex-cronjob.yaml",
    "k8s/base/services.yaml",
    "k8s/base/ingress.yaml",
    "k8s/base/configmap.yaml",
    "k8s/base/networkpolicy.yaml",
    "k8s/base/hpa.yaml",
    "k8s/base/kustomization.yaml",
    # Kubernetes — overlays
    "k8s/overlays/dev/kustomization.yaml",
    "k8s/overlays/prod/kustomization.yaml",
    # Docs
    "docs/CORPUS.md",
    "docs/PIPELINE.md",
    "docs/FAILURE-ANALYSIS.md",
    "docs/ENGINEERING-NOTES.md",
    "docs/AI-USAGE.md",
    "docs/ARCHITECTURE.md",
    "docs/adr/0001-indexer-as-job.md",
    "docs/adr/0002-semantic-cache-redis.md",
    "docs/adr/0003-llm-provider-pluggable.md",
    "docs/adr/0004-embedding-pin.md",
    # Workflows, checker, root files
    "scripts/check_submission.py",
    ".github/workflows/ci.yml",
    ".github/workflows/cd.yml",
    ".gitignore",
    "Makefile",
    "README.md",
    "LICENSE",
]

PLACEHOLDER_VALUES = {
    "",
    "placeholder",
    "replace_me",
    "replace-me",
    "changeme",
    "change-me",
    "your-api-key",
    "your_api_key",
    "xxx",
    "todo",
    "stub-key-for-ci-only",
}

# Files/dirs never scanned for secrets (the checker itself contains the
# patterns as literals; binary/corpus artefacts are not source).
SECRET_SCAN_EXCLUDES = {
    "scripts/check_submission.py",
    ".git/",
    "__pycache__/",
    ".venv/",
    "corpus/raw/",
}
SECRET_SCAN_SUFFIX_EXCLUDES = (".pdf", ".png", ".jpg", ".jpeg", ".gif")

# (pattern, description) — a match is a failure unless the value is an
# obvious placeholder / stub / example.
SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key (AKIA...)"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "GitHub personal access token (ghp_...)"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "GitHub fine-grained token"),
    (re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----"), "private key block"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "API key with sk- prefix"),
    (
        re.compile(r"""(?i)(api_key|apikey|api-key)\s*[:=]\s*["']([^"'\s]{16,})["']"""),
        "api_key assignment with a real-looking value",
    ),
    (
        re.compile(r"""(?i)(password|passwd|secret)\s*[:=]\s*["']([^"'\s]{8,})["']"""),
        "password/secret assignment with a real-looking value",
    ),
]


def _is_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in PLACEHOLDER_VALUES:
        return True
    return any(
        word in lowered
        for word in (
            "placeholder",
            "replace",
            "change_me",
            "change-me",
            "example",
            "stub",
            "todo",
            "your-",
            "your_",
            "<",
            "$",
        )
    )


def _tracked_files() -> list[Path]:
    """Git-tracked files if this is a git repo, else all files under ROOT."""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        files = [ROOT / line for line in out.stdout.splitlines() if line.strip()]
        if files:
            return files
    except Exception:  # noqa: BLE001, S110 — git ls-files failure falls back to rglob
        pass
    return [p for p in ROOT.rglob("*") if p.is_file()]


def _load_yaml_docs(path: Path) -> list[dict]:
    if yaml is None:
        return []
    docs: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for doc in yaml.safe_load_all(f):
                if isinstance(doc, dict):
                    docs.append(doc)
    except Exception:  # noqa: BLE001, S110 — YAML parsing failure falls back to empty doc list
        pass
    return docs


def _iter_k8s_yaml_files() -> list[Path]:
    files: list[Path] = []
    for base in (ROOT / "k8s",):
        if base.exists():
            files.extend(sorted(base.rglob("*.yaml")))
            files.extend(sorted(base.rglob("*.yml")))
    return files


# ---------------------------------------------------------------------------
# Individual checks. Each returns (passed: bool, detail: str).
# ---------------------------------------------------------------------------
def check_required_paths() -> tuple[bool, str]:
    missing = [p for p in REQUIRED_PATHS if not (ROOT / p).exists()]
    if missing:
        return False, f"missing {len(missing)}: {', '.join(missing)}"
    return True, f"all {len(REQUIRED_PATHS)} required paths exist"


def check_no_secrets() -> tuple[bool, str]:
    problems: list[str] = []
    for path in _tracked_files():
        rel = str(path.relative_to(ROOT))
        if any(ex in rel for ex in SECRET_SCAN_EXCLUDES):
            continue
        if rel.endswith(SECRET_SCAN_SUFFIX_EXCLUDES):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except Exception:  # noqa: BLE001, S112 — binary or unreadable file
            continue
        for pattern, description in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                # For assignment-style patterns the captured value is group 2.
                value = (
                    match.group(2)
                    if match.lastindex and match.lastindex >= 2
                    else match.group(0)
                )
                if _is_placeholder(value):
                    continue
                problems.append(f"{rel}: {description}")
                break
        # Base64 Secret with a real (non-placeholder) value in a manifest.
        if path.suffix in (".yaml", ".yml") and "k8s" in rel:
            for doc in _load_yaml_docs(path):
                if doc.get("kind") != "Secret":
                    continue
                data = doc.get("data") or {}
                string_data = doc.get("stringData") or {}
                for key, value in {**data, **string_data}.items():
                    if not isinstance(value, str):
                        continue
                    decoded = value
                    if key in data:
                        try:
                            decoded = base64.b64decode(value, validate=True).decode(
                                "utf-8", errors="replace"
                            )
                        except (binascii.Error, ValueError):
                            decoded = value
                    if not _is_placeholder(decoded):
                        problems.append(
                            f"{rel}: Secret '{doc.get('metadata', {}).get('name')}' "
                            f"key '{key}' holds a non-placeholder value (-15)"
                        )
    if problems:
        return False, "; ".join(problems[:10])
    return True, "no secret patterns in tracked files; no real-value base64 Secret"


def check_namespace() -> tuple[bool, str]:
    problems: list[str] = []
    for path in _iter_k8s_yaml_files():
        rel = str(path.relative_to(ROOT))
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001, S112 — unreadable file
            continue
        if re.search(r"namespace:\s*default\b", text):
            problems.append(f"{rel}: namespace: default")
        for doc in _load_yaml_docs(path):
            ns = (doc.get("metadata") or {}).get("namespace")
            if ns is not None and ns != "rahbar":
                problems.append(f"{rel}: metadata.namespace={ns!r} (want 'rahbar')")
    # The namespace object itself must be rahbar.
    ns_file = ROOT / "k8s/base/namespace.yaml"
    if ns_file.exists():
        docs = _load_yaml_docs(ns_file)
        names = [
            (d.get("metadata") or {}).get("name")
            for d in docs
            if d.get("kind") == "Namespace"
        ]
        if names and names != ["rahbar"]:
            problems.append(
                f"namespace.yaml defines Namespace {names} (want ['rahbar'])"
            )
    if problems:
        return False, "; ".join(problems)
    return True, "namespace rahbar everywhere; no 'namespace: default'"


def check_chroma_statefulset() -> tuple[bool, str]:
    path = ROOT / "k8s/base/chroma-statefulset.yaml"
    if not path.exists():
        return False, "k8s/base/chroma-statefulset.yaml missing"
    docs = _load_yaml_docs(path)
    kinds = [d.get("kind") for d in docs]
    if "StatefulSet" not in kinds:
        return False, f"chroma is {kinds}, not a StatefulSet (-8)"
    for doc in docs:
        if doc.get("kind") == "StatefulSet":
            spec = doc.get("spec") or {}
            if "volumeClaimTemplates" not in spec:
                return False, "StatefulSet has no volumeClaimTemplates (-8)"
            replicas = spec.get("replicas")
            if replicas not in (1, "1"):
                return False, f"StatefulSet replicas={replicas} (want 1)"
    return True, "Chroma is a StatefulSet (1 replica) with volumeClaimTemplates"


def check_no_nodeport_loadbalancer() -> tuple[bool, str]:
    problems: list[str] = []
    for path in _iter_k8s_yaml_files():
        rel = str(path.relative_to(ROOT))
        for doc in _load_yaml_docs(path):
            if doc.get("kind") != "Service":
                continue
            name = (doc.get("metadata") or {}).get("name", "")
            svc_type = (doc.get("spec") or {}).get("type", "ClusterIP")
            if svc_type in ("NodePort", "LoadBalancer"):
                problems.append(f"{rel}: Service/{name} is {svc_type}")
            if name in ("chroma", "redis") and svc_type != "ClusterIP":
                problems.append(
                    f"{rel}: Service/{name} type={svc_type} (want ClusterIP, -8)"
                )
    if problems:
        return False, "; ".join(problems)
    return True, "no NodePort/LoadBalancer; Chroma and Redis are ClusterIP"


def check_resources() -> tuple[bool, str]:
    if yaml is None:
        return False, "PyYAML not available — cannot parse manifests"
    problems: list[str] = []
    checked = 0
    for path in _iter_k8s_yaml_files():
        rel = str(path.relative_to(ROOT))
        for doc in _load_yaml_docs(path):
            kind = doc.get("kind")
            if kind not in ("Deployment", "StatefulSet", "Job", "CronJob", "DaemonSet"):
                continue
            spec = doc.get("spec") or {}
            # CronJob nests the pod template one level deeper.
            template = spec.get("template") or (spec.get("jobTemplate") or {}).get(
                "spec", {}
            ).get("template", {})
            pod_spec = (template or {}).get("spec") or {}
            containers = list(pod_spec.get("containers") or []) + list(
                pod_spec.get("initContainers") or []
            )
            for container in containers:
                checked += 1
                name = container.get("name", "?")
                resources = container.get("resources") or {}
                req = resources.get("requests") or {}
                lim = resources.get("limits") or {}
                for field in ("cpu", "memory"):
                    if field not in req:
                        problems.append(
                            f"{rel}: {kind}/{name} missing requests.{field} (-6)"
                        )
                    if field not in lim:
                        problems.append(
                            f"{rel}: {kind}/{name} missing limits.{field} (-6)"
                        )
    if problems:
        return False, "; ".join(problems[:10])
    if checked == 0:
        return False, "no containers found in manifests — nothing to check"
    return True, f"all {checked} containers specify CPU+memory requests and limits"


def check_no_latest() -> tuple[bool, str]:
    # The tag pattern is built dynamically so this checker file itself
    # never contains the literal tag string.
    latest_tag = ":lat" + "est"
    problems: list[str] = []
    search_roots = [ROOT / ".github" / "workflows", ROOT / "k8s"]
    for base in search_roots:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in (".yml", ".yaml"):
                continue
            rel = str(path.relative_to(ROOT))
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
            ):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if latest_tag in line:
                    problems.append(f"{rel}:{lineno}: '{latest_tag}' tag")
    if problems:
        return False, "; ".join(problems) + " — deploy by commit SHA only (-6)"
    return True, f"no '{latest_tag}' tag in workflows or manifests"


def check_needs() -> tuple[bool, str]:
    if yaml is None:
        return False, "PyYAML not available — cannot parse workflows"
    problems: list[str] = []
    checked = 0
    for workflow in ("ci.yml", "cd.yml"):
        path = ROOT / ".github" / "workflows" / workflow
        if not path.exists():
            problems.append(f".github/workflows/{workflow} missing")
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001 — report YAML parsing error
            problems.append(f"{workflow}: unparsable YAML ({exc})")
            continue
        jobs = data.get("jobs") or {}
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            steps = job.get("steps") or []
            text = str(steps)
            publishes_or_deploys = (
                "push: true" in text
                or "docker/build-push-action" in text
                and "push: true" in text
                or "kubectl apply" in text
                or "kubectl rollout" in text
                or job_name in ("build-push", "deploy", "e2e-eval")
            )
            if publishes_or_deploys:
                checked += 1
                if "needs" not in job:
                    problems.append(
                        f"{workflow} job '{job_name}' publishes/deploys without needs: (-6)"
                    )
    if problems:
        return False, "; ".join(problems)
    if checked == 0:
        return False, "no publishing/deploying jobs found to check"
    return True, f"all {checked} publishing/deploying jobs have needs:"


def check_golden() -> tuple[bool, str]:
    path = ROOT / "eval" / "golden.yaml"
    if not path.exists():
        return False, "eval/golden.yaml missing"
    if yaml is None:
        return False, "PyYAML not available — cannot parse golden.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 — report golden.yaml parsing error
        return False, f"golden.yaml unparsable ({exc})"
    questions = data.get("questions") or []
    counts: dict[str, int] = {}
    for q in questions:
        counts[q.get("type", "?")] = counts.get(q.get("type", "?"), 0) + 1
    required = {
        "ordinary": 8,
        "version-sensitive": 2,
        "exact-term": 2,
        "must-abstain": 2,
        "prompt-injection": 1,
    }
    problems = []
    if len(questions) < 15:
        problems.append(f"only {len(questions)} questions (want >= 15)")
    for qtype, minimum in required.items():
        if counts.get(qtype, 0) < minimum:
            problems.append(f"{qtype}: {counts.get(qtype, 0)} (want >= {minimum})")
    if problems:
        return False, "; ".join(problems)
    return True, f"golden.yaml: {len(questions)} questions, counts {counts}"


def check_adr_0001() -> tuple[bool, str]:
    path = ROOT / "docs" / "adr" / "0001-indexer-as-job.md"
    if not path.exists():
        return False, "docs/adr/0001-indexer-as-job.md missing"
    text = path.read_text(encoding="utf-8").lower()
    # The four failure modes of sec. 4.2, in the assignment's own words.
    modes = {
        "1 concurrent writers / race": ("race", "concurrent"),
        "2 every restart re-indexes": ("restart", "re-index"),
        "3 readiness becomes a lie": ("readiness", "lie"),
        "4 cannot re-index without a redeploy": ("redeploy",),
    }
    missing = [
        name for name, keywords in modes.items() if not all(k in text for k in keywords)
    ]
    if missing:
        return False, "ADR 0001 missing failure mode(s): " + "; ".join(missing)
    if "kubectl create job --from=cronjob/reindex" not in text:
        return False, "ADR 0001 missing the manual reindex command"
    return True, "ADR 0001 covers all four failure modes + manual reindex command"


def check_engineering_notes() -> tuple[bool, str]:
    path = ROOT / "docs" / "ENGINEERING-NOTES.md"
    if not path.exists():
        return False, "docs/ENGINEERING-NOTES.md missing"
    text = path.read_text(encoding="utf-8")
    missing = [f"Q{i}" for i in range(1, 8) if f"## Q{i}" not in text]
    if missing:
        return False, "ENGINEERING-NOTES missing question(s): " + ", ".join(missing)
    return True, "ENGINEERING-NOTES answers all 7 questions (Q1–Q7 headings present)"


def check_gitignore() -> tuple[bool, str]:
    path = ROOT / ".gitignore"
    if not path.exists():
        return False, ".gitignore missing"
    text = path.read_text(encoding="utf-8")
    if "*-secret.yaml" not in text:
        return False, ".gitignore does not cover *-secret.yaml"
    lines = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if "eval/results.json" in lines:
        return (
            False,
            ".gitignore ignores eval/results.json — it must be COMMITTED (sec. 8)",
        )
    return True, ".gitignore covers *-secret.yaml; eval/results.json is not ignored"


CHECKS = [
    ("required paths (sec. 10 layout)", check_required_paths),
    ("no secrets in tracked files", check_no_secrets),
    ("namespace rahbar everywhere", check_namespace),
    ("Chroma StatefulSet + PVC", check_chroma_statefulset),
    ("no NodePort/LoadBalancer on Chroma/Redis", check_no_nodeport_loadbalancer),
    ("every container has requests+limits", check_resources),
    ("no floating latest tag in workflows/manifests", check_no_latest),
    ("needs: on publishing/deploying jobs", check_needs),
    ("golden set >= 15, all 5 types", check_golden),
    ("ADR 0001 covers four failure modes", check_adr_0001),
    ("ENGINEERING-NOTES answers 7 questions", check_engineering_notes),
    (".gitignore covers *-secret.yaml", check_gitignore),
]


def main() -> int:
    print(f"RAHBAR submission checker — repo root: {ROOT}")
    print("=" * 72)
    failures = 0
    for name, fn in CHECKS:
        try:
            passed, detail = fn()
        except Exception as exc:  # noqa: BLE001 — a checker crash must not masquerade as a pass
            passed, detail = False, f"checker error: {exc}"
        status = "PASS" if passed else "FAIL"
        if not passed:
            failures += 1
        print(f"[{status}] {name}: {detail}")
    print("=" * 72)
    if failures:
        print(
            f"RESULT: {failures} check(s) FAILED out of {len(CHECKS)} — fix before submitting."
        )
        return 1
    print(f"RESULT: all {len(CHECKS)} checks PASSED — clean run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
