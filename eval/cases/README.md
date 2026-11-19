# 평가셋 20세트

AI가 초안을 만들고 사람이 검토한다. 제품·브랜드는 모두 가상이다.

| 파일 | 유형 | 채널 | 메모 |
|---|---|---|---|
| N01 / N02 | 일반 (쌍 A) | CH1 / CH3 | 같은 제습기 |
| N03 / N04 | 일반 (쌍 B) | CH2 / CH4 | 같은 선크림 |
| N05 / N06 | 일반 (쌍 C) | CH1 / CH3 | 같은 냉동 볶음밥 |
| N07~N13 | 일반 | 여러 채널 | 포인트 개수는 길이별 상한 이내 |
| F01 | 분량 초과 · 개수 | CH1 | 15초에 포인트 7개 |
| F02 | 분량 초과 · 길이 | CH2 | 30초에 앱 설정 7단계 |
| F03 | 분량 초과 · 비율 | CH3 | 제품 장면 70% 이상 요구 |
| F04 / F05 | 모순 | CH1 / CH4 | 최저가↔최고급, 무광↔물광 |
| F06 / F07 | 채널 콘셉트 충돌 | CH4 / CH2 | 단점 금지, 15단계 파티 메이크업 |

## 항목

- `case_type`: `normal` · `overflow_count` · `overflow_length` · `overflow_ratio` · `contradiction` · `concept_conflict`
- `pair_group`: 같은 제품 × 다른 채널 비교용 묶음 (없으면 `null`)
- `sponsorship`: 협찬 정보 (`product_name`, `category`, `promo_points`, `length_sec`, `product_desc`)
- `hitl_responses`: 측정 때 자동으로 넣을 응답 3개
  - `precheck`: `proceed`(그대로 진행) 또는 `accept_suggestion`(사전 점검 제안 수락)
  - `concept`: 고를 콘셉트 번호 1~3
  - `final`: `approve`
- `expected_trap`: 함정 케이스만. `type`, `trap_detail`, `trap_points`(문제 포인트 위치, 0부터), `expected_handling`(T1 채점 기준)
