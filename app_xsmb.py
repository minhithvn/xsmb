import datetime
from typing import List, Dict

import requests
import streamlit as st
from bs4 import BeautifulSoup

# -------- Config ---------
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
SOURCES = [
    "https://www.minhngoc.net.vn/ket-qua-xo-so/mien-bac/{}.html",  # dd-mm-yyyy
    "https://xoso.com.vn/xsmb-{}.html",  # dd-mm-yyyy (fallback)
]

# Prize label mapping for display order
PRIZE_LABELS = ["GDB", "G1", "G2", "G3", "G4", "G5", "G6", "G7"]


# -------- Helpers ---------
def fetch_from_minhngoc(date: datetime.date) -> Dict[str, List[str]]:
    url = SOURCES[0].format(date.strftime('%d-%m-%Y'))
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
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
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
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


def fetch_xsmb(date: datetime.date) -> Dict[str, List[str]]:
    # Try primary, then fallback
    errors = []
    for func in (fetch_from_minhngoc, fetch_from_xoso):
        try:
            return func(date)
        except Exception as e:
            errors.append(str(e))
            continue
    raise RuntimeError("; ".join(errors))


def normalize_last2(result: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Chỉ lấy 2 chữ số cuối cho mỗi số."""
    norm: Dict[str, List[str]] = {}
    for k, arr in result.items():
        norm[k] = [n[-2:].zfill(2) for n in arr if n]
    return norm


def aggregate_weighted(history: List[Dict[str, List[str]]], decay: float = 0.9, day0_penalty: float = 1.0) -> Dict[str, float]:
    """Exponential decay by day offset: weight = (decay**offset) * penalty_if_today.
    day0_penalty < 1.0 sẽ giảm ảnh hưởng của ngày gần nhất.
    """
    freq: Dict[str, float] = {}
    for offset, day in enumerate(history):
        w = (decay ** offset)
        if offset == 0:
            w *= day0_penalty
        for arr in day.values():
            for n in arr:
                freq[n] = freq.get(n, 0.0) + w
    return freq


def suggest_numbers(freq: Dict[str, float], top_k: int = 10) -> List[str]:
    sorted_nums = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [n for n, _ in sorted_nums[:top_k]]


# -------- Streamlit UI ---------
st.set_page_config(page_title="XSMB Checker", page_icon="🎟️", layout="centered")
st.title("XS Miền Bắc: kết quả & gợi ý tần suất")

st.markdown(
    """
- Nguồn chính: minhngoc.net.vn; dự phòng: xoso.com.vn.
- Gợi ý 2 chữ số dựa trên tần suất có trọng số (ưu tiên ngày gần).
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
    day0_penalty = st.slider("Giảm ảnh hưởng ngày gần nhất", 0.0, 1.0, 0.2, step=0.05)

col5, col6 = st.columns(2)
with col5:
    top_k = st.slider("Top số hiển thị", 3, 15, 5)
with col6:
    show_today = st.checkbox("Hiển thị kết quả ngày chọn (đầy đủ)", value=False)

if st.button("Lấy dữ liệu & gợi ý ngày tiếp theo"):
    try:
        today_raw = fetch_xsmb(date_pick)
        if show_today:
            st.subheader(f"Kết quả đầy đủ {date_pick.strftime('%d-%m-%Y')}")
            st.json(today_raw)
    except Exception as e:
        st.error(f"Lỗi lấy kết quả: {e}")
        today_raw = None

    history = []
    for delta in range(days_hist):
        d = date_pick - datetime.timedelta(days=delta)
        try:
            day_raw = fetch_xsmb(d)
            history.append(normalize_last2(day_raw))  # chỉ lấy 2 chữ số cho phân tích
        except Exception:
            continue

    if not history:
        st.info("Không đủ dữ liệu lịch sử để gợi ý.")
    else:
        freq_w = aggregate_weighted(history, decay=decay, day0_penalty=day0_penalty)
        suggestions = suggest_numbers(freq_w, top_k=top_k)
        best_pick = suggestions[0] if suggestions else None
        st.subheader("Gợi ý 2 chữ số cho ngày tiếp theo (dựa trên lịch sử)")
        st.write(", ".join(suggestions))
        if best_pick:
            st.markdown(f"**Ưu tiên:** {best_pick}")
        st.caption("Gợi ý dùng 2 chữ số cuối, trọng số giảm dần theo ngày, ngày gần nhất giảm thêm hệ số (slider).")

st.divider()
st.caption("Nguồn: minhngoc.net.vn (chính), Chơi vui là chính")
