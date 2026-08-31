import io
import math
from typing import Dict

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Chart Lab V0.1", layout="wide")

# -----------------------------
# Data loading
# -----------------------------
COL_MAP = {
    "날짜": "date", "일자": "date", "거래일": "date", "시간": "time",
    "시가": "open", "고가": "high", "저가": "low", "종가": "close", "현재가": "close",
    "거래량": "volume", "체결량": "volume", "거래대금": "value",
}


def read_uploaded(file) -> pd.DataFrame:
    name = (file.name or "").lower()
    b = file.getvalue()
    if name.endswith(".csv"):
        last = None
        for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
            try:
                return pd.read_csv(io.BytesIO(b), encoding=enc)
            except Exception as e:
                last = e
        raise ValueError(f"CSV를 읽지 못했습니다: {last}")
    if name.endswith(".xlsx"):
        return pd.read_excel(io.BytesIO(b), engine="openpyxl")
    if name.endswith(".xls"):
        return pd.read_excel(io.BytesIO(b), engine="xlrd")
    raise ValueError("xls/xlsx/csv 파일만 지원합니다.")


def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.rename(columns={c: COL_MAP.get(c, c) for c in df.columns})
    if "date" not in df.columns:
        df = df.rename(columns={df.columns[0]: "date"})
    for c in ["open", "high", "low", "close", "volume", "value"]:
        if c in df.columns:
            df[c] = pd.to_numeric(
                df[c].astype(str).str.replace(",", "", regex=False).str.replace(" ", "", regex=False),
                errors="coerce",
            )
    if "close" not in df.columns:
        raise ValueError("종가(close/종가/현재가) 컬럼이 필요합니다.")
    for c in ["open", "high", "low"]:
        if c not in df.columns:
            df[c] = df["close"]
    if "volume" not in df.columns:
        df["volume"] = 0.0
    if "value" not in df.columns:
        df["value"] = df["close"] * df["volume"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    return df[["date", "open", "high", "low", "close", "volume", "value"]]


def clamp_int(x: float, lo=0, hi=100) -> int:
    if pd.isna(x) or np.isinf(x):
        return 50
    return max(lo, min(hi, int(round(x))))

# -----------------------------
# MARVEL-compatible flow metrics
# (same conceptual formulas, made safer for short datasets)
# -----------------------------

def calc_avg_cost_band(df: pd.DataFrame, lookback=60) -> Dict:
    x = df.tail(min(lookback, len(df))).copy()
    w = x["value"].clip(lower=1.0)
    price = x["close"]
    wa = float((price * w).sum() / max(w.sum(), 1e-9))
    var = float((w * (price - wa) ** 2).sum() / max(w.sum(), 1e-9))
    sigma = math.sqrt(max(var, 0))
    current = float(df["close"].iloc[-1])
    lo, hi = wa - sigma, wa + sigma
    score = 30 if current < lo else 55 if current > hi else 75
    return {"name": "가중 평균단가 밴드", "score": score, "wa": wa, "band_low": lo, "band_high": hi}


def calc_supply_density(df: pd.DataFrame, lookback=120, bins=20) -> Dict:
    x = df.tail(min(lookback, len(df))).copy()
    pmin, pmax = float(x["close"].min()), float(x["close"].max())
    if pmin == pmax:
        return {"name": "구조적 매물대 밀도", "score": 50, "zone": (pmin, pmax)}
    edges = np.linspace(pmin, pmax, bins + 1)
    bucket = pd.cut(x["close"], bins=edges, include_lowest=True)
    by = x["value"].groupby(bucket, observed=False).sum().sort_values(ascending=False)
    top = by.index[0]
    zone_low, zone_high = float(top.left), float(top.right)
    current = float(df["close"].iloc[-1])
    if zone_low <= current <= zone_high:
        score = 45
    else:
        dist = (zone_low - current) / current if current < zone_low else (current - zone_high) / current
        score = 55 if dist < 0.02 else 70
    return {"name": "구조적 매물대 밀도", "score": score, "zone": (zone_low, zone_high)}


def calc_absorption(df: pd.DataFrame, lookback=20) -> Dict:
    x = df.tail(min(lookback, len(df))).copy()
    base = df["value"].tail(min(60, len(df))).mean()
    value_ratio = float(x["value"].mean() / max(base, 1e-9))
    range_pct = float((x["high"].max() - x["low"].min()) / max(abs(x["close"].iloc[-1]), 1e-9))
    score = 78 if value_ratio >= 1.5 and range_pct <= 0.10 else 60 if value_ratio >= 1.3 else 45
    return {"name": "유동성 흡수", "score": score, "value_ratio": value_ratio, "range_pct": range_pct}


def calc_attack(df: pd.DataFrame, lookback=20) -> Dict:
    x = df.tail(min(max(5, lookback), len(df))).copy()
    eps = 1e-9
    hl = (x["high"] - x["low"]).replace(0, eps)
    clv = ((2*x["close"] - x["high"] - x["low"]) / hl).clip(-1, 1)
    w = (x["value"] / (x["value"].mean() + eps)).clip(0.2, 5.0)
    clv_w = float(np.clip((clv*w).mean(), -1, 1))
    ret = x["close"].pct_change().fillna(0).abs()
    base = df["value"].tail(min(60, len(df))).mean()
    money_intensity = (x["value"] / (base + eps)).clip(0.2, 5.0)
    evr = (ret / (money_intensity + eps)).replace([np.inf, -np.inf], 0.0)
    evr_signed = (evr * np.sign(clv)).clip(-1, 1)
    evr_w = float(np.clip((evr_signed*w).mean(), -1, 1))
    body = (x["close"] - x["open"]).abs()
    upper = (x["high"] - x[["open", "close"]].max(axis=1)).clip(lower=0)
    lower = (x[["open", "close"]].min(axis=1) - x["low"]).clip(lower=0)
    wick = ((lower-upper)/(body+upper+lower+eps)).clip(-1, 1)
    wick_w = float(np.clip((wick*w).mean(), -1, 1))
    composite = float(np.clip(0.45*clv_w + 0.35*evr_w + 0.20*wick_w, -1, 1))
    return {"name": "공격성", "score": clamp_int((composite+1)*50), "clv": clv_w, "evr": evr_w, "wick": wick_w}


def calc_elasticity(df: pd.DataFrame, lookback=10) -> Dict:
    x = df.tail(min(lookback, len(df))).copy()
    if len(x) < 2:
        return {"name":"수급 탄성", "score":50, "elasticity":0, "fmi":1}
    start, end = float(x["close"].iloc[0]), float(x["close"].iloc[-1])
    price_chg = (end-start)/max(abs(start),1e-9)*100
    base = df["value"].tail(min(60, len(df))).mean()
    fmi = max(0.2, float(x["value"].mean()/max(base,1e-9)))
    elasticity = price_chg/fmi
    return {"name":"수급 탄성", "score":clamp_int(50+elasticity*6), "elasticity":elasticity, "fmi":fmi}


def calc_fatigue(df: pd.DataFrame) -> Dict:
    es, el = calc_elasticity(df, 10), calc_elasticity(df, 30)
    fatigue = 0.0
    if es["fmi"] >= el["fmi"] and es["elasticity"] < el["elasticity"]:
        fatigue = el["elasticity"] - es["elasticity"]
    return {"name":"수급 피로도", "score":clamp_int(30+fatigue*12)}


def flow_metrics(df: pd.DataFrame) -> Dict[str, Dict]:
    return {
        "absorption": calc_absorption(df),
        "attack": calc_attack(df),
        "elasticity": calc_elasticity(df),
        "fatigue": calc_fatigue(df),
        "avg_cost": calc_avg_cost_band(df),
        "density": calc_supply_density(df),
    }


def flow_score(m: Dict[str, Dict]) -> int:
    return clamp_int(
        m["absorption"]["score"]*0.18 +
        m["attack"]["score"]*0.22 +
        m["elasticity"]["score"]*0.18 +
        (100-m["fatigue"]["score"])*0.18 +
        m["avg_cost"]["score"]*0.12 +
        m["density"]["score"]*0.12
    )

# -----------------------------
# New price-structure layer
# -----------------------------

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    for n in (5,20,60,120):
        x[f"ma{n}"] = x["close"].rolling(n, min_periods=max(2, n//3)).mean()
    prev_close = x["close"].shift(1)
    tr = pd.concat([(x["high"]-x["low"]).abs(), (x["high"]-prev_close).abs(), (x["low"]-prev_close).abs()], axis=1).max(axis=1)
    x["atr14"] = tr.rolling(14, min_periods=5).mean()
    return x


def price_structure(df: pd.DataFrame) -> Dict[str, int | float]:
    x = add_indicators(df)
    last = x.iloc[-1]
    close = float(last["close"])
    # Trend: price above MAs + MA slope
    checks = []
    for n in (5,20,60,120):
        ma = last.get(f"ma{n}")
        if pd.notna(ma):
            checks.append(1 if close > ma else 0)
    trend = 50 if not checks else int(round(35 + 65*np.mean(checks)))
    if len(x) >= 6 and pd.notna(x["ma20"].iloc[-1]) and pd.notna(x["ma20"].iloc[-6]):
        trend = clamp_int(trend + (8 if x["ma20"].iloc[-1] > x["ma20"].iloc[-6] else -8))

    # Breakout: distance from prior 20-day high
    prior = x.iloc[:-1].tail(20)
    if len(prior):
        prior_high = float(prior["high"].max())
        d = (close-prior_high)/max(abs(prior_high),1e-9)
        breakout = clamp_int(50 + d*1200)
    else:
        prior_high, breakout = close, 50

    # Support: proximity above 20/60-day lows, avoid being too extended
    lows = [float(x["low"].tail(min(n,len(x))).min()) for n in (20,60)]
    support_dist = min((close-l)/max(abs(close),1e-9) for l in lows)
    support = clamp_int(55 + min(max(support_dist,0),0.10)*250)

    # Volatility quality: ATR% around 2~5% neutral/good, extreme >8% penalized
    atr_pct = float(last["atr14"]/max(abs(close),1e-9)) if pd.notna(last["atr14"]) else 0.03
    volatility = clamp_int(80 - abs(atr_pct-0.035)*700)

    # Volume confirmation: latest 5d avg / 20d avg
    v5 = float(x["volume"].tail(5).mean())
    v20 = float(x["volume"].tail(min(20,len(x))).mean())
    vol_ratio = v5/max(v20,1e-9)
    volume_confirm = clamp_int(50 + (vol_ratio-1)*35)

    score = clamp_int(trend*0.30 + breakout*0.25 + support*0.20 + volatility*0.10 + volume_confirm*0.15)
    return {"score":score,"trend":trend,"breakout":breakout,"support":support,"volatility":volatility,"volume_confirm":volume_confirm,"prior_high":prior_high,"atr_pct":atr_pct,"vol_ratio":vol_ratio}


def verdict(score:int) -> str:
    if score >= 80: return "강한 구조"
    if score >= 68: return "우호적 구조"
    if score >= 52: return "중립/관찰"
    if score >= 38: return "둔화/주의"
    return "위험/막힘 가능성"


def explain_change(cur: Dict, prev: Dict | None) -> str:
    if not prev: return "비교할 이전 봉 데이터가 부족합니다."
    deltas = {k: cur[k]["score"]-prev[k]["score"] for k in cur if "score" in cur[k] and k in prev}
    labels = {"absorption":"흡수","attack":"공격성","elasticity":"탄성","fatigue":"피로도","avg_cost":"평균단가","density":"매물대"}
    # fatigue lower is good, so invert direction in narrative
    ordered = sorted(deltas.items(), key=lambda kv: abs(kv[1]), reverse=True)
    bits=[]
    for k,d in ordered[:3]:
        arrow = "↑" if d>0 else "↓" if d<0 else "→"
        bits.append(f"{labels[k]} {d:+d} {arrow}")
    return " / ".join(bits)

# -----------------------------
# UI
# -----------------------------
st.title("📈 Chart Lab V0.1")
st.caption("MARVEL V2의 6개 수급 지표를 보존하면서 가격 구조·차트·전일 변화 분석을 추가한 실험용 분석 앱")
st.info("이 앱은 매수/매도 신호가 아니라 차트 구조를 일관되게 해석하기 위한 보조 도구입니다.")

uploaded = st.file_uploader("키움 XLS/XLSX 또는 CSV 업로드", type=["xls","xlsx","csv"])
if uploaded:
    try:
        raw = read_uploaded(uploaded)
        df = normalize(raw)
    except Exception as e:
        st.error(f"파일을 읽지 못했습니다: {e}")
        st.stop()

    if len(df) < 10:
        st.warning("데이터가 10봉 미만이라 일부 지표의 신뢰도가 낮습니다.")

    flow = flow_metrics(df)
    fs = flow_score(flow)
    price = price_structure(df)
    ps = int(price["score"])
    combined = clamp_int(fs*0.55 + ps*0.45)

    prev_flow = flow_metrics(df.iloc[:-1]) if len(df) > 10 else None
    prev_fs = flow_score(prev_flow) if prev_flow else None
    prev_price = price_structure(df.iloc[:-1]) if len(df) > 10 else None

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("수급 구조", f"{fs}점", None if prev_fs is None else f"{fs-prev_fs:+d}")
    c2.metric("가격 구조", f"{ps}점", None if prev_price is None else f"{ps-int(prev_price['score']):+d}")
    c3.metric("실험 종합", f"{combined}점")
    c4.metric("현재 단계", verdict(combined))

    # chart
    x = add_indicators(df)
    view = x.tail(180)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=view["date"], open=view["open"], high=view["high"], low=view["low"], close=view["close"], name="가격"))
    for n in (5,20,60,120):
        fig.add_trace(go.Scatter(x=view["date"], y=view[f"ma{n}"], mode="lines", name=f"MA{n}"))
    ac = flow["avg_cost"]
    fig.add_hline(y=ac["wa"], line_dash="dash", annotation_text="가중 평균단가")
    fig.add_hrect(y0=ac["band_low"], y1=ac["band_high"], opacity=0.08, line_width=0, annotation_text="평균단가 밴드")
    zl, zh = flow["density"]["zone"]
    fig.add_hrect(y0=zl, y1=zh, opacity=0.08, line_width=0, annotation_text="핵심 매물대")
    fig.update_layout(height=620, xaxis_rangeslider_visible=False, margin=dict(l=10,r=10,t=30,b=10))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("수급 구조 6지표")
    labels = [("흡수","absorption"),("공격성","attack"),("탄성","elasticity"),("피로도","fatigue"),("평균단가","avg_cost"),("매물대","density")]
    cols = st.columns(6)
    for col,(label,key) in zip(cols,labels):
        cur = flow[key]["score"]
        delta = None
        if prev_flow:
            delta = cur-prev_flow[key]["score"]
        col.metric(label, cur, None if delta is None else f"{delta:+d}")

    st.subheader("가격 구조")
    pc = st.columns(5)
    for col,(name,key) in zip(pc,[("추세","trend"),("돌파","breakout"),("지지","support"),("변동성","volatility"),("거래량 확인","volume_confirm")]):
        col.metric(name, int(price[key]))

    st.subheader("오늘의 변화")
    st.write(explain_change(flow, prev_flow))

    # interpretation
    notes=[]
    if flow["attack"]["score"] >= 65: notes.append("종가 위치·거래대금·꼬리 압력 조합에서 매수 우위가 상대적으로 강합니다.")
    elif flow["attack"]["score"] <= 40: notes.append("공격성 지표가 약해 주도권 확인이 더 필요합니다.")
    if flow["fatigue"]["score"] >= 60: notes.append("피로도가 높아 자금 대비 가격 반응 둔화를 주의해야 합니다.")
    if price["breakout"] >= 65: notes.append("최근 고점 돌파 측면은 우호적입니다.")
    if price["volume_confirm"] >= 65: notes.append("최근 거래량이 20일 평균 대비 강화되어 가격 움직임을 확인해주고 있습니다.")
    if not notes: notes.append("신호가 혼재되어 있어 다음 봉에서 방향이 더 분명해지는지 확인하는 구간입니다.")
    st.subheader("해석")
    st.write(" ".join(notes))

    with st.expander("계산 세부값"):
        st.json({"flow":flow, "price":price, "flow_score":fs, "price_score":ps, "experimental_combined":combined}, expanded=False)

    st.caption("주의: '실험 종합'은 Chart Lab V0.1에서 새로 추가한 실험값이며 원본 MARVEL V2의 공식이 아닙니다. 실제 투자 성과 검증 전에는 의사결정의 단독 근거로 사용하지 마세요.")
