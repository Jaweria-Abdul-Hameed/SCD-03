# RAHBAR Makefile (assignment sec. 9 — these are the documented commands)
#
# Usage:
#   make cluster   — start minikube with Calico + addons
#   make build     — build api, ui, indexer images (SHA tag, never the floating latest tag)
#   make deploy    — apply the prod overlay, wait for the api rollout
#   make index     — run the indexer Job once, wait for completion
#   make eval      — run eval/run_eval.py against the live stack
#   make test      — pytest with >=60% coverage on the app package (stub provider)
#   make lint      — ruff + mypy
#   make check     — the submission checker (sec. 8)
#
# Image tags use the current git SHA only — never the floating latest tag (sec. 6).

SHELL := /bin/bash
TAG ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo local)
NAMESPACE := rahbar
KUSTOMIZE ?= kustomize
KUBECTL ?= kubectl

.PHONY: cluster build deploy index eval test lint check clean reindex smoke corpus-to-cluster

cluster: ## Start minikube with Calico (NetworkPolicy is silently ignored without it)
	minikube start --driver=docker --cni=calico --memory=6144 --cpus=4
	minikube addons enable metrics-server
	minikube addons enable ingress

build: ## Build api, ui and indexer images (no push; SHA tag only)
	docker build -t rahbar-api:$(TAG) ./api
	docker build -t rahbar-ui:$(TAG) ./ui
	docker build -t rahbar-indexer:$(TAG) ./indexer

corpus-to-cluster: ## Populate the corpus-data PVC from corpus/raw/ (run before make index)
	# The indexer Job mounts the corpus-data PVC at /corpus; an empty PVC
	# means the Job finds no documents (exit 2). Create the PVC if needed,
	# run a temporary busybox pod mounting it, copy corpus/raw/ into
	# /corpus/raw/ on the claim, then delete the pod.
	$(KUBECTL) apply -f k8s/base/corpus-pvc.yaml
	@printf '%s\n' 'apiVersion: v1' 'kind: Pod' 'metadata:' '  name: corpus-loader' '  namespace: $(NAMESPACE)' 'spec:' '  restartPolicy: Never' '  containers:' '    - name: loader' '      image: busybox:1.36' '      command: ["sleep", "3600"]' '      volumeMounts:' '        - name: corpus' '          mountPath: /corpus' '  volumes:' '    - name: corpus' '      persistentVolumeClaim:' '        claimName: corpus-data' > /tmp/corpus-loader-pod.yaml
	$(KUBECTL) apply -f /tmp/corpus-loader-pod.yaml
	$(KUBECTL) wait --for=condition=ready pod/corpus-loader -n $(NAMESPACE) --timeout=120s
	$(KUBECTL) exec -n $(NAMESPACE) pod/corpus-loader -- mkdir -p /corpus/raw
	$(KUBECTL) cp corpus/raw/. corpus-loader:/corpus/raw/ -n $(NAMESPACE)
	$(KUBECTL) delete pod corpus-loader -n $(NAMESPACE) --wait=true

deploy: ## Build images, retag :SHA with the git SHA tag, apply prod overlay, wait for rollout
	# TAG comes from `git rev-parse --short HEAD` (fallback `local` if git
	# is absent — see the TAG definition at the top of this file). The
	# literal `:SHA` placeholder in the manifests is NEVER deployed: the
	# kustomize output is sed-replaced `:SHA` -> `:$(TAG)` before apply,
	# and the images are built locally with the matching ghcr.io names.
	docker build -t ghcr.io/rahbar/api:$(TAG) ./api
	docker build -t ghcr.io/rahbar/ui:$(TAG) ./ui
	docker build -t ghcr.io/rahbar/indexer:$(TAG) ./indexer
	$(KUSTOMIZE) build k8s/overlays/prod | sed 's/:SHA/:$(TAG)/g' | $(KUBECTL) apply -f -
	$(KUBECTL) rollout status deployment/api -n $(NAMESPACE) --timeout=300s
	$(KUBECTL) rollout status deployment/ui -n $(NAMESPACE) --timeout=300s
	$(KUBECTL) get pods -n $(NAMESPACE)

index: ## Run the indexer Job once (indexing is a Job, never API startup)
	$(KUBECTL) apply -f k8s/base/indexer-job.yaml
	$(KUBECTL) wait --for=condition=complete --timeout=600s job/indexer -n $(NAMESPACE)

reindex: ## Re-index without a redeploy (manual run of the weekly CronJob)
	$(KUBECTL) create job --from=cronjob/reindex manual-reindex-1 -n $(NAMESPACE)

eval: ## Run the evaluation against the live stack (writes eval/results.json)
	python eval/run_eval.py --output eval/results.json

test: ## pytest with >=60% coverage on the app package (stub provider, no network/model)
	LLM_PROVIDER=stub EMBED_MODEL=nomic-embed-text pytest api/tests indexer/tests \
		--cov=api/app --cov-report=term-missing --cov-fail-under=60

lint: ## ruff + mypy
	ruff check api indexer eval scripts
	ruff format --check api indexer eval scripts
	mypy api/app indexer/pipeline --ignore-missing-imports

check: ## Submission checker (sec. 8) — must exit 0 before submitting
	python scripts/check_submission.py

smoke: ## Smoke test through the Ingress: ordinary + must-abstain question
	@curl -s -H 'Host: rahbar.local' -X POST http://$(shell minikube ip)/api/chat \
		-H 'Content-Type: application/json' \
		-d '{"question": "Can a student register for a course after failing its prerequisite?"}' | head -c 500; echo
	@curl -s -H 'Host: rahbar.local' -X POST http://$(shell minikube ip)/api/chat \
		-H 'Content-Type: application/json' \
		-d '{"question": "What are the hostel allotment rules for first-year students?"}' | head -c 500; echo

clean: ## Remove local build artefacts (never the committed eval results)
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache coverage.xml
