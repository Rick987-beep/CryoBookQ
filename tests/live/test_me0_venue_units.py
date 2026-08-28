"""Live ME0: REST instruments + ATM unit sanity on Deribit/Bybit/Binance/OKX.

Public market data only — never places orders.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import requests

from cryobookq.venues.spec import SPECS
from tests.live.conftest import require_network

pytestmark = pytest.mark.live

TIMEOUT = 25
TMP = Path("tmp/live")
INDEX_URL = "https://www.deribit.com/api/v2/public/get_index_price"
DERIBIT_INST = "https://www.deribit.com/api/v2/public/get_instruments"
DERIBIT_BOOK = "https://www.deribit.com/api/v2/public/get_order_book"
BYBIT_INST = "https://api.bybit.com/v5/market/instruments-info"
BYBIT_BOOK = "https://api.bybit.com/v5/market/orderbook"
BINANCE_INFO = "https://eapi.binance.com/eapi/v1/exchangeInfo"
BINANCE_DEPTH = "https://eapi.binance.com/eapi/v1/depth"
OKX_INST = "https://www.okx.com/api/v5/public/instruments"
OKX_BOOK = "https://www.okx.com/api/v5/market/books"

_MONTHS = {
    1: "JAN",
    2: "FEB",
    3: "MAR",
    4: "APR",
    5: "MAY",
    6: "JUN",
    7: "JUL",
    8: "AUG",
    9: "SEP",
    10: "OCT",
    11: "NOV",
    12: "DEC",
}


def _get(url: str, params: dict | None = None) -> dict:
    r = requests.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _bybit_symbol(exp_ms: int, strike: float, is_call: bool) -> str:
    dt = datetime.fromtimestamp(exp_ms / 1000, tz=UTC)
    tok = f"{dt.day}{_MONTHS[dt.month]}{dt.strftime('%y')}"
    cp = "C" if is_call else "P"
    strike_s = str(int(strike)) if strike == int(strike) else str(strike)
    return f"BTC-{tok}-{strike_s}-{cp}-USDT"


def _yymmdd_symbol(prefix: str, exp_ms: int, strike: float, is_call: bool) -> str:
    dt = datetime.fromtimestamp(exp_ms / 1000, tz=UTC)
    cp = "C" if is_call else "P"
    strike_s = str(int(strike)) if strike == int(strike) else str(strike)
    return f"{prefix}-{dt.strftime('%y%m%d')}-{strike_s}-{cp}"


def test_me0_venue_units_rest() -> None:
    require_network()
    dump: dict = {}

    index = float(_get(INDEX_URL, {"index_name": "btc_usd"})["result"]["index_price"])
    dump["index"] = index
    assert index > 1000

    inst = _get(DERIBIT_INST, {"currency": "BTC", "kind": "option", "expired": "false"})["result"]
    coin = [it for it in inst if "USDC" not in it.get("instrument_name", "")]
    assert len(coin) > 500
    assert all("BTC_USDC-" not in it["instrument_name"] for it in coin)
    dump["deribit_n"] = len(coin)

    now_ms = datetime.now(tz=UTC).timestamp() * 1000
    cands: list[tuple[float, dict]] = []
    for it in coin:
        if it.get("option_type") != "call":
            continue
        dte = (it["expiration_timestamp"] - now_ms) / 86_400_000
        if 5 <= dte <= 12:
            cands.append((abs(float(it["strike"]) - index), it))
    assert cands, "no Deribit 5–12 DTE calls"
    pick = min(cands, key=lambda x: x[0])[1]
    exp_ms = int(pick["expiration_timestamp"])
    strike = float(pick["strike"])
    d_sym = pick["instrument_name"]
    dump["target"] = {"deribit": d_sym, "exp_ms": exp_ms, "strike": strike}

    d_book = _get(DERIBIT_BOOK, {"instrument_name": d_sym, "depth": 5})["result"]
    d_bids = d_book.get("bids") or []
    d_asks = d_book.get("asks") or []
    assert d_bids and d_asks
    d_bid_px, d_bid_sz = float(d_bids[0][0]), float(d_bids[0][1])
    d_ask_px = float(d_asks[0][0])
    assert d_bid_px < 1.0  # BTC premium
    d_mid_usd = (d_bid_px + d_ask_px) / 2.0 * index
    dump["deribit_l1"] = {"bid_px": d_bid_px, "bid_sz": d_bid_sz, "mid_usd": d_mid_usd}

    listed = 0
    mids_usd: dict[str, float] = {"deribit": d_mid_usd}
    venue_errors: dict[str, str] = {}

    # Bybit
    by_n = 0
    cursor = ""
    try:
        for _ in range(20):
            params: dict = {"category": "option", "baseCoin": "BTC", "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            j = _get(BYBIT_INST, params)
            lst = j.get("result", {}).get("list") or []
            by_n += sum(1 for it in lst if str(it.get("symbol", "")).endswith("-USDT"))
            cursor = j.get("result", {}).get("nextPageCursor") or ""
            if not cursor:
                break
        assert by_n > 400
        dump["bybit_n"] = by_n
        by_sym = _bybit_symbol(exp_ms, strike, True)
        ob = _get(BYBIT_BOOK, {"category": "option", "symbol": by_sym, "limit": 25})
        b = (ob.get("result") or {}).get("b") or []
        a = (ob.get("result") or {}).get("a") or []
        if b and a:
            by_mid = (float(b[0][0]) + float(a[0][0])) / 2.0
            assert by_mid > 50  # USDT premium
            mids_usd["bybit"] = by_mid
            listed += 1
            dump["bybit_l1"] = {"symbol": by_sym, "mid": by_mid, "bid_sz": float(b[0][1])}
        else:
            dump["bybit_l1"] = {"symbol": by_sym, "empty": True}
    except requests.RequestException as exc:
        venue_errors["bybit"] = str(exc)
        dump["bybit_error"] = str(exc)

    # Binance
    try:
        info = _get(BINANCE_INFO)
        opts = [
            o
            for o in (info.get("optionSymbols") or info.get("symbols") or [])
            if o.get("underlying") == "BTCUSDT" and o.get("status") == "TRADING"
        ]
        assert len(opts) > 400
        dump["binance_n"] = len(opts)
        bn_sym = _yymmdd_symbol("BTC", exp_ms, strike, True)
        depth = _get(BINANCE_DEPTH, {"symbol": bn_sym, "limit": 10})
        bids, asks = depth.get("bids") or [], depth.get("asks") or []
        if bids and asks:
            bn_mid = (float(bids[0][0]) + float(asks[0][0])) / 2.0
            assert bn_mid > 50
            mids_usd["binance"] = bn_mid
            listed += 1
            dump["binance_l1"] = {"symbol": bn_sym, "mid": bn_mid, "bid_sz": float(bids[0][1])}
        else:
            dump["binance_l1"] = {"symbol": bn_sym, "empty": True}
    except requests.RequestException as exc:
        venue_errors["binance"] = str(exc)
        dump["binance_error"] = str(exc)

    # OKX inverse
    try:
        okx = _get(OKX_INST, {"instType": "OPTION", "instFamily": "BTC-USD"})
        data = okx.get("data") or []
        assert len(data) > 400
        assert all("USD_UM" not in (it.get("instId") or "") for it in data)
        dump["okx_n"] = len(data)
        ok_sym = _yymmdd_symbol("BTC-USD", exp_ms, strike, True)
        meta = next((it for it in data if it.get("instId") == ok_sym), None)
        if meta is not None:
            ct = float(meta.get("ctVal") or 1) * float(meta.get("ctMult") or 0.01)
            assert ct == pytest.approx(SPECS["okx"].size_to_btc, abs=1e-9)
            listed += 1
            book = _get(OKX_BOOK, {"instId": ok_sym, "sz": "5"})
            lvl = (book.get("data") or [{}])[0]
            ob_bids, ob_asks = lvl.get("bids") or [], lvl.get("asks") or []
            if ob_bids and ob_asks:
                ok_bid_px, ok_bid_sz = float(ob_bids[0][0]), float(ob_bids[0][1])
                ok_ask_px = float(ob_asks[0][0])
                assert ok_bid_px < 1.0  # BTC premium
                mids_usd["okx"] = (ok_bid_px + ok_ask_px) / 2.0 * index
                sz_btc = ok_bid_sz * ct
                dump["okx_l1"] = {
                    "symbol": ok_sym,
                    "native_sz": ok_bid_sz,
                    "sz_btc": sz_btc,
                    "mid_usd": mids_usd["okx"],
                }
                if ok_bid_sz > 10:
                    assert sz_btc < 80, f"OKX multiplier missing? native={ok_bid_sz} sz_btc={sz_btc}"
            else:
                dump["okx_l1"] = {"symbol": ok_sym, "empty_book": True}
        else:
            dump["okx_l1"] = {"symbol": ok_sym, "unlisted": True}
    except requests.RequestException as exc:
        venue_errors["okx"] = str(exc)
        dump["okx_error"] = str(exc)

    if len(venue_errors) == 3:
        pytest.skip(f"all new venues failed REST: {venue_errors}")
    assert listed >= 2, f"need ≥2 of 3 new venues listed for the ATM key; dump={dump}"

    ref = mids_usd["deribit"]
    for name, mid in mids_usd.items():
        if name == "deribit":
            continue
        rel = abs(mid - ref) / ref
        assert rel < 0.15, f"{name} mid {mid} vs deribit {ref} rel={rel:.2%}"

    TMP.mkdir(parents=True, exist_ok=True)
    (TMP / "me0_units.json").write_text(json.dumps(dump, indent=2) + "\n")
