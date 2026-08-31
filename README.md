# Chart Lab V0.1

Ellie chart lab 6개 수급 지표를 보존하면서 다음 기능을 추가한 Streamlit 실험 앱입니다.

- 키움 XLS/XLSX/CSV 업로드
- 캔들 차트 + MA5/20/60/120
- 가중 평균단가 밴드 표시
- 핵심 매물대 표시
- MARVEL 호환 수급 구조 6지표
- 가격 구조 점수(추세/돌파/지지/변동성/거래량 확인)
- 직전 봉 대비 지표 변화
- 실험 종합 구조 점수

## 실행

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
streamlit run app.py
```

## 주의

- 이 앱은 매수/매도 신호를 제공하는 목적이 아니라 차트 구조를 일관되게 점검하기 위한 보조 도구입니다.
- `실험 종합` 점수는 Chart Lab V0.1에서 추가된 임시 모델입니다. 백테스트와 검증 전에는 투자 의사결정의 단독 근거로 사용하지 마세요.
