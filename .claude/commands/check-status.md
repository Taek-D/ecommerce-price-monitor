# 봇 상태 확인

현재 봇의 설정 상태와 모니터링 현황을 요약합니다.

## 수행 절차

### 1. 설정 파일 확인

- `.env` 파일 존재 여부 (내용은 출력하지 않음)
- `safe/` 폴더 내 서비스 계정 키 존재 여부
- `price_state.json` 상태 파일 확인

### 2. price_state.json 분석

- 추적 중인 URL 수
- 각 URL의 마지막 가격
- 품절 상태인 URL 목록

### 3. 어댑터 현황

`musinsa_price_watch.py`에서 등록된 어댑터 목록과 각각의:
- 이름
- 매칭 프리픽스
- 웹훅 URL 설정 여부

### 4. 결과 출력

```
봇 상태 요약:
- 어댑터: X개 (전용 Y개 + UniversalAdapter)
- 추적 URL: Z개
- 품절 상태: N개
- 마지막 체크: {timestamp}
```
