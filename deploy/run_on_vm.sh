#!/usr/bin/env bash
# Usage: run_on_vm.sh <dev|uat> <variant> <git-url> <branch> [docs-dir]
# Clones the repo on the VM, runs the pipeline, builds the UI and publishes it via deploy.sh.
# docs-dir (optional): folder already on the VM holding the vendor .docx files; if set,
# extract + lint reports are produced for each manifest interface whose file is found there.
set -euo pipefail

ENV_NAME="${1:?usage: run_on_vm.sh <dev|uat> <variant> <git-url> <branch> [docs-dir]}"
VARIANT="${2:?variant required}"
GIT_URL="${3:?git url required}"
BRANCH="${4:?branch required}"
DOCS_DIR="${5:-}"

WORK="${WORK_DIR:-$HOME/knowledge-hub-work}"
PIPELINE_REL="Knowledge_Hub_Build_Pipeline_4/Knowledge_Hub_Build_Pipeline_4"
UI_REL="Knowledge_Hub_Build_Pipeline_4/Knowledge Hub Tool"

if [ -d "$WORK/repo/.git" ]; then
  git -C "$WORK/repo" fetch --prune origin
  git -C "$WORK/repo" checkout -q "$BRANCH"
  git -C "$WORK/repo" reset -q --hard "origin/$BRANCH"
else
  mkdir -p "$WORK"
  git clone --branch "$BRANCH" "$GIT_URL" "$WORK/repo"
fi

REPO="$WORK/repo"
SHA="$(git -C "$REPO" rev-parse HEAD)"
PIPELINE="$REPO/$PIPELINE_REL"
UI="$REPO/$UI_REL"

python3 -m venv "$WORK/venv"
# shellcheck disable=SC1091
source "$WORK/venv/bin/activate"
pip install -q -r "$PIPELINE/requirements.txt"

cd "$PIPELINE"

if [ -n "$DOCS_DIR" ]; then
  echo "== Stage 1/1.5: extract + lint from $DOCS_DIR (reports only, drafts are not built)"
  python - "$DOCS_DIR" <<'PY' | while IFS='|' read -r id name domain template docx; do
import sys, yaml
from pathlib import Path
docs = Path(sys.argv[1])
for i in yaml.safe_load(open("interfaces.manifest.yaml"))["interfaces"]:
    f = docs / i["sharepoint_path"].rsplit("/", 1)[-1]
    if f.is_file():
        print(f'{i["id"]}|{i["name"]}|{i["domain"]}|{i["template"]}|{f}')
PY
    case "$template" in
      json) python scripts/extract_interface_from_docx.py "$docx" --id "$id" --name "$name" --out-dir "domains/$domain" ;;
      xml)  python scripts/extract_interface_from_docx_xml.py "$docx" --id "$id" --name "$name" --out-dir "domains/$domain" ;;
    esac
    # Exit 1 = blocking findings in the vendor document: a result, not a failure.
    python scripts/lint_source_document.py "$docx" --out-dir "domains/$domain" || true
  done
fi

echo "== Stage 3: validate"
python scripts/validate_all.py
echo "== Stage 4: compile"
python scripts/compile_knowledge_hub.py --out "$UI/src/data/exampleData.js"
echo "== Stage 4b: OpenAPI"
python scripts/generate_openapi.py --out-dir "$UI/public/openapi"

echo "== Stage 5: build UI"
cd "$UI"
npm ci
npm run lint
npm run build

echo "== Deploy"
bash "$REPO/deploy/deploy.sh" "$ENV_NAME" "$VARIANT" "$UI/dist" "$SHA"
