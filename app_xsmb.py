import datetime
import json
import time
from pathlib import Path
from typing import List, Dict, Optional

import requests
import streamlit as st
from bs4 import BeautifulSoup

# -------- Config ---------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}
SOURCES = [
    "https://www.minhngoc.net.vn/ket-qua-xo-so/mien-bac/{}.html",  # dd-mm-yyyy
    "https://xoso.com.vn/xsmb-{}.html",  # dd-mm-yyyy (fallback)
]
CACHE_PATH = Path(".cache/xsmb_cache.json")
CACHE_PATH.parent.mkdir(exist_ok=True)

# Prize label mapping for display order
PRIZE_LABELS = ["GDB", "G1", "G2", "G3", "G4", "G5", "G6", "G7"]

# -------- Cache helpers ---------

def _load_cache() -> Dict[str, Dict]:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: Dict[str, Dict]) -> None:
    try:
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def get_cached(date: datetime.date) -> Optional[Dict[str, List[str]]]:
    cache = _load_cache()
    key = date.isoformat()
    entry = cache.get(key)
    if not entry:
        return None
    return entry.get("data")


def set_cached(date: datetime.date, data: Dict[str, List[str]]) -> None:
    cache = _load_cache()
    cache[date.isoformat()] = {"data": data, "ts": int(time.time())}
    _save_cache(cache)


# -------- Fetch helpers ---------

def fetch_url(url: str, retries: int = 2, backoff: float = 0.5) -> str:
    """Fetch URL with basic retry and backoff."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff * (2 ** attempt))
            continue
    raise last_err  # type: ignore


def fetch_from_minhngoc(date: datetime.date) -> Dict[str, List[str]]:
    url = SOURCES[0].format(date.strftime('%d-%m-%Y'))
    html = fetch_url(url)
    soup = BeautifulSoup(html, "html.parser")
    out: Dict[str, List[str]] = {}

    tbl = soup.find("table", class_="bkqmienbac")
    if not tbl:
        raise ValueError("Không tìm thấy bảng kết quả trên minhngoc.net.vn")

    class_map = {
        "giaidb": "GDB",
        "giai1": "G1",
        "giai2": "G2",
        "giai3": "G3",
        "giai4": "G4",
        "giai5": "G5",
        "giai6": "G6",
        "giai7": "G7",
    }

    for css, label in class_map.items():
        cells = tbl.select(f"td.{css} div")
        nums = [c.get_text(strip=True) for c in cells if c.get_text(strip=True)]
        if nums:
            out[label] = nums
    if not out:
        raise ValueError("Không đọc được dữ liệu từ minhngoc.net.vn")
    return out


def fetch_from_xoso(date: datetime.date) -> Dict[str, List[str]]:
    url = SOURCES[1].format(date.strftime('%d-%m-%Y'))
    html = fetch_url(url)
    soup = BeautifulSoup(html, "html.parser")
    out: Dict[str, List[str]] = {}
    mapping = {
        "prizeDB": "GDB",
        "prize1": "G1",
        "prize2": "G2",
        "prize3": "G3",
        "prize4": "G4",
        "prize5": "G5",
        "prize6": "G6",
        "prize7": "G7",
    }
    for pid, key in mapping.items():
        cell = soup.find(id=pid)
        if not cell:
            continue
        nums = [n.strip() for n in cell.get_text(" ").split() if n.strip().isdigit()]
        if nums:
            out[key] = nums
    if not out:
        raise ValueError("Không đọc được dữ liệu từ xoso.com.vn")
    return out


def fetch_xsmb(date: datetime.date, use_cache: bool = True, force_refresh: bool = False) -> Dict[str, List[str]]:
    # Try cache first
    if use_cache and not force_refresh:
        cached = get_cached(date)
        if cached:
            return cached

    errors = []
    for func in (fetch_from_minhngoc, fetch_from_xoso):
        try:
            data = func(date)
            if use_cache:
                set_cached(date, data)
            return data
        except Exception as e:
            errors.append(str(e))
            continue
    raise RuntimeError("; ".join(errors))


# -------- Analytics helpers ---------

def aggregate_frequency(history: List[Dict[str, List[str]]]) -> Dict[str, int]:
    freq: Dict[str, int] = {}
    for day in history:
        for arr in day.values():
            for n in arr:
                freq[n] = freq.get(n, 0) + 1
    return freq


def normalize_last2(result: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Take last 2 digits of every number (zero-fill)."""
    norm: Dict[str, List[str]] = {}
    for k, arr in result.items():
        norm[k] = [n[-2:].zfill(2) for n in arr if n]
    return norm


def aggregate_weighted(history: List[Dict[str, List[str]]], decay: float = 0.9) -> Dict[str, float]:
    """Exponential decay by day offset: weight = decay**offset (offset=0 is selected date)."""
    freq: Dict[str, float] = {}
    for offset, day in enumerate(history):
        w = decay ** offset
        for arr in day.values():
            for n in arr:
                freq[n] = freq.get(n, 0.0) + w
    return freq


def suggest_numbers(freq: Dict[str, float], top_k: int = 10) -> List[str]:
    sorted_nums = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [n for n, _ in sorted_nums[:top_k]]


# -------- Streamlit UI ---------
st.set_page_config(page_title="XSMB Checker", page_icon="🎟️", layout="centered")
st.title("XS Miền Bắc")

main_tab, rule_tab = st.tabs(["Gợi ý 2 số lô", "Tìm số đề đóm"])

with main_tab:
    st.markdown(
        """
- Nguồn chính: minhngoc.net.vn; dự phòng: xoso.com.vn.
- Gợi ý dựa trên tần suất 2 chữ số cuối, ưu tiên ngày gần (chỉ thống kê, không đảm bảo trúng).
        """
    )

    col1, col2 = st.columns(2)
    with col1:
        date_pick = st.date_input("Chọn ngày dữ liệu cuối cùng", value=datetime.date.today())
    with col2:
        days_hist = st.slider("Số ngày lịch sử", 3, 30, 7)

    col3, col4 = st.columns(2)
    with col3:
        decay = st.slider("Trọng số giảm dần (gần ngày ưu tiên)", 0.5, 0.99, 0.9, step=0.01)
    with col4:
        top_k = st.slider("Top số hiển thị", 3, 15, 5)

    col5, col6 = st.columns(2)
    with col5:
        use_cache = st.checkbox("Dùng cache", value=True)
    with col6:
        force_refresh = st.checkbox("Làm mới dữ liệu ngày chọn", value=False)

    col7, col8 = st.columns(2)
    with col7:
        show_today_full = st.checkbox("Hiển thị kết quả đầy đủ ngày chọn", value=False)
    with col8:
        show_today_last2 = st.checkbox("Hiển thị 2 chữ số cuối ngày chọn", value=False)

    if st.button("Lấy dữ liệu & gợi ý cho ngày tiếp theo"):
        today_raw = None
        try:
            with st.spinner("Đang lấy dữ liệu..."):
                today_raw = fetch_xsmb(date_pick, use_cache=use_cache, force_refresh=force_refresh)
            today_result = normalize_last2(today_raw)
            if show_today_full:
                st.subheader(f"Kết quả đầy đủ {date_pick.strftime('%d-%m-%Y')}")
                st.json(today_raw)
            if show_today_last2:
                st.subheader(f"Kết quả (2 chữ số cuối) {date_pick.strftime('%d-%m-%Y')}")
                st.json(today_result)
        except Exception as e:
            st.error(f"Lỗi lấy kết quả: {e}")
            today_result = None

        history = []
        for delta in range(days_hist):
            d = date_pick - datetime.timedelta(days=delta)
            try:
                day_raw = fetch_xsmb(d, use_cache=use_cache)
                history.append(normalize_last2(day_raw))
            except Exception:
                continue

        if not history:
            st.info("Không đủ dữ liệu lịch sử để gợi ý.")
        else:
            freq_w = aggregate_weighted(history, decay=decay)
            suggestions = suggest_numbers(freq_w, top_k=top_k)
            best_pick = suggestions[0] if suggestions else None
            st.subheader("Gợi ý 2 chữ số cho ngày tiếp theo")
            st.write(", ".join(suggestions))
            if best_pick:
                st.markdown(f"**Ưu tiên:** {best_pick}")
            st.caption("Dựa trên tần suất 2 chữ số cuối, có trọng số giảm dần theo ngày. Không phải tư vấn đánh số.")

with rule_tab:
    st.markdown(
        """
**Quy tắc thứ 2 (thử nghiệm):**
- Lấy ngày thứ 2 của tuần, lấy chữ số **hàng nghìn** của Giải Nhất (G1) làm mốc.
- Sinh ra 10 số (2 chữ số) kết thúc bằng chữ số mốc đó.
- Dự đoán ngày trong tuần có thể xuất hiện dựa trên thống kê lịch sử (2 chữ số cuối Giải ĐB) chứa chữ số mốc ở hàng đơn vị.
        """
    )

    anchor_date = st.date_input(
        "Chọn thứ 2 làm mốc", value=(datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday()))
    )
    hist_days = st.slider("Số ngày lịch sử để thống kê", 7, 90, 30)
    hist_weeks = st.slider("Số tuần lịch sử để ước tính tuần có xuất hiện", 4, 52, 12)

    if st.button("Phân tích quy tắc tìm số đề"):
        try:
            anchor_raw = fetch_xsmb(anchor_date)
            anchor_g1 = anchor_raw.get("G1", [])
            if not anchor_g1:
                st.error("Không có dữ liệu Giải Nhất ngày mốc")
            else:
                anchor_digit = anchor_g1[0][-4] if len(anchor_g1[0]) >= 4 else anchor_g1[0][0]
                st.write(f"Chữ số mốc (hàng nghìn G1 ngày {anchor_date:%d-%m-%Y}): **{anchor_digit}**")

            candidates = [f"{t}{anchor_digit}" for t in range(10)]
            st.subheader("10 số (2 chữ số) kết thúc bằng mốc")
            st.write(", ".join(candidates))

            # Thống kê weekday cho 2 số cuối Giải ĐB nếu NẰM TRONG 10 số (kết thúc bằng mốc)
            weekday_hits = {i: 0 for i in range(7)}
            occurrences = []
            total_hits = 0
            for delta in range(hist_days):
                d = anchor_date - datetime.timedelta(days=delta + 1)
                try:
                    res = fetch_xsmb(d)
                    db = res.get("GDB", [])
                    if not db:
                        continue
                    last2 = db[0][-2:]
                    if last2 in candidates:
                        wd = d.weekday()  # 0=Mon
                        weekday_hits[wd] += 1
                        total_hits += 1
                        occurrences.append({"Ngày": d, "Thứ": wd, "2 số cuối ĐB": last2})
                except Exception:
                    continue

            # Kiểm tra tuần hiện tại (anchor_date → anchor_date+6) xem đã xuất hiện chưa
            current_week_hits = []
            for offset in range(7):
                d = anchor_date + datetime.timedelta(days=offset)
                try:
                    res = fetch_xsmb(d)
                    db = res.get("GDB", [])
                    if not db:
                        continue
                    last2 = db[0][-2:]
                    if last2 in candidates:
                        current_week_hits.append({"Ngày": d, "Thứ": d.weekday(), "2 số cuối ĐB": last2})
                except Exception:
                    continue

            wd_names = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

            if total_hits == 0:
                st.info("Không có mẫu trùng mốc trong dữ liệu lịch sử đã chọn.")
            else:
                rows = [
                    {"Thứ": wd_names[i], "Số lần trùng (2 số cuối ĐB thuộc 10 số mốc)": weekday_hits[i]}
                    for i in range(7)
                ]
                st.subheader("Thống kê lịch sử (2 số cuối ĐB) nằm trong 10 số mốc")
                st.table(rows)

                st.subheader("Các lần xuất hiện (trong lịch sử)")
                st.table(
                    [
                        {"Ngày": oc["Ngày"].strftime('%d-%m-%Y'), "Thứ": wd_names[oc["Thứ"]], "2 số cuối ĐB": oc["2 số cuối ĐB"]}
                        for oc in sorted(occurrences, key=lambda x: x["Ngày"], reverse=True)
                    ]
                )

            if current_week_hits:
                st.subheader("Tuần hiện tại: đã xuất hiện")
                st.table(
                    [
                        {"Ngày": h["Ngày"].strftime('%d-%m-%Y'), "Thứ": wd_names[h["Thứ"]], "2 số cuối ĐB": h["2 số cuối ĐB"]}
                        for h in sorted(current_week_hits, key=lambda x: x["Ngày"], reverse=True)
                    ]
                )
            else:
                st.info("Tuần hiện tại: chưa thấy 2 số cuối ĐB thuộc 10 số mốc.")

            # Ước tính xác suất tuần có xuất hiện (dựa trên hist_weeks tuần quá khứ)
            week_hits = 0
            for w in range(hist_weeks):
                week_start = anchor_date - datetime.timedelta(days=7 * (w + 1))
                week_end = week_start + datetime.timedelta(days=6)
                hit_week = False
                for delta in range(7):
                    d = week_start + datetime.timedelta(days=delta)
                    try:
                        res = fetch_xsmb(d)
                        db = res.get("GDB", [])
                        if db and db[0][-2:] in candidates:
                            hit_week = True
                            break
                    except Exception:
                        continue
                if hit_week:
                    week_hits += 1
            prob = week_hits / hist_weeks if hist_weeks > 0 else 0
            st.subheader("Xác suất tuần có xuất hiện (ước tính)")
            st.write(f"Trong {hist_weeks} tuần gần nhất: {week_hits} tuần có xuất hiện ⇒ xác suất lịch sử ~ {prob:.0%}")

            # Gợi ý cho các ngày còn lại trong tuần hiện tại (chỉ nếu tuần mốc là tuần hiện tại)
            start_week = anchor_date
            end_week = anchor_date + datetime.timedelta(days=6)
            today = datetime.date.today()
            is_current_week = start_week <= today <= end_week

            if is_current_week and any(weekday_hits.values()):
                best_wd_overall = max(weekday_hits, key=weekday_hits.get)
                today_wd = today.weekday()
                remaining = [d for d in range(today_wd, 7)]
                ordered = sorted(range(7), key=lambda i: (-weekday_hits[i], i))
                pick_wd = None
                for cand in ordered:
                    if cand in remaining and weekday_hits[cand] > 0:
                        pick_wd = cand
                        break
                if pick_wd is None and weekday_hits[best_wd_overall] > 0 and best_wd_overall in remaining:
                    pick_wd = best_wd_overall
                if pick_wd is not None:
                    st.success(
                        f"Gợi ý tuần này (các ngày còn lại): ưu tiên {wd_names[pick_wd]} (dựa trên lịch sử {hist_days} ngày; khả năng tuần có xuất hiện ≈ {prob:.0%})."
                    )
        except Exception as e:
            st.error(f"Lỗi phân tích: {e}")

st.divider()
st.caption("Nguồn: minhngoc.net.vn (chính), xoso.com.vn (dự phòng). Nếu nguồn đổi cấu trúc, cần chỉnh parser. Có retry + cache.")


# -------- Minimal self-test (manual) ---------
if __name__ == "__main__":
    # Quick sanity checks (does not hit network)
    sample = {"G1": ["12345", "00001"], "GDB": ["99999"]}
    assert normalize_last2(sample) == {"G1": ["45", "01"], "GDB": ["99"]}
    freq = aggregate_weighted([normalize_last2(sample)], decay=0.9)
    assert freq.get("45") and freq.get("01") and freq.get("99")
    print("Self-test OK (no network).")
