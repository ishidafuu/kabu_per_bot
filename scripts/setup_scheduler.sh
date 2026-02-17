#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

PROJECT_ID="${PROJECT_ID:-${FIRESTORE_PROJECT_ID:-}}"
REGION="${REGION:-asia-northeast1}"
SCHEDULER_LOCATION="${SCHEDULER_LOCATION:-${REGION}}"
TIME_ZONE="${TIME_ZONE:-Asia/Tokyo}"

ARTIFACT_REPO="${ARTIFACT_REPO:-kabu-bot}"
IMAGE_NAME="${IMAGE_NAME:-kabu-per-bot}"
IMAGE_URI="${IMAGE_URI:-}"
SKIP_BUILD=false

RUNTIME_SA_NAME="${RUNTIME_SA_NAME:-kabu-job-runtime}"
SCHEDULER_SA_NAME="${SCHEDULER_SA_NAME:-kabu-scheduler-invoker}"
SECRET_NAME="${SECRET_NAME:-discord-webhook-url}"

DAILY_JOB_NAME="${DAILY_JOB_NAME:-kabu-daily}"
DAILY_AT21_JOB_NAME="${DAILY_AT21_JOB_NAME:-kabu-daily-at21}"
EARNINGS_WEEKLY_JOB_NAME="${EARNINGS_WEEKLY_JOB_NAME:-kabu-earnings-weekly}"
EARNINGS_TOMORROW_JOB_NAME="${EARNINGS_TOMORROW_JOB_NAME:-kabu-earnings-tomorrow}"

DAILY_SCHEDULER_NAME="${DAILY_SCHEDULER_NAME:-sc-kabu-daily}"
DAILY_AT21_SCHEDULER_NAME="${DAILY_AT21_SCHEDULER_NAME:-sc-kabu-daily-at21}"
WEEKLY_SCHEDULER_NAME="${WEEKLY_SCHEDULER_NAME:-sc-kabu-earnings-weekly}"
TOMORROW_SCHEDULER_NAME="${TOMORROW_SCHEDULER_NAME:-sc-kabu-earnings-tomorrow}"

DAILY_CRON="${DAILY_CRON:-0 18 * * 1-5}"
DAILY_AT21_CRON="${DAILY_AT21_CRON:-5 21 * * 1-5}"
WEEKLY_CRON="${WEEKLY_CRON:-0 21 * * 6}"
TOMORROW_CRON="${TOMORROW_CRON:-0 21 * * *}"

WINDOW_1W_DAYS="${WINDOW_1W_DAYS:-5}"
WINDOW_3M_DAYS="${WINDOW_3M_DAYS:-63}"
WINDOW_1Y_DAYS="${WINDOW_1Y_DAYS:-252}"
COOLDOWN_HOURS="${COOLDOWN_HOURS:-2}"

log_info() {
  printf '[INFO] %s\n' "$1"
}

log_warn() {
  printf '[WARN] %s\n' "$1"
}

log_error() {
  printf '[ERROR] %s\n' "$1" >&2
}

usage() {
  cat <<'EOF'
Cloud Run Jobs + Cloud Scheduler の初期セットアップを一括実行します。

使い方:
  bash scripts/setup_scheduler.sh [options]

主なオプション:
  --project-id <id>            GCPプロジェクトID（未指定時は環境変数 PROJECT_ID / FIRESTORE_PROJECT_ID）
  --region <region>            Cloud Runリージョン（既定: asia-northeast1）
  --scheduler-location <loc>   Cloud Schedulerリージョン（既定: regionと同じ）
  --image-uri <uri>            既存のコンテナイメージURIを利用（指定時はビルドしない）
  --skip-build                 イメージビルドをスキップ（--image-uri 必須）
  --daily-cron "<cron>"        日次ジョブのcron（既定: 0 18 * * 1-5）
  --daily-at21-cron "<cron>"   21時日次ジョブのcron（既定: 5 21 * * 1-5）
  --weekly-cron "<cron>"       週次決算ジョブのcron（既定: 0 21 * * 6）
  --tomorrow-cron "<cron>"     翌日決算ジョブのcron（既定: 0 21 * * *）
  --time-zone <tz>             タイムゾーン（既定: Asia/Tokyo）
  --help                       ヘルプ表示

補足:
  - DISCORD_WEBHOOK_URL が環境変数にある場合、Secretの最新バージョンとして登録します。
  - DISCORD_WEBHOOK_URL が無い場合は Secret の既存バージョンを利用します。
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    log_error "必要コマンドが見つかりません: ${cmd}"
    exit 1
  fi
}

read_dotenv_value() {
  local key="$1"
  local dotenv_file="$2"
  if [ ! -f "${dotenv_file}" ]; then
    printf ''
    return
  fi
  local line
  line="$(grep -E "^${key}=" "${dotenv_file}" | tail -n 1 || true)"
  if [ -z "${line}" ]; then
    printf ''
    return
  fi
  local value="${line#*=}"
  value="${value#\"}"
  value="${value%\"}"
  value="${value#\'}"
  value="${value%\'}"
  printf '%s' "${value}"
}

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --project-id)
        PROJECT_ID="$2"
        shift 2
        ;;
      --region)
        REGION="$2"
        shift 2
        ;;
      --scheduler-location)
        SCHEDULER_LOCATION="$2"
        shift 2
        ;;
      --time-zone)
        TIME_ZONE="$2"
        shift 2
        ;;
      --image-uri)
        IMAGE_URI="$2"
        shift 2
        ;;
      --skip-build)
        SKIP_BUILD=true
        shift
        ;;
      --daily-cron)
        DAILY_CRON="$2"
        shift 2
        ;;
      --daily-at21-cron)
        DAILY_AT21_CRON="$2"
        shift 2
        ;;
      --weekly-cron)
        WEEKLY_CRON="$2"
        shift 2
        ;;
      --tomorrow-cron)
        TOMORROW_CRON="$2"
        shift 2
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        log_error "不明な引数: $1"
        usage
        exit 1
        ;;
    esac
  done
}

enable_required_apis() {
  log_info "必要APIを有効化します"
  gcloud services enable \
    run.googleapis.com \
    cloudscheduler.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    secretmanager.googleapis.com \
    firestore.googleapis.com \
    iam.googleapis.com \
    --project "${PROJECT_ID}" >/dev/null
}

ensure_service_account() {
  local name="$1"
  local display_name="$2"
  local email="${name}@${PROJECT_ID}.iam.gserviceaccount.com"
  if gcloud iam service-accounts describe "${email}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    log_info "サービスアカウントは既存です: ${email}"
    return
  fi
  log_info "サービスアカウントを作成します: ${email}"
  gcloud iam service-accounts create "${name}" \
    --display-name "${display_name}" \
    --project "${PROJECT_ID}" >/dev/null
}

grant_project_role() {
  local member="$1"
  local role="$2"
  log_info "IAMロール付与: ${member} -> ${role}"
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member "${member}" \
    --role "${role}" \
    --quiet >/dev/null
}

ensure_secret() {
  if gcloud secrets describe "${SECRET_NAME}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    log_info "Secretは既存です: ${SECRET_NAME}"
  else
    log_info "Secretを作成します: ${SECRET_NAME}"
    gcloud secrets create "${SECRET_NAME}" \
      --replication-policy "automatic" \
      --project "${PROJECT_ID}" >/dev/null
  fi

  if [ -n "${DISCORD_WEBHOOK_URL:-}" ]; then
    log_info "環境変数 DISCORD_WEBHOOK_URL を Secret に追加します"
    printf '%s' "${DISCORD_WEBHOOK_URL}" | \
      gcloud secrets versions add "${SECRET_NAME}" \
        --data-file=- \
        --project "${PROJECT_ID}" >/dev/null
  else
    log_warn "DISCORD_WEBHOOK_URL が未設定です。Secretの既存バージョンを利用します。"
  fi

  local version_count
  version_count="$(gcloud secrets versions list "${SECRET_NAME}" \
    --project "${PROJECT_ID}" \
    --format='value(name)' 2>/dev/null | wc -l | tr -d ' ')"
  if [ "${version_count}" = "0" ]; then
    log_error "Secret ${SECRET_NAME} にバージョンがありません。DISCORD_WEBHOOK_URL を設定して再実行してください。"
    exit 1
  fi
}

ensure_artifact_repo() {
  if gcloud artifacts repositories describe "${ARTIFACT_REPO}" \
    --location "${REGION}" \
    --project "${PROJECT_ID}" >/dev/null 2>&1; then
    log_info "Artifact Registryリポジトリは既存です: ${ARTIFACT_REPO}"
    return
  fi
  log_info "Artifact Registryリポジトリを作成します: ${ARTIFACT_REPO}"
  gcloud artifacts repositories create "${ARTIFACT_REPO}" \
    --repository-format "docker" \
    --location "${REGION}" \
    --description "kabu_per_bot images" \
    --project "${PROJECT_ID}" >/dev/null
}

build_image_if_needed() {
  if [ -n "${IMAGE_URI}" ]; then
    log_info "指定イメージを利用します: ${IMAGE_URI}"
    return
  fi

  if [ "${SKIP_BUILD}" = true ]; then
    log_error "--skip-build 指定時は --image-uri が必須です。"
    exit 1
  fi

  local dockerfile_path="${ROOT_DIR}/Dockerfile.job"
  if [ ! -f "${dockerfile_path}" ]; then
    log_error "Dockerfileが見つかりません: ${dockerfile_path}"
    exit 1
  fi

  ensure_artifact_repo
  IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${IMAGE_NAME}:$(date +%Y%m%d-%H%M%S)"
  log_info "Cloud Buildでイメージを作成します: ${IMAGE_URI}"
  local build_config
  build_config="$(mktemp)"
  cat > "${build_config}" <<'EOF'
steps:
  - name: gcr.io/cloud-builders/docker
    args:
      - build
      - -f
      - Dockerfile.job
      - -t
      - ${_IMAGE_URI}
      - .
images:
  - ${_IMAGE_URI}
EOF

  gcloud builds submit "${ROOT_DIR}" \
    --project "${PROJECT_ID}" \
    --config "${build_config}" \
    --substitutions "_IMAGE_URI=${IMAGE_URI}" >/dev/null
  rm -f "${build_config}"
}

upsert_run_job() {
  local job_name="$1"
  local args_csv="$2"
  local env_csv="$3"
  local runtime_sa_email="$4"

  local action="create"
  if gcloud run jobs describe "${job_name}" --region "${REGION}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    action="update"
  fi

  log_info "Cloud Run Job ${action}: ${job_name}"
  gcloud run jobs "${action}" "${job_name}" \
    --image "${IMAGE_URI}" \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --service-account "${runtime_sa_email}" \
    --command "python" \
    --args "${args_csv}" \
    --set-env-vars "${env_csv}" \
    --set-secrets "DISCORD_WEBHOOK_URL=${SECRET_NAME}:latest" \
    --task-timeout "1800s" \
    --max-retries "1" >/dev/null
}

upsert_scheduler_job() {
  local scheduler_name="$1"
  local cron_expr="$2"
  local target_job="$3"
  local scheduler_sa_email="$4"
  local uri="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${target_job}:run"

  local action="create"
  if gcloud scheduler jobs describe "${scheduler_name}" \
    --location "${SCHEDULER_LOCATION}" \
    --project "${PROJECT_ID}" >/dev/null 2>&1; then
    action="update"
  fi

  local header_flag="--headers"
  if [ "${action}" = "update" ]; then
    header_flag="--update-headers"
  fi

  log_info "Cloud Scheduler ${action}: ${scheduler_name} (${cron_expr})"
  gcloud scheduler jobs "${action}" http "${scheduler_name}" \
    --location "${SCHEDULER_LOCATION}" \
    --project "${PROJECT_ID}" \
    --schedule "${cron_expr}" \
    --time-zone "${TIME_ZONE}" \
    --uri "${uri}" \
    --http-method "POST" \
    "${header_flag}" "Content-Type=application/json" \
    --message-body "{}" \
    --oauth-service-account-email "${scheduler_sa_email}" \
    --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform" >/dev/null
}

main() {
  parse_args "$@"

  if [ -z "${PROJECT_ID}" ]; then
    PROJECT_ID="$(read_dotenv_value "FIRESTORE_PROJECT_ID" "${ROOT_DIR}/.env")"
  fi
  if [ -z "${PROJECT_ID}" ]; then
    log_error "PROJECT_ID が未設定です。--project-id を指定してください。"
    exit 1
  fi

  require_cmd "gcloud"
  gcloud config set project "${PROJECT_ID}" >/dev/null

  local runtime_sa_email="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
  local scheduler_sa_email="${SCHEDULER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

  enable_required_apis
  ensure_service_account "${RUNTIME_SA_NAME}" "kabu per bot runtime"
  ensure_service_account "${SCHEDULER_SA_NAME}" "kabu scheduler invoker"

  grant_project_role "serviceAccount:${runtime_sa_email}" "roles/datastore.user"
  grant_project_role "serviceAccount:${runtime_sa_email}" "roles/secretmanager.secretAccessor"
  grant_project_role "serviceAccount:${scheduler_sa_email}" "roles/run.invoker"

  ensure_secret
  build_image_if_needed

  local common_env="PYTHONPATH=/app/src,FIRESTORE_PROJECT_ID=${PROJECT_ID},APP_TIMEZONE=${TIME_ZONE},COOLDOWN_HOURS=${COOLDOWN_HOURS}"
  local daily_env="${common_env},WINDOW_1W_DAYS=${WINDOW_1W_DAYS},WINDOW_3M_DAYS=${WINDOW_3M_DAYS},WINDOW_1Y_DAYS=${WINDOW_1Y_DAYS}"

  upsert_run_job "${DAILY_JOB_NAME}" "scripts/run_daily_job.py,--execution-mode,daily" "${daily_env}" "${runtime_sa_email}"
  upsert_run_job "${DAILY_AT21_JOB_NAME}" "scripts/run_daily_job.py,--execution-mode,at_21" "${daily_env}" "${runtime_sa_email}"
  upsert_run_job "${EARNINGS_WEEKLY_JOB_NAME}" "scripts/run_earnings_job.py,--job,weekly" "${common_env}" "${runtime_sa_email}"
  upsert_run_job "${EARNINGS_TOMORROW_JOB_NAME}" "scripts/run_earnings_job.py,--job,tomorrow" "${common_env}" "${runtime_sa_email}"

  upsert_scheduler_job "${DAILY_SCHEDULER_NAME}" "${DAILY_CRON}" "${DAILY_JOB_NAME}" "${scheduler_sa_email}"
  upsert_scheduler_job "${DAILY_AT21_SCHEDULER_NAME}" "${DAILY_AT21_CRON}" "${DAILY_AT21_JOB_NAME}" "${scheduler_sa_email}"
  upsert_scheduler_job "${WEEKLY_SCHEDULER_NAME}" "${WEEKLY_CRON}" "${EARNINGS_WEEKLY_JOB_NAME}" "${scheduler_sa_email}"
  upsert_scheduler_job "${TOMORROW_SCHEDULER_NAME}" "${TOMORROW_CRON}" "${EARNINGS_TOMORROW_JOB_NAME}" "${scheduler_sa_email}"

  cat <<EOF

[DONE] セットアップが完了しました。
  project: ${PROJECT_ID}
  region: ${REGION}
  image: ${IMAGE_URI}

確認コマンド:
  gcloud run jobs executions list --job=${DAILY_JOB_NAME} --region=${REGION} --project=${PROJECT_ID}
  gcloud run jobs executions list --job=${DAILY_AT21_JOB_NAME} --region=${REGION} --project=${PROJECT_ID}
  gcloud scheduler jobs list --location=${SCHEDULER_LOCATION} --project=${PROJECT_ID}
  gcloud scheduler jobs run ${DAILY_SCHEDULER_NAME} --location=${SCHEDULER_LOCATION} --project=${PROJECT_ID}
  gcloud scheduler jobs run ${DAILY_AT21_SCHEDULER_NAME} --location=${SCHEDULER_LOCATION} --project=${PROJECT_ID}
EOF
}

main "$@"
