from __future__ import annotations

from pathlib import Path

from paper.session_log import SessionEvent, SessionLogger
from paper.session_replay import fills_only, load_session, pnl_curve, session_to_dataframe


def test_logged_events_round_trip(tmp_path: Path):
    path = tmp_path / "session.jsonl"
    with SessionLogger(path) as logger:
        logger.log(SessionEvent(timestamp=1.0, event_type="quote", instrument="BTC-PERPETUAL", data={"bid": 100.0, "ask": 101.0}))
        logger.log(SessionEvent(timestamp=2.0, event_type="fill", instrument="BTC-PERPETUAL", data={"side": "bid", "price": 100.0, "size": 0.1}))

    events = load_session(path)
    assert len(events) == 2
    assert events[0].event_type == "quote"
    assert events[1].data["price"] == 100.0


def test_logger_flushes_immediately(tmp_path: Path):
    path = tmp_path / "session.jsonl"
    logger = SessionLogger(path)
    logger.log(SessionEvent(timestamp=1.0, event_type="fill", instrument="X", data={}))
    # read the file while the logger is still open, without closing it first
    events = load_session(path)
    logger.close()
    assert len(events) == 1


def test_session_to_dataframe_flattens_data_fields(tmp_path: Path):
    path = tmp_path / "session.jsonl"
    with SessionLogger(path) as logger:
        logger.log(SessionEvent(timestamp=1.0, event_type="fill", instrument="BTC-PERPETUAL", data={"side": "bid", "price": 100.0}))

    df = session_to_dataframe(path)
    assert "price" in df.columns
    assert df.iloc[0]["price"] == 100.0


def test_fills_only_filters_to_fill_events(tmp_path: Path):
    path = tmp_path / "session.jsonl"
    with SessionLogger(path) as logger:
        logger.log(SessionEvent(timestamp=1.0, event_type="quote", instrument="X", data={}))
        logger.log(SessionEvent(timestamp=2.0, event_type="fill", instrument="X", data={"price": 1.0}))
        logger.log(SessionEvent(timestamp=3.0, event_type="fill", instrument="X", data={"price": 2.0}))

    df = fills_only(path)
    assert len(df) == 2
    assert (df["event_type"] == "fill").all()


def test_pnl_curve_extracts_greeks_snapshots(tmp_path: Path):
    path = tmp_path / "session.jsonl"
    with SessionLogger(path) as logger:
        logger.log(SessionEvent(timestamp=1.0, event_type="greeks", instrument="BTC-PERPETUAL", data={"unrealized_pnl": 5.0, "delta": 0.1}))
        logger.log(SessionEvent(timestamp=2.0, event_type="greeks", instrument="BTC-PERPETUAL", data={"unrealized_pnl": -2.0, "delta": 0.2}))

    curve = pnl_curve(path)
    assert list(curve["unrealized_pnl"]) == [5.0, -2.0]


def test_empty_session_file_yields_no_events(tmp_path: Path):
    path = tmp_path / "session.jsonl"
    path.touch()
    assert load_session(path) == []
