"""시연 전용 합성 자료. 임상 준비 지침이나 실제 환자 자료가 아니다."""

ORDERS = {
    "EX-1001": {"id": "EX-1001", "alias": "가상 사례 A", "exam": "CT", "department": "영상검사실", "referral_received": True, "contact_verified": True, "checklist_received": True},
    "EX-1002": {"id": "EX-1002", "alias": "가상 사례 B", "exam": "MRI", "department": "영상검사실", "referral_received": True, "contact_verified": False, "checklist_received": False},
    "EX-1003": {"id": "EX-1003", "alias": "가상 사례 C", "exam": "US", "department": "초음파실", "referral_received": True, "contact_verified": True, "checklist_received": True},
}
POLICY = {"id": "DEMO-ADMIN-01", "version": "1.0", "source": "합성 병원 행정 운영 규칙", "required": ["referral_received", "contact_verified", "checklist_received"], "scope": "서류 접수 여부만 확인. 의학적 검사 적합성은 판단하지 않음."}
FIELD_LABELS = {"referral_received": "검사 의뢰서 접수", "contact_verified": "연락처 확인", "checklist_received": "담당 의료진의 사전 확인표 접수"}
SLOTS = [
    {"id": "CT-AM", "exam": "CT", "time": "09:30", "period": "morning", "room": "CT 1실", "day": "다음 운영일"},
    {"id": "CT-PM", "exam": "CT", "time": "14:00", "period": "afternoon", "room": "CT 1실", "day": "다음 운영일"},
    {"id": "MRI-AM", "exam": "MRI", "time": "10:00", "period": "morning", "room": "MRI 1실", "day": "다음 운영일"},
]
