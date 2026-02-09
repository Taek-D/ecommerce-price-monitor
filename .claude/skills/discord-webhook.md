# Discord Webhook 알림 패턴

이 프로젝트에서 Discord webhook으로 알림을 보낼 때 참고할 패턴입니다.

## Embed 색상 코드

| 용도 | 색상 | 코드 |
|------|------|------|
| 가격 하락 | 초록 | `3066993` |
| 가격 상승 | 빨강 | `15158332` |
| 재입고 감지 | 초록 | `3066993` |
| 품절 감지 | 텍스트만 | embed 없음 |

## Embed 구조

```python
embeds = [{
    "title": f"{ad.name} 가격 변동 감지",
    "description": url,
    "color": color,
    "fields": [
        {"name": "필드명", "value": "값", "inline": True},  # 가로 배치
        {"name": "필드명", "value": "값", "inline": False}, # 세로 배치
    ]
}]
await post_webhook(webhook_url, "알림 내용", embeds=embeds)
```

## 알림 유형별 분기

| 이벤트 | 조건 | 알림 형태 |
|--------|------|-----------|
| 첫 등록 | `url not in state` + 가격 있음 | 일반 가격 변동 embed |
| 가격 변동 | `prev != curr` + 둘 다 int | 가격 변동 embed (이전/현재/변동) |
| 품절 감지 | `kind == "soldout"` + changed | 텍스트 알림 |
| 재입고 | `url in state` + `prev is None` + `curr is not None` | 재입고 전용 embed |

## Rate Limit 주의

- Discord webhook rate limit: 5 requests / 2 seconds (per webhook)
- URL 간 `asyncio.sleep(1.0)` 딜레이로 자연스럽게 제한
- 동시에 많은 알림 발생 시 429 에러 가능
