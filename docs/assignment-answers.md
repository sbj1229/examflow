# 과제 요구사항에 대한 질문과 구현 답변

과제 원문의 요구사항별로 제출물을 검토할 때 나올 질문을 정리하고, 설계 이유·실제 구현·확인 방법을 연결했습니다.

## 왜 검사 예약 전 행정 확인을 선택했는가?

의뢰서·연락처·사전 확인표의 접수 여부와 검사실 일정을 각각 조회해야 하는 업무로 범위를 정했습니다. 결과가 단순 답변으로 끝나지 않고, 근거 확인 → 일정 제안 → 담당자 승인 → 기록으로 이어져 에이전트 협업과 도구 사용을 확인할 수 있기 때문입니다. 실제 병원 관찰로 측정한 절감 시간은 없으며, 합성 데이터와 시연용 규칙으로 구현했습니다.

## 두 에이전트가 필요한가? 단일 함수와 무엇이 다른가?

준비 확인은 의뢰·행정 규칙을 근거로 접수 상태와 시간 선호를 반환합니다. 일정 조정은 가용 시간·전달된 선호를 근거로 후보를 선택합니다. 준비 상태가 미완료면 일정 조정을 호출하지 않습니다. 코드 경계는 app/agents.py의 readiness·scheduling, 입력 계약은 app/contracts.py의 AgentJob입니다.

이 작은 합성 사례만 처리한다면 단일 규칙 함수도 가능합니다. 두 역할로 나눈 목적은 과제의 협업 요구를 실제 통신 계약으로 구현하고, 각 역할의 프롬프트·근거·검증 규칙을 독립적으로 점검하기 위해서입니다. 서비스는 하나로 배포하며, 서로 자율 협상하는 구조가 아니라 조정기가 결과를 전달하는 순차 협업입니다.

## A2A와 MCP는 이름만 붙인 호출이 아닌가?

app/main.py의 call_agent는 JSON-RPC message/send를 HTTP로 전송합니다. 공식 A2A SDK 서버가 Task와 Artifact를 반환하며 UI에 Task ID와 상태가 기록됩니다. 준비 확인의 preference가 다음 AgentJob에 전달됩니다.

app/tools_client.py는 독립 Python 프로세스로 MCP 서버를 시작하고 공식 ClientSession의 initialize·call_tool을 사용합니다. 도구는 get_order, get_preparation_policy, find_slots, reserve_demo_slot 네 개입니다. UI에서 mcp.call과 mcp.result를 펼쳐 실제 인수와 결과를 확인할 수 있습니다. 호출 이벤트는 비공개 모델 추론을 의미하지 않습니다.

EX-1001은 두 A2A 응답을, EX-1002는 한 응답만 남기는 것으로 협업 분기를 확인할 수 있습니다. tests/test_system.py 및 scripts/verify_deployment.py가 이 차이를 검증합니다.

## 어떤 판단을 LLM에 맡겼고 어떤 것은 코드가 책임지는가?

Gemini는 자연어 요청의 오전·오후 선호 해석, 조회 근거 설명, 허용 후보 선택을 맡습니다. 코드는 원본 필드와 ready·missing_fields를 대조하고 slot_id가 후보에 실제로 있는지 확인합니다. 승인·버전·세션 소유권·DB의 예약 충돌은 모델 판단으로 우회하지 않습니다.

현재 합성 후보가 적어 모델 선택의 어려움은 제한적입니다. 모델의 복잡한 일정 최적화나 전체 병원 업무 계획 능력을 입증했다고 주장하지 않습니다. 이 데모에서 확인한 것은 실제 모델 호출을 포함한 협업 계약과 그 출력의 검증 경계입니다.

## 담당자가 확인한 예약안과 실제 승인 대상이 같은가?

웹은 승인·취소 처리 중 새 요청과 중복 조작을 막고, 요청 세대를 대조해 이전 폴링 응답이 현재 상태를 덮어쓰지 않게 했습니다. 응답 유실 시에도 같은 실행을 조회합니다. tests/test_ui.cjs의 세 가지 지연·실패 시나리오로 확인합니다.

스킬은 조회 결과를 상태 파일에 보관하고 승인 시 같은 세션과 run ID를 사용합니다. 별도 프로세스 두 번으로 조회·승인하고 다시 승인해도 원래 run만 사용되는지 Python 테스트로 검증합니다. 처음부터 --approve만 붙여 새 예약안을 자동 확정하는 경로는 허용하지 않습니다.

## 실패해도 성공으로 보이지 않는가?

서류 누락은 needs_input, 빈 후보는 no_slots, 예약 중복은 conflict입니다. 모델 형식 오류는 한 번만 재시도하고, 근거 불일치는 실패로 종료합니다. 실제 모델 장애 시 fixture 결과로 대체하지 않습니다. 예약 DB 기록 후 응답이 유실되면 confirmation_unknown을 표시하고 같은 실행으로 재확인합니다. 취소는 이후 작업과 확정을 막으며 이미 전송한 외부 계산을 원격 중단하지는 않습니다.

## Antigravity 시연

공식 스킬 문서의 workspace 위치인 .agents/skills/examflow 아래에 skills/examflow 패키지를 복사합니다. 기존 동명 폴더를 덮어쓰지 않습니다. 저장소 원본의 SKILL.md와 scripts도 함께 제출합니다. [공식 스킬 문서](https://antigravity.google/docs/skills).

Antigravity에서 프로젝트를 연 뒤 다음과 같이 요청합니다.

> ExamFlow 스킬로 EX-1001의 오후 예약안을 조회하고, 의뢰와 제안 시간 및 근거를 보여줘. 내가 승인하기 전에는 확정하지 마.

스킬이 수행할 명령:

```bash
python skills/examflow/scripts/invoke.py --base-url https://examflow-922216333816.asia-northeast3.run.app --order EX-1001 --request "오후 예약" --state-file .tmp/antigravity-proposal.json
```

표시된 예약안을 확인한 뒤:

> 방금 제시한 예약안을 확정해. 저장한 세션과 실행 번호를 그대로 사용해.

```bash
python skills/examflow/scripts/invoke.py --base-url https://examflow-922216333816.asia-northeast3.run.app --resume --approve --state-file .tmp/antigravity-proposal.json
```

상태 파일은 쿠키를 포함하므로 공유하지 않습니다. 복사한 패키지만 사용하는 환경에서는 스크립트 경로를 해당 SKILL.md 옆 scripts/invoke.py로 바꿉니다. 현재 검증은 패키지 형식과 호출 스크립트 실행까지이며 Antigravity IDE/CLI 자체의 자동 발견은 미검증입니다.

## 평가자가 어떤 순서로 확인하면 되는가?

1. README에서 공개 데모를 열어 EX-1001 오후 요청을 실행합니다. Task ID·도구 근거·제안 시간을 확인한 후 승인합니다.
2. EX-1002로 누락 상태와 일정 단계 미실행을, EX-1003으로 빈 후보를 확인합니다.
3. 로컬에서는 requirements-dev.txt 설치 후 pytest와 node --test tests/test_ui.cjs를 실행합니다. Node는 UI 회귀 검사에만 필요하며 서비스 실행 의존성은 아닙니다.
4. 실제 모델을 검증하려면 표준 ADC와 본인 프로젝트로 scripts/live_smoke.py를 실행합니다. 공개 서비스용 verify_deployment.py도 제공합니다.
5. 위 Antigravity 시연과 발표자료를 확인합니다. 공개 저장소에서 필수 파일이 열리는 것까지 확인해야 제출이 완료됩니다.

## 운영 서비스와 어디까지 다른가?

Cloud Run 단일 서비스와 휘발성 저장소를 사용한 공개 데모입니다. 로그인 기반 담당자 권한, 영구 DB, 작업 큐, 병원 시스템 연동, 실제 임상 효과는 구현·검증하지 않았습니다. 다음 단계는 이 항목들과 외부 영속 비용 카운터입니다. 배포 리전·서비스 계정·비용 제한·롤백은 deployment.md에 기록했습니다.
