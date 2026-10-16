import pandas as pd
from scan import classify_day, evaluate, normalize_date, recent_surge_candle


def test_evaluate_filters_and_relative_strength():
    today = pd.DataFrame({
        "종가": [110, 100, 50], "고가": [112, 101, 52],
        "거래대금": [900e8, 700e8, 100e8], "등락률": [10.0, 0.0, 1.0],
    }, index=["A", "B", "C"])
    ref = pd.Series({"A": 100, "B": 105, "C": 50})
    df = evaluate(today, ref, index_ret=-2.0, min_value_eok=500)
    assert list(df.index) == ["A", "B"]          # C는 거래대금 미달, 거래대금순
    assert abs(df.loc["A", "상대강도"] - 12.0) < 1e-9
    assert df.loc["B", "상대강도"] < 0                # B는 지수(-2%)보다 약함
    assert abs(df.loc["A", "고가변동률"] - 12.0) < 0.1


def test_surge_candle():
    n = 30
    hist = pd.DataFrame({"시가": [100] * n, "종가": [100] * n, "거래량": [1000] * n})
    assert not recent_surge_candle(hist, 20, 3, 10)
    hist.loc[n - 5, ["시가", "종가", "거래량"]] = [100, 115, 5000]
    hist.loc[n - 4:, ["시가", "종가"]] = 115
    assert recent_surge_candle(hist, 20, 3, 10)


def test_classify_day():
    assert classify_day(-1.0, 2.0, 3.0) == "방어(하락장 상승)"
    assert classify_day(-1.0, -0.3, 1.0) == "방어(덜 하락)"
    assert classify_day(-1.0, -2.0, 0.0) == "-"
    assert classify_day(1.0, 12.0, 15.0) == "탄력(10%+)"
    assert classify_day(1.0, 3.0, 4.0) == "-"


def test_normalize_date():
    assert normalize_date("2026-10-14") == "20261014"
    assert normalize_date("2026.10.14") == "20261014"
    assert normalize_date("20261014") == "20261014"
    try:
        normalize_date("2026-13-40")
        assert False
    except ValueError:
        pass


# ---------------------------------------------------------------- 새 기능
from scan import assign_groups, group_summary, mark_leaders, score, sort_results


def _sample():
    return pd.DataFrame({
        "종목명": ["A", "B", "C", "D"],
        "그룹": ["반도체", "반도체", "바이오", "기타"],
        "등락률": [3.0, 9.0, 5.0, 1.0],
        "거래대금(억)": [900, 600, 700, 800],
        "고가변동률": [4, 10, 3, 2],
        "상대강도": [1, 2, -1, 3],
    }, index=["a", "b", "c", "d"])


def test_assign_groups_theme_then_sector_then_etc():
    g = assign_groups(["A", "B", "C"], ["전기전자", None, float("nan")], {"A": "반도체 장비"})
    assert g == ["반도체 장비", "기타", "기타"]
    assert assign_groups(["Z"], ["제약"], {}) == ["제약"]


def test_mark_leaders_excludes_etc():
    df = mark_leaders(_sample())
    assert df.loc["a", "대장"] and not df.loc["b", "대장"]
    assert df.loc["c", "대장"]
    assert not df.loc["d", "대장"]


def test_sort_by_score_then_change():
    df = score(_sample(), pd.Series({"a": False, "b": False, "c": True, "d": False}))
    out = sort_results(df)
    # b: ①②③(고가10%) =3, c: ①③ =2 (상대강도 음수), a: ①② =2, d: ①② =2
    assert out.index[0] == "b"
    assert list(out.index[1:]) == ["c", "a", "d"]       # 충족수 2끼리 등락률 5>3>1


def test_group_summary_picks_leader():
    df = mark_leaders(score(_sample(), pd.Series({"a": False, "b": False, "c": True, "d": False})))
    s = group_summary(df).set_index("그룹")
    assert s.loc["반도체", "대장주"] == "A" and s.loc["반도체", "3조건충족"] == 1
    assert s.index[0] == "반도체"                        # 3조건 충족이 있는 그룹이 먼저


# 가짜 pykrx로 run() 전체 흐름 검증 (KRX 접속 없이)
class _FakeStock:
    def __init__(self):
        import numpy as np
        self.dates = pd.bdate_range("2026-09-01", "2026-10-14")
        n = len(self.dates)
        base = pd.Series(range(n), index=self.dates)
        self.idx = pd.DataFrame({"종가": 7000 - base * 2.0})      # 지수 완만한 하락

    def get_index_ohlcv_by_date(self, a, b, code):
        return self.idx.loc[a:b]

    def get_market_ohlcv_by_ticker(self, date, market):
        d = pd.Timestamp(date)
        up = d == self.dates[-1]
        data = {
            "000001": [100, 100, 130, 100, 0, 900e8 if market == "KOSDAQ" else 0, 0.0],
        }
        # 하나의 종목만 KOSDAQ에 존재: 어제 100 -> 오늘 112(고가 115)
        if market != "KOSDAQ":
            return pd.DataFrame(columns=["시가", "고가", "저가", "종가", "거래량", "거래대금", "등락률"])
        close = 112 if up else 100
        row = [100, 115 if up else 100, 100, close, 1000, 900e8, 12.0 if up else 0.0]
        return pd.DataFrame([row], index=["000001"],
                            columns=["시가", "고가", "저가", "종가", "거래량", "거래대금", "등락률"])

    def get_market_ticker_name(self, t):
        return "에코프로"

    def get_market_ohlcv_by_date(self, a, b, t):
        n = len(self.dates)
        h = pd.DataFrame({"시가": [100] * n, "종가": [100] * n, "거래량": [1000] * n}, index=self.dates)
        h.iloc[-1] = [100, 112, 5000]
        return h.loc[a:b]

    def get_market_sector_classifications(self, date, market):
        return pd.DataFrame({"업종명": ["화학"]}, index=["000001"]) if market == "KOSDAQ" \
            else pd.DataFrame({"업종명": []}, index=[])


def test_run_end_to_end_with_fake_krx(monkeypatch):
    import argparse
    import scan
    monkeypatch.setattr(scan, "_stock", lambda: _FakeStock())
    monkeypatch.setattr(scan, "ensure_krx_login", lambda: None)
    args = argparse.Namespace(date="20261014", days=5, min_value=500, top=30, surge_days=20,
                              vol_mult=3.0, body_pct=10.0, auto=True, min_hits=1)
    df = scan.run(args)
    assert len(df) == 1
    r = df.iloc[0]
    assert r["충족수"] == 3 and r["그룹"] == "2차전지" and r["대장"]   # themes.json 의 에코프로
    assert r["당일유형"] == "탄력(10%+)" or r["당일유형"].startswith("방어")
    assert df.attrs["base"] == "20261014"


def test_csv_save_falls_back_when_locked(monkeypatch, tmp_path, capsys):
    import scan
    df = scan.score(_sample(), pd.Series({"a": False, "b": False, "c": True, "d": False}))
    df["대장"] = True
    for c in ["시장", "종가", "Nd수익률", "당일유형"]:
        df[c] = 0
    df.attrs["base"] = "20261014"
    monkeypatch.setattr(scan, "run", lambda a: df)
    real = pd.DataFrame.to_csv
    calls = []

    def fake(self, path, **kw):
        calls.append(path)
        if len(calls) == 1:
            raise PermissionError(13, "denied")
        return real(self, path, **kw)

    monkeypatch.setattr(pd.DataFrame, "to_csv", fake)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["scan.py", "--date", "20261014"])
    scan.main()
    assert len(calls) == 2 and calls[0] != calls[1]
    assert (tmp_path / calls[1]).exists()


def test_weak_day_stock_fails_condition2_and_cannot_lead():
    df = _sample()
    df["지수당일"] = -5.0
    df.loc["a", "등락률"] = -10.0           # 거래대금 1위지만 지수보다 약함
    s = score(df, pd.Series({"a": True, "b": False, "c": False, "d": False}))
    assert not s.loc["a", "②상대강도"]       # 5일 상대강도는 +1 이어도 당일이 약하면 탈락
    m = mark_leaders(s)
    assert not m.loc["a", "대장"] and m.loc["b", "대장"]      # 반도체 대장은 B
    summ = group_summary(m).set_index("그룹")
    assert summ.loc["반도체", "거래대금1위"] == "A"


def test_group_without_strong_stock_has_no_leader():
    df = _sample()
    df["지수당일"] = 10.0                    # 모두 지수보다 약함
    m = mark_leaders(score(df, pd.Series(False, index=df.index)))
    assert not m["대장"].any()
    assert (group_summary(m)["대장주"] == "(없음)").all()
