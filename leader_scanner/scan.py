"""거래대금 상위 순 주도주 스캐너 (김종봉 방식).

조건
  1. 당일 거래대금 >= --min-value (억원, 기본 500)
  2. 최근 N일(기본 5) 수익률이 해당 시장 지수 수익률보다 높음 (지수 하락 시 덜 하락하거나 플러스 유지)
  3. 당일 고가 등락률 >= 10%  또는  최근 20일 내 거래량 급증(직전 평균의 N배) 장대양봉

사용:  python scan.py            # 가장 최근 거래일 기준
       python scan.py --date 20261014 --min-value 1000
"""
import argparse
import getpass
import os
import sys
from datetime import datetime, timedelta

import pandas as pd

INDEX_CODE = {"KOSPI": "1001", "KOSDAQ": "2001"}


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
             min_value_eok: float) -> pd.DataFrame:
    """조건 1·2와 당일 고가 변동률을 계산. today: 티커 인덱스, 컬럼 종가/고가/거래대금/등락률."""
    df = today.copy()
    df["거래대금(억)"] = df["거래대금"] / 1e8
    df = df[df["거래대금(억)"] >= min_value_eok]
    df["prev_close"] = df["종가"] / (1 + df["등락률"] / 100)
    df["고가변동률"] = (df["고가"] / df["prev_close"] - 1) * 100
    df["Nd수익률"] = (df["종가"] / ref_close.reindex(df.index) - 1) * 100
    df["지수Nd"] = index_ret
    df["상대강도"] = df["Nd수익률"] - index_ret
    return df.sort_values("거래대금(억)", ascending=False)


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


def trading_days(stock, end: str, n: int) -> list:
    start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=n * 2 + 20)).strftime("%Y%m%d")
    idx = stock.get_index_ohlcv_by_date(start, end, INDEX_CODE["KOSPI"])
    return [d.strftime("%Y%m%d") for d in idx.index]


def run(args) -> pd.DataFrame:
    stock = _stock()
    ensure_krx_login()
    end = args.date or datetime.now().strftime("%Y%m%d")
    days = trading_days(stock, end, args.days + 25)
    if len(days) < args.days + 1:
        sys.exit("거래일 데이터를 가져오지 못했습니다. 날짜/네트워크를 확인하세요.")
    base, ref = days[-1], days[-1 - args.days]
    print(f"기준일 {base}, 비교일 {ref} ({args.days}거래일 전)")

    rows = []
    for market, icode in INDEX_CODE.items():
        idx = stock.get_index_ohlcv_by_date(ref, base, icode)["종가"]
        index_ret = (idx.iloc[-1] / idx.iloc[0] - 1) * 100
        idx_today = (idx.iloc[-1] / idx.iloc[-2] - 1) * 100
        print(f"{market}: 당일 {idx_today:+.2f}%  {args.days}일 {index_ret:+.2f}%")

        today = stock.get_market_ohlcv_by_ticker(base, market=market)
        ref_close = stock.get_market_ohlcv_by_ticker(ref, market=market)["종가"]
        df = evaluate(today, ref_close, index_ret, args.min_value)
        df["시장"] = market
        rows.append(df)

    df = pd.concat(rows).sort_values("거래대금(억)", ascending=False).head(args.top)
    df["종목명"] = [stock.get_market_ticker_name(t) for t in df.index]

    start20 = days[-min(len(days), 40)]
    surge = []
    for t in df.index:
        hist = stock.get_market_ohlcv_by_date(start20, base, t)
        surge.append(recent_surge_candle(hist, args.surge_days, args.vol_mult, args.body_pct))
    df["최근장대양봉"] = surge

    df["①거래대금"] = True
    df["②상대강도"] = df["상대강도"] > 0
    df["③탄력성"] = (df["고가변동률"] >= 10) | df["최근장대양봉"]
    df["충족수"] = df[["①거래대금", "②상대강도", "③탄력성"]].sum(axis=1)
    return df


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--date", help="기준일 YYYYMMDD (기본: 오늘/가장 최근 거래일)")
    p.add_argument("--min-value", type=float, default=500, help="최소 거래대금(억원)")
    p.add_argument("--days", type=int, default=5, help="상대강도 비교 거래일 수")
    p.add_argument("--top", type=int, default=30, help="거래대금 상위 N개만 검사")
    p.add_argument("--surge-days", type=int, default=20, help="장대양봉 탐색 기간(거래일)")
    p.add_argument("--vol-mult", type=float, default=3.0, help="거래량 급증 배수(직전 20일 평균 대비)")
    p.add_argument("--body-pct", type=float, default=10.0, help="장대양봉 최소 상승률(%%)")
    p.add_argument("--all", action="store_true", help="3조건 모두 충족하지 않는 종목도 출력")
    p.add_argument("--out", help="CSV 저장 경로 (기본: leaders_YYYYMMDD.csv)")
    args = p.parse_args()

    df = run(args)
    cols = ["시장", "종목명", "종가", "등락률", "거래대금(억)", "고가변동률",
            "Nd수익률", "상대강도", "최근장대양봉", "충족수"]
    show = df if args.all else df[df["충족수"] == 3]
    pd.set_option("display.width", 200, "display.unicode.east_asian_width", True)
    fmt = show[cols].rename(columns={"Nd수익률": f"{args.days}일수익률"})
    print("\n" + (fmt.round(2).to_string() if len(fmt) else "3조건 모두 충족한 종목이 없습니다. --all 로 전체 확인"))

    out = args.out or f"leaders_{datetime.now():%Y%m%d}.csv"
    df.to_csv(out, encoding="utf-8-sig")
    print(f"\n전체 {len(df)}종목 결과 저장: {out}")


if __name__ == "__main__":
    main()
