# 배포 구성과 운영

2026-09-13 KST 확인. 웹 서비스는 Cloud Run 서울 리전, 모델은 Vertex AI의 global 엔드포인트를 사용합니다. 전체 모델 처리가 서울에 한정된다는 의미는 아닙니다.

| 항목 | 확인한 값 |
|---|---|
| 프로젝트 | project-462d529a-f067-4a26-bbb |
| 서비스 URL | https://examflow-922216333816.asia-northeast3.run.app |
| 리전 | asia-northeast3 |
| 최종 리비전 / 트래픽 | examflow-00005-szb / 100% |
| 최종 빌드 | a1756237-408a-4016-baa3-04ee8775dbce |
| 이미지 SHA256 | ee7841f5989bcef6a3f06d0c0688cd061ac234748e68c9ef4519cf497f059f69 |
| 모델 | Gemini 2.5 Flash |
| CPU / 메모리 | 1 vCPU / 1 GiB |
| 서비스 인스턴스 | 최소 0 / 최대 1 |
| 동시 HTTP 요청 / 타임아웃 | 8 / 240초 |
| CPU / 세션 | 요청 외 CPU 사용 허용 / session affinity 활성화 |

최대 1은 서비스 수준 `run.googleapis.com/maxScale=1`입니다. 별도 리비전 기본 maxScale 값은 3이며 서비스 한도를 함께 적용합니다. 비용의 절대 상한이나 교체 순간의 원자적 단일 인스턴스 보장으로 해석하지 않습니다.

## 권한과 이미지

- `examflow-runtime`: `roles/aiplatform.user`, Cloud Run 기본 자격 증명으로 모델 호출.
- `examflow-build`: 소스 버킷 `roles/storage.objectViewer`, 전용 이미지 저장소 `roles/artifactregistry.writer`, 프로젝트 `roles/logging.logWriter`.
- 서비스 계정 키를 생성해 저장소에 넣지 않았습니다. 인증과 임시 자료는 Git·소스 업로드에서 제외했습니다.
- Docker는 UID 10001의 비루트 사용자로 실행합니다.

## 재배포 명령

해당 프로젝트 권한을 가진 Cloud CLI 인증 환경에서 실행합니다. 실제 리소스 비용이 발생합니다.

```bash
PROJECT=project-462d529a-f067-4a26-bbb
REGION=asia-northeast3
IMAGE=$REGION-docker.pkg.dev/$PROJECT/examflow/app:review
gcloud builds submit . --config=cloudbuild.yaml \
  --substitutions=_IMAGE=$IMAGE \
  --service-account=projects/$PROJECT/serviceAccounts/examflow-build@$PROJECT.iam.gserviceaccount.com \
  --project=$PROJECT --region=$REGION
gcloud run deploy examflow --image=$IMAGE --project=$PROJECT --region=$REGION \
  --service-account=examflow-runtime@$PROJECT.iam.gserviceaccount.com \
  --allow-unauthenticated --min=0 --max=1 --cpu=1 --memory=1Gi \
  --concurrency=8 --timeout=240 --no-cpu-throttling --session-affinity \
  --set-env-vars=MODEL_MODE=gemini,GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=global,GEMINI_MODEL=gemini-2.5-flash,DAILY_MODEL_CALL_LIMIT=120,COOKIE_SECURE=true,PUBLIC_BASE_URL=https://examflow-922216333816.asia-northeast3.run.app
```

최종 배포는 태그 대신 위 SHA256 digest를 지정했습니다. `python scripts/verify_deployment.py --base-url <URL>`로 배포 기능을 확인합니다.

## 롤백

이전 검증 리비전으로 트래픽을 되돌리는 명령입니다.

```bash
gcloud run services update-traffic examflow \
  --to-revisions=examflow-00004-fph=100 \
  --project=project-462d529a-f067-4a26-bbb --region=asia-northeast3
```

리비전 교체 때 데모 상태가 사라질 수 있으므로 브라우저에서 새 요청을 시작합니다.

## 비용과 영속성

승인된 무료 체험 크레딧 범위에서 운영하며 일반 유료 계정으로 전환하지 않았습니다. 최소 인스턴스 0·서비스 최대 1·세션당 시간당 20개 요청·동시 작업 4개·UTC 일일 모델 호출 120회를 제한합니다.

일일 카운터는 로컬 SQLite에 있어 재시작 시 초기화될 수 있습니다. 이 카운터나 예산 알림으로 지출을 강제 차단한다고 주장하지 않습니다. 빌드·이미지 보관·CPU·모델 비용은 각각 발생할 수 있고, 누적 실제 지출을 측정한 금액은 제시하지 않습니다. 데모 확인이 끝나면 운영 지속 여부를 결정해야 합니다.

요청은 메모리, 예약은 임시 파일시스템에 저장합니다. 영구 보존과 다중 인스턴스 운영에는 외부 DB·작업 큐·공유 비용 카운터·담당자 인증이 필요합니다.
