#!/usr/bin/env bash
# ==============================================================================
# Veratum Installer — Universal AI Engineering Harness
# https://github.com/yadavmandeep/Veratum
# ==============================================================================
set -e

BOLD="\033[1m"
GREEN="\033[32m"
CYAN="\033[36m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

echo -e "${CYAN}${BOLD}"
cat << 'EOF'
 __     __               _                 
 \ \   / /__ _ __  __ _ | |_ _  _ _ __ ___ 
  \ \ / / _ \ '__|/ _` || __| || | '_ ` _ \
   \ V /  __/ |  | (_| || |_| || | | | | | |
    \_/ \___|_|   \__,_| \__|\_,_|_| |_| |_|
EOF
echo -e "${RESET}${BOLD}Universal AI Engineering Harness, Skill & MCP Runtime${RESET}"
echo -e "${CYAN}https://github.com/yadavmandeep/Veratum${RESET}\n"

# 1. Detect Python 3.8+
echo -e "${BOLD}[1/4] Checking Python environment...${RESET}"
PYTHON_BIN=""
for py in python3 python py; do
    if command -v "$py" >/dev/null 2>&1; then
        if "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
            PYTHON_BIN="$py"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo -e "${RED}✗ Python 3.8+ is required but not found in PATH.${RESET}"
    echo "Please install Python from https://www.python.org and try again."
    exit 1
fi
PY_VERSION=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
echo -e "  ${GREEN}✓${RESET} Found Python ${PY_VERSION} (${PYTHON_BIN})"

# 2. Check Node.js / npx
echo -e "\n${BOLD}[2/4] Checking Node.js runtime...${RESET}"
if command -v npx >/dev/null 2>&1; then
    NODE_VERSION=$(node -v 2>/dev/null || echo "detected")
    echo -e "  ${GREEN}✓${RESET} Found Node.js (${NODE_VERSION}) & npx"
    USE_NPX=true
else
    echo -e "  ${YELLOW}!${RESET} npx not found. Will bootstrap directly via Python engine."
    USE_NPX=false
fi

# 3. Target directory and installation
TARGET_DIR="${1:-$(pwd)}"
echo -e "\n${BOLD}[3/4] Installing Veratum into:${RESET} ${TARGET_DIR}"

if [ "$USE_NPX" = true ]; then
    npx veratum init --dir "$TARGET_DIR" "$@"
else
    "$PYTHON_BIN" .veratum/engine/veratum_cli.py init --root "$TARGET_DIR"
fi

# 4. Diagnostic & Health Check
echo -e "\n${BOLD}[4/4] Verifying installation health...${RESET}"
if [ -f "$TARGET_DIR/.veratum/engine/veratum_cli.py" ]; then
    "$PYTHON_BIN" "$TARGET_DIR/.veratum/engine/veratum_cli.py" doctor --root "$TARGET_DIR"
else
    echo -e "  ${GREEN}✓${RESET} Skill installed successfully."
fi

echo -e "\n${GREEN}${BOLD}✨ Veratum setup completed successfully!${RESET}"
echo -e "Quickstart: Tell your agent ${BOLD}\"Use Veratum to work on this repo.\"${RESET}\n"
