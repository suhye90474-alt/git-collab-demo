"""거래대금 상위 순 주도주 스캐너 (김종봉 방식).

조건
  1. 당일 거래대금 >= --min-value (억원, 기본 500)
  2. 최근 N일(기본 5) 수익률이 해당 시장 지수보다 높고, 분석일 당일 등락률도 지수보다 높음
  3. 당일 고가 등락률 >= 10%  또는  최근 20일 내 거래량 급증(직전 평균의 N배) 장대양봉

사용:  python scan.py                      # 날짜를 물어봄 (엔터 = 오늘)
       python scan.py --date 20261014      # 그날 데이터 기준으로 분석
       python scan.py --date 2026-10-14 --min-value 1000
"""
import argparse
import getpass
import json
import os
import sys
from datetime import datetime, timedelta

import pandas as pd

INDEX_CODE = {"KOSPI": "1001", "KOSDAQ": "2001"}
THEMES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "themes.json")
# 장대양봉 기준 단계: (거래량 배수, 최소 상승률%). --auto 일 때 충족 종목이 적으면 순서대로 완화.
SURGE_LEVELS = [(3.0, 10.0), (2.0, 7.0), (1.5, 5.0)]


def recent_surge_candle(hist: pd.DataFrame, lookback: int, vol_mult: float,
                        body_pct: float) -> bool:
    """최근 lookback일 내 '거래량 급증 + 장대양봉'이 있었는지.

    hist: 일자 오름차순, 컬럼 시가/종가/거래량. 거래량 비교 기준은 해당일 직전 20일 평균.
    장대양봉 = 종가 > 시가 이고 전일 종가 대비 상승률 >= body_pct(%).
    """
    h = hist.copy()
    h["prev_close"] = h["종가"].shift(1)
    h["ret"] = (h["종가"] / h["prev_close"] - 1) * 100
    h["avg_vol"] = h["거래량"].rolling(20, min_periods=5).mean().shift(1)
    tail = h.tail(lookback)
    hit = (
        (tail["종가"] > tail["시가"])
        & (tail["ret"] >= body_pct)
        & (tail["거래량"] >= tail["avg_vol"] * vol_mult)
    )
    return bool(hit.any())


def evaluate(today: pd.DataFrame, ref_close: pd.Series, index_ret: float,
             min_value_eok: float, idx_day_ret: float = None) -> pd.DataFrame:
    """조건 1·2와 당일 고가 변동률을 계산. today: 티커 인덱스, 컬럼 종가/고가/거래대금/등락률."""
    df = today.copy()
    df["거래대금(억)"] = df["거래대금"] / 1e8
    df = df[df["거래대금(억)"] >= min_value_eok]
    df["prev_close"] = df["종가"] / (1 + df["등락률"] / 100)
    df["고가변동률"] = (df["고가"] / df["prev_close"] - 1) * 100
    df["Nd수익률"] = (df["종가"] / ref_close.reindex(df.index) - 1) * 100
    df["지수Nd"] = index_ret
    df["상대강도"] = df["Nd수익률"] - index_ret
    if idx_day_ret is not None:
        df["지수당일"] = idx_day_ret
    return df.sort_values("거래대금(억)", ascending=False)


def normalize_date(text: str) -> str:
    """'2026-10-14', '2026.10.14', '20261014' -> '20261014'. 잘못된 형식이면 ValueError."""
    digits = "".join(ch for ch in text if ch.isdigit())
    datetime.strptime(digits, "%Y%m%d")
    return digits


def classify_day(index_day_ret: float, ret: float, high_ret: float) -> str:
    """분석일 하루 기준 종목 유형.

    지수 하락일: 종목이 플러스면 '방어(하락장 상승)', 지수보다 덜 빠졌으면 '방어(덜 하락)'.
    지수 상승일: 당일 등락률 또는 고가 변동률이 10% 이상이면 '탄력(10%+)'.
    """
    if index_day_ret < 0:
        if ret > 0:
            return "방어(하락장 상승)"
        if ret > index_day_ret:
            return "방어(덜 하락)"
    elif ret >= 10 or high_ret >= 10:
        return "탄력(10%+)"
    return "-"


def load_themes(path: str = THEMES_FILE) -> dict:
    """themes.json -> {종목명: 테마명}. 파일이 없거나 깨져 있으면 빈 dict."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    return {name: theme for theme, names in raw.items()
            if isinstance(names, list) for name in names}


def assign_groups(names, sectors, theme_of: dict) -> list:
    """테마(themes.json) 우선, 없으면 KRX 업종, 그것도 없으면 '기타'."""
    out = []
    for n, sec in zip(names, sectors):
        out.append(theme_of.get(n) or (sec if isinstance(sec, str) and sec else "기타"))
    return out


def mark_leaders(df: pd.DataFrame) -> pd.DataFrame:
    """그룹별 대장주('대장' 컬럼). '기타' 그룹은 제외.

    대장 = 그룹 안에서 '당일 지수보다 덜 빠졌거나 오른' 종목 중 거래대금 1위.
    그룹 전체가 지수보다 약했다면 대장 없음(거래대금만 큰 약세 종목을 대장으로 보지 않기 위해).
    """
    df = df.copy()
    ok = df["등락률"] > df["지수당일"] if "지수당일" in df else pd.Series(True, index=df.index)
    ok &= df["그룹"] != "기타"
    val = df["거래대금(억)"].where(ok)
    top = val.groupby(df["그룹"]).transform("max")
    df["대장"] = ok & (val == top)
    return df


def sort_results(df: pd.DataFrame) -> pd.DataFrame:
    """충족수 내림차순, 같으면 등락률 내림차순."""
    return df.sort_values(["충족수", "등락률"], ascending=[False, False])


def score(df: pd.DataFrame, surge: pd.Series) -> pd.DataFrame:
    df = df.copy()
    df["최근장대양봉"] = surge
    df["①거래대금"] = True
    df["②상대강도"] = df["상대강도"] > 0
    if "지수당일" in df:       # 5일 상대강도 + 당일에도 지수보다 강해야 함
        df["②상대강도"] &= df["등락률"] > df["지수당일"]
    df["③탄력성"] = (df["고가변동률"] >= 10) | df["최근장대양봉"]
    df["충족수"] = df[["①거래대금", "②상대강도", "③탄력성"]].sum(axis=1)
    return df


def group_summary(df: pd.DataFrame) -> pd.DataFrame:
    """그룹별 요약. df 에는 '대장' 컬럼(mark_leaders 결과)이 있어야 함. 3조건 충족 많은 그룹 먼저."""
    rows = []
    for g, sub in df.groupby("그룹"):
        top_val = sub.sort_values("거래대금(억)", ascending=False).iloc[0]
        lead = sub[sub["대장"]]
        lead = lead.iloc[0] if len(lead) else None
        rows.append({
            "그룹": g,
            "대장주": lead["종목명"] if lead is not None else "(없음)",
            "대장등락률": float(lead["등락률"]) if lead is not None else float("nan"),
            "거래대금1위": top_val["종목명"],
            "1위등락률": float(top_val["등락률"]),
            "종목수": len(sub),
            "3조건충족": int((sub["충족수"] == 3).sum()),
            "최대충족수": int(sub["충족수"].max()),
        })
    out = pd.DataFrame(rows)
    return out.sort_values(["3조건충족", "최대충족수", "대장등락률"], ascending=False) if len(out) else out


# ---------------------------------------------------------------- data access
def _stock():
    try:
        from pykrx import stock
    except ImportError:
        sys.exit("pykrx가 없습니다:  pip install -r requirements.txt")
    return stock


def ensure_krx_login():
    """pykrx 1.2+ 는 KRX 데이터 마켓플레이스(data.krx.co.kr) 로그인이 필요합니다.

    환경변수 KRX_ID / KRX_PW 가 없으면 실행 시 직접 입력받습니다(비밀번호는 저장하지 않음).
    """
    if os.getenv("KRX_ID") and os.getenv("KRX_PW"):
        return
    print("KRX 로그인이 필요합니다 (data.krx.co.kr 무료 회원가입 계정).")
    if not sys.stdin.isatty():
        sys.exit("환경변수 KRX_ID, KRX_PW 를 설정하세요.")
    os.environ["KRX_ID"] = input("KRX 아이디: ").strip()
    os.environ["KRX_PW"] = getpass.getpass("KRX 비밀번호(입력 내용은 화면에 안 보임): ")


def fetch_sectors(stock, base: str) -> pd.Series:
    """티커 -> KRX 업종명. 실패하면 빈 Series(그룹은 '기타' 또는 테마로 처리)."""
    parts = []
    for market in INDEX_CODE:
        try:
            parts.append(stock.get_market_sector_classifications(base, market)["업종명"])
        except Exception as e:  # 네트워크/인증/스키마 변경 등
            print(f"  (업종 정보를 가져오지 못했습니다: {market}: {e})")
    return pd.concat(parts) if parts else pd.Series(dtype=object)


def trading_days(stock, end: str, n: int) -> list:
    start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=n * 2 + 20)).strftime("%Y%m%d")
    idx = stock.get_index_ohlcv_by_date(start, end, INDEX_CODE["KOSPI"])
    return [d.strftime("%Y%m%d") for d in idx.index]


def run(args) -> pd.DataFrame:
    stock = _stock()
    ensure_krx_login()
    end = args.date
    days = trading_days(stock, end, args.days + 25)
    if len(days) < args.days + 1:
        sys.exit("거래일 데이터를 가져오지 못했습니다. 날짜/네트워크를 확인하세요.")
    base, ref = days[-1], days[-1 - args.days]
    if base != end:
        print(f"※ {end}은(는) 휴장일이거나 데이터가 없어 직전 거래일 {base} 기준으로 분석합니다.")
    print(f"분석일 {base}, 비교일 {ref} ({args.days}거래일 전)")

    rows = []
    for market, icode in INDEX_CODE.items():
        idx = stock.get_index_ohlcv_by_date(ref, base, icode)["종가"]
        index_ret = (idx.iloc[-1] / idx.iloc[0] - 1) * 100
        idx_today = (idx.iloc[-1] / idx.iloc[-2] - 1) * 100
        print(f"{market}: 당일 {idx_today:+.2f}%  {args.days}일 {index_ret:+.2f}%")

        today = stock.get_market_ohlcv_by_ticker(base, market=market)
        ref_close = stock.get_market_ohlcv_by_ticker(ref, market=market)["종가"]
        df = evaluate(today, ref_close, index_ret, args.min_value, idx_today)
        df["당일유형"] = [classify_day(idx_today, r, h)
                      for r, h in zip(df["등락률"], df["고가변동률"])]
        df["시장"] = market
        rows.append(df)

    rows = [r for r in rows if len(r)]
    if not rows:
        sys.exit("거래대금 조건을 넘는 종목이 없습니다. --min-value 를 낮춰 보세요.")
    df = pd.concat(rows).sort_values("거래대금(억)", ascending=False).head(args.top)
    df["종목명"] = [stock.get_market_ticker_name(t) for t in df.index]

    start20 = days[-min(len(days), 40)]
    hists = {t: stock.get_market_ohlcv_by_date(start20, base, t) for t in df.index}

    levels = SURGE_LEVELS if args.auto else [(args.vol_mult, args.body_pct)]
    chosen = None
    for vol_mult, body_pct in levels:
        surge = pd.Series(
            {t: recent_surge_candle(h, args.surge_days, vol_mult, body_pct) for t, h in hists.items()}
        )
        scored = score(df, surge)
        hits = int((scored["충족수"] == 3).sum())
        chosen = (vol_mult, body_pct, scored)
        if hits >= args.min_hits:
            break
    vol_mult, body_pct, df = chosen
    df["장대양봉기준"] = f"거래량x{vol_mult:g}/{body_pct:g}%"
    print(f"\n장대양봉 기준: 거래량 {vol_mult:g}배 이상 & 상승 {body_pct:g}% 이상"
          + (" (충족 종목이 적어 자동 완화)" if (vol_mult, body_pct) != levels[0] else ""))

    funnel = (f"거래대금 상위 {len(df)}종목 중 → ②상대강도 {int(df['②상대강도'].sum())}개, "
              f"③탄력성 {int(df['③탄력성'].sum())}개, 3조건 모두 {int((df['충족수'] == 3).sum())}개")
    print(funnel)

    sectors = fetch_sectors(stock, base).reindex(df.index)
    df["그룹"] = assign_groups(df["종목명"], sectors, load_themes())
    df = sort_results(mark_leaders(df))
    df.attrs["base"] = base
    return df


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--date", help="분석할 날짜 YYYYMMDD 또는 YYYY-MM-DD (생략하면 실행 시 물어봄)")
    p.add_argument("--min-value", type=float, default=500, help="최소 거래대금(억원)")
    p.add_argument("--days", type=int, default=5, help="상대강도 비교 거래일 수")
    p.add_argument("--top", type=int, default=30, help="거래대금 상위 N개만 검사")
    p.add_argument("--surge-days", type=int, default=20, help="장대양봉 탐색 기간(거래일)")
    p.add_argument("--vol-mult", type=float, default=3.0, help="거래량 급증 배수(--no-auto 일 때 사용)")
    p.add_argument("--body-pct", type=float, default=10.0, help="장대양봉 최소 상승률(%%) (--no-auto 일 때 사용)")
    p.add_argument("--no-auto", dest="auto", action="store_false",
                   help="장대양봉 기준 자동 완화를 끄고 --vol-mult/--body-pct 고정 사용")
    p.add_argument("--min-hits", type=int, default=3, help="3조건 충족 종목이 이보다 적으면 기준을 단계적으로 완화")
    p.add_argument("--all", action="store_true", help="3조건 모두 충족하지 않는 종목도 출력")
    p.add_argument("--out", help="CSV 저장 경로 (기본: leaders_YYYYMMDD.csv)")
    args = p.parse_args()

    if not args.date:
        default = datetime.now().strftime("%Y%m%d")
        args.date = input(f"분석할 날짜 (예: 20261014, 엔터={default}): ").strip() or default
    try:
        args.date = normalize_date(args.date)
    except ValueError:
        sys.exit("날짜 형식이 올바르지 않습니다. 예: 20261014 또는 2026-10-14")

    df = run(args)
    df["대장"] = df["대장"].map({True: "★", False: ""})
    cols = ["그룹", "대장", "시장", "종목명", "종가", "등락률", "거래대금(억)", "고가변동률",
            "Nd수익률", "상대강도", "최근장대양봉", "당일유형", "충족수"]
    if "지수당일" in df:
        cols.insert(cols.index("등락률") + 1, "지수당일")
    show = df if args.all else df[df["충족수"] == 3]
    pd.set_option("display.width", 220, "display.unicode.east_asian_width", True)
    fmt = show[cols].rename(columns={"Nd수익률": f"{args.days}일수익률"})
    print("\n[종목 목록: 충족수↓, 등락률↓]")
    print(fmt.to_string(float_format=lambda v: f"{v:,.2f}") if len(fmt) else "3조건 모두 충족한 종목이 없습니다. --all 로 전체 확인")

    summ = group_summary(df.assign(대장=df["대장"] == "★"))
    print("\n[섹터/테마별 대장주]  (대장 = 그룹 내 '당일 지수보다 강한' 종목 중 거래대금 1위, 없으면 (없음))")
    print(summ.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))

    out = args.out or f"leaders_{df.attrs['base']}.csv"
    try:
        df.to_csv(out, encoding="utf-8-sig")
    except PermissionError:
        # 같은 이름의 파일이 엑셀 등에서 열려 있으면 쓸 수 없음 -> 시각을 붙인 새 이름으로 저장
        root, ext = os.path.splitext(out)
        out = f"{root}_{datetime.now():%H%M%S}{ext}"
        print(f"\n(기존 파일이 열려 있어 새 이름으로 저장합니다)")
        df.to_csv(out, encoding="utf-8-sig")
    print(f"\n전체 {len(df)}종목 결과 저장: {os.path.abspath(out)}")


if __name__ == "__main__":
    main()
