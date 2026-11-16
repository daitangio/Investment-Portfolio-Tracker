#!/bin/bash
set -euo pipefail
SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd $SCRIPT_DIR/..
test -f requirements.txt && mv requirements.txt requirements.txt.old
uv pip compile --refresh requirements.in backend/requirements.txt > requirements.txt
test -f requirements.txt.old && diff requirements.txt.old requirements.txt ||  {     
    echo Ready to upgrade. Press enter to continue or ^C to stop
    read
    uv pip install --upgrade -r requirements.txt
}