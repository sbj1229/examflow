# 현재 상태

- 목표: ExamFlow — 검사 예약 준비 확인 및 일정 조정.
- 새 프로젝트로 착수. 기존 프로젝트 코드·산출물 재사용 없음.
- 설계: 준비 확인 / 일정 조정 에이전트, A2A HTTP, 독립 MCP stdio 서버, Gemini 구조화 출력, 승인 후 합성 예약 확정.
- 2026-09-12 KST: 구현·공개 배포·문서화·기능 검증·발표자료 제작 및 검토 완료.
- Google Cloud 지정 계정과 무료 체험 크레딧 잔액 확인. 일반 유료 계정 활성화 안 함.
- 공개 저장소: https://github.com/sbj1229/examflow
- 공개 데모: https://examflow-922216333816.asia-northeast3.run.app
- 최종 배포: examflow-00004-fph, 실제 Gemini 모드.
- 자동 테스트 18개 통과. 로컬 실제 Gemini 4개 사례와 최종 공개 배포 3개 업무 사례를 별도 검증.
- 7장 PPTX·발표자 노트·대본 완료. 최종 PPTX 재가져오기 및 전 페이지 시각 검토 완료.
- Antigravity 패키지와 호출 스크립트 검증 완료. IDE 자체의 자동 발견 검증은 미수행.
- 상세 근거 및 한계: [검증 기록](verification.md), [요구사항 대응](review.md), [배포 구성](deployment.md).
