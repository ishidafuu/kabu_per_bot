#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WEB_DIR="${ROOT_DIR}/web"
ROOT_ENV_FILE="${ROOT_DIR}/.env"
WEB_ENV_FILE="${WEB_DIR}/.env.local"

failures=0
warnings=0

log_info() {
  printf '[INFO] %s\n' "$1"
}

log_warn() {
  printf '[WARN] %s\n' "$1"
}

log_error() {
  printf '[ERROR] %s\n' "$1"
}

increment_failure() {
  failures=$((failures + 1))
}

increment_warning() {
  warnings=$((warnings + 1))
}

check_command() {
  local cmd="$1"
  if command -v "${cmd}" >/dev/null 2>&1; then
    log_info "Found command: ${cmd}"
  else
    log_error "Missing required command: ${cmd}"
    increment_failure
  fi
}

strip_quotes() {
  local raw="$1"
  raw="${raw#\"}"
  raw="${raw%\"}"
  raw="${raw#\'}"
  raw="${raw%\'}"
  printf '%s' "${raw}"
}

get_var_value() {
  local key="$1"
  local env_file="$2"
  local value=""

  if [ -n "${!key-}" ]; then
    printf '%s' "${!key}"
    return
  fi

  if [ -f "${env_file}" ]; then
    local line
    line="$(grep -E "^${key}=" "${env_file}" | tail -n 1 || true)"
    if [ -n "${line}" ]; then
      value="${line#*=}"
      strip_quotes "${value}"
      return
    fi
  fi

  printf ''
}

is_missing_or_placeholder() {
  local value="$1"
  if [ -z "${value}" ]; then
    return 0
  fi

  case "${value}" in
    your-gcp-project-id|your-*|changeme|*\<*|*example.com*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

warn_if_missing() {
  local key="$1"
  local env_file="$2"
  local value
  value="$(get_var_value "${key}" "${env_file}")"
  if is_missing_or_placeholder "${value}"; then
    log_warn "Environment value is missing or placeholder: ${key} (${env_file})"
    increment_warning
  else
    log_info "Environment value looks set: ${key}"
  fi
}

log_info "Preflight deploy checks started"
log_info "Repository root: ${ROOT_DIR}"

if command -v python >/dev/null 2>&1; then
  log_info "Found command: python"
elif command -v python3 >/dev/null 2>&1; then
  log_warn "python command not found. python3 is available."
  increment_warning
else
  log_error "Missing required command: python or python3"
  increment_failure
fi

check_command "node"
check_command "npm"
check_command "git"

if [ ! -f "${ROOT_ENV_FILE}" ]; then
  log_warn "Root env file not found: ${ROOT_ENV_FILE}"
  increment_warning
fi
if [ ! -f "${WEB_ENV_FILE}" ]; then
  log_warn "Web env file not found: ${WEB_ENV_FILE}"
  increment_warning
fi

warn_if_missing "FIRESTORE_PROJECT_ID" "${ROOT_ENV_FILE}"
warn_if_missing "DISCORD_WEBHOOK_URL" "${ROOT_ENV_FILE}"
warn_if_missing "VITE_API_BASE_URL" "${WEB_ENV_FILE}"
warn_if_missing "VITE_USE_MOCK_API" "${WEB_ENV_FILE}"
warn_if_missing "VITE_USE_MOCK_AUTH" "${WEB_ENV_FILE}"

use_mock_auth="$(get_var_value "VITE_USE_MOCK_AUTH" "${WEB_ENV_FILE}")"
if [ "${use_mock_auth}" = "false" ]; then
  warn_if_missing "VITE_FIREBASE_API_KEY" "${WEB_ENV_FILE}"
  warn_if_missing "VITE_FIREBASE_AUTH_DOMAIN" "${WEB_ENV_FILE}"
  warn_if_missing "VITE_FIREBASE_PROJECT_ID" "${WEB_ENV_FILE}"
  warn_if_missing "VITE_FIREBASE_APP_ID" "${WEB_ENV_FILE}"
fi

if [ -d "${WEB_DIR}" ]; then
  log_info "Running web build check: npm run build"
  if (cd "${WEB_DIR}" && npm run build); then
    log_info "Web build succeeded"
  else
    log_error "Web build failed"
    increment_failure
  fi
else
  log_error "Web directory not found: ${WEB_DIR}"
  increment_failure
fi

log_info "Summary: failures=${failures}, warnings=${warnings}"

if [ "${failures}" -gt 0 ]; then
  exit 1
fi

exit 0
