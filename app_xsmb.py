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


def aggregate_frequency(history: List[Dict[str, List[str]]]) -> Dict[str, int]:
    freq: Dict[str, int] = {}
    for day in history:
        for arr in day.values():
            for n in arr:
                freq[n] = freq.get(n, 0) + 1
    return freq


def suggest_numbers(freq: Dict[str, int], top_k: int = 15) -> List[str]:
    sorted_nums = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [n for n, _ in sorted_nums[:top_k]]


# -------- Streamlit UI ---------
st.set_page_config(page_title="XSMB Checker", page_icon="🎟️", layout="centered")
st.title("XS Miền Bắc: kết quả & gợi ý tần suất")

st.markdown(
    """
- Lấy kết quả XS miền Bắc theo ngày (nguồn chính: minhngoc.net.vn; dự phòng: xoso.com.vn).
- Gợi ý số dựa trên tần suất xuất hiện (không đảm bảo trúng – chỉ thống kê).
    """
)

col1, col2 = st.columns(2)
with col1:
    date_pick = st.date_input("Chọn ngày", value=datetime.date.today())
with col2:
    days_hist = st.slider("Số ngày lịch sử để tính tần suất", 3, 30, 7)

if st.button("Lấy kết quả"):
    try:
        today_result = fetch_xsmb(date_pick)
        st.subheader(f"Kết quả {date_pick.strftime('%d-%m-%Y')}")
        st.json(today_result)
    except Exception as e:
        st.error(f"Lỗi lấy kết quả: {e}")
        today_result = None

    history = []
    for delta in range(days_hist):
        d = date_pick - datetime.timedelta(days=delta)
        try:
            history.append(fetch_xsmb(d))
        except Exception:
            continue

    if not history:
        st.info("Không đủ dữ liệu lịch sử để gợi ý.")
    else:
        freq = aggregate_frequency(history)
        suggestions = suggest_numbers(freq, top_k=15)
        best_pick = suggestions[0] if suggestions else None
        st.subheader("Gợi ý số theo tần suất (top 15)")
        st.write(", ".join(suggestions))
        if best_pick:
            st.markdown(f"**Số tần suất cao nhất:** {best_pick}")
        st.caption("Gợi ý chỉ mang tính thống kê, không phải tư vấn đánh số.")

st.divider()
st.caption("Nguồn: minhngoc.net.vn (chính), xoso.com.vn (dự phòng). Nếu nguồn đổi cấu trúc, cần chỉnh parser.")
