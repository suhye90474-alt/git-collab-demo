import pandas as pd
from scan import evaluate, recent_surge_candle


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
