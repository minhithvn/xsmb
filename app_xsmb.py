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


def build_transitions(days: List[Dict[str, List[str]]]) -> Dict[str, Dict[str, int]]:
    """Build transition counts between consecutive days for 2-digit numbers."""
    trans: Dict[str, Dict[str, int]] = {}
    for i in range(len(days) - 1):
        src_day = days[i]
        dst_day = days[i + 1]
        src_nums = set(n for arr in src_day.values() for n in arr)
        dst_nums = [n for arr in dst_day.values() for n in arr]
        for s in src_nums:
            trans.setdefault(s, {})
            for d in dst_nums:
                trans[s][d] = trans[s].get(d, 0) + 1
    return trans


def predict_next_from_transitions(trans: Dict[str, Dict[str, int]], today_nums: List[str], exclude_today: bool = False) -> List[str]:
    scores: Dict[str, int] = {}
    today_set = set(today_nums)
    for s in today_nums:
        for d, c in trans.get(s, {}).items():
            if exclude_today and d in today_set:
                continue
            scores[d] = scores.get(d, 0) + c
    return [n for n, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]


def combine_ensemble(freq_scores: Dict[str, float], trans_scores: Dict[str, int], alpha: float = 0.5, exclude_set=None) -> List[str]:
    if exclude_set is None:
        exclude_set = set()
    all_keys = set(freq_scores.keys()) | set(trans_scores.keys())
    combined: Dict[str, float] = {}
    for k in all_keys:
        if k in exclude_set:
            continue
        f = freq_scores.get(k, 0.0)
        t = trans_scores.get(k, 0)
        combined[k] = alpha * f + (1 - alpha) * t
    return [n for n, _ in sorted(combined.items(), key=lambda kv: (-kv[1], kv[0]))]


# -------- Streamlit UI ---------
st.set_page_config(page_title="XSMB Checker", page_icon="🎟️", layout="centered")
st.title("XS Miền Bắc")

# Tabs
main_tab, rule_tab = st.tabs(["Gợi ý 2 số lô", "Tìm số đề đóm"])

with main_tab:
    st.markdown(
        """
- Nguồn chính: minhngoc.net.vn; dự phòng: xoso.com.vn.
- Gợi ý 2 chữ số dựa trên tần suất có trọng số (ưu tiên ngày gần). Không đảm bảo trúng.
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

    col7, col8 = st.columns(2)
    with col7:
        trans_window = st.slider("Số ngày lịch sử cho chuyển tiếp", 5, 60, 30)
    with col8:
        exclude_today_nums = st.checkbox("Loại trừ các số đã ra hôm nay khỏi gợi ý chuyển tiếp", value=True)

    col9, col10 = st.columns(2)
    with col9:
        alpha_ensemble = st.slider("Trọng số freq vs transition (alpha)", 0.0, 1.0, 0.5, step=0.05)
    with col10:
        exclude_last_days = st.slider("Loại trừ số đã ra trong X ngày gần nhất (ensemble)", 0, 3, 1)

    if st.button("Lấy dữ liệu & gợi ý ngày tiếp theo"):
        try:
            today_raw = fetch_xsmb(date_pick)
            today_norm = normalize_last2(today_raw)
            today_nums_flat = [n for arr in today_norm.values() for n in arr]
            if show_today:
                st.subheader(f"Kết quả đầy đủ {date_pick.strftime('%d-%m-%Y')}")
                st.json(today_raw)
        except Exception as e:
            st.error(f"Lỗi lấy kết quả: {e}")
            today_raw = None
            today_nums_flat = []

        # Nếu ngày chọn là hôm nay/hiện tại trở đi, hiển thị mốc dự đoán cho ngày kế tiếp
        today_real = datetime.date.today()
        if date_pick >= today_real:
            target_date = date_pick + datetime.timedelta(days=1)
            st.info(f"Dự đoán cho ngày: {target_date.strftime('%d-%m-%Y')} (dựa trên dữ liệu đến {date_pick.strftime('%d-%m-%Y')})")

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
            # Gợi ý tần suất trọng số
            freq_w = aggregate_weighted(history, decay=decay, day0_penalty=day0_penalty)
            suggestions = suggest_numbers(freq_w, top_k=top_k)
            best_pick = suggestions[0] if suggestions else None
            st.subheader("Gợi ý 2 chữ số (tần suất trọng số)")
            st.write(", ".join(suggestions))
            if best_pick:
                st.markdown(f"**Ưu tiên:** {best_pick}")
            st.caption("Gợi ý dùng 2 chữ số cuối, trọng số giảm dần theo ngày, ngày gần nhất giảm thêm hệ số (slider). Không phải tư vấn đánh số.")

            # Gợi ý theo chuyển tiếp
            trans_history = []
            for delta in range(trans_window):
                d = date_pick - datetime.timedelta(days=delta)
                try:
                    day_raw = fetch_xsmb(d)
                    trans_history.append(normalize_last2(day_raw))
                except Exception:
                    continue
            trans = build_transitions(trans_history)
            trans_scores = predict_next_from_transitions(trans, today_nums_flat, exclude_today=exclude_today_nums)
            st.subheader("Gợi ý theo chuyển tiếp (từ hôm nay sang ngày tiếp theo)")
            if trans_scores:
                st.write(", ".join(trans_scores[:5]))
                st.markdown(f"**Ưu tiên (transitions):** {trans_scores[0]}")
            else:
                st.info("Không đủ dữ liệu chuyển tiếp để gợi ý.")

            # Ensemble freq + transition
            # freq_w is a score dict; build trans score dict
            trans_score_dict = {}
            for s in today_nums_flat:
                for d, c in trans.get(s, {}).items():
                    trans_score_dict[d] = trans_score_dict.get(d, 0) + c

            exclude_set = set()
            if exclude_last_days > 0:
                for delta in range(exclude_last_days):
                    d = date_pick - datetime.timedelta(days=delta)
                    try:
                        day_raw = fetch_xsmb(d)
                        norm = normalize_last2(day_raw)
                        for arr in norm.values():
                            exclude_set.update(arr)
                    except Exception:
                        continue

            ensemble = combine_ensemble(freq_w, trans_score_dict, alpha=alpha_ensemble, exclude_set=exclude_set)
            st.subheader("Gợi ý ensemble (freq + transition)")
            if ensemble:
                st.write(", ".join(ensemble[:5]))
                st.markdown(f"**Ưu tiên (ensemble):** {ensemble[0]}")
            else:
                st.info("Không đủ dữ liệu để gợi ý ensemble.")

with rule_tab:
    st.markdown(
        """
**Quy tắc thứ 2 (thử nghiệm):**
- Lấy ngày thứ 2 của tuần, lấy chữ số **hàng nghìn** của Giải Nhất (G1) làm mốc.
- Sinh ra 10 số (2 chữ số) kết thúc bằng chữ số mốc đó.
- Dự đoán ngày trong tuần có thể xuất hiện dựa trên thống kê lịch sử (2 chữ số cuối Giải ĐB) chứa chữ số mốc ở hàng đơn vị.
        """
    )

    anchor_date = st.date_input("Chọn thứ 2 làm mốc", value=(datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())))
    hist_days = st.slider("Số ngày lịch sử để thống kê", 7, 90, 30)

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
                    d = anchor_date - datetime.timedelta(days=delta+1)
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
                    st.table([
                        {"Ngày": oc["Ngày"].strftime('%d-%m-%Y'), "Thứ": wd_names[oc["Thứ"]], "2 số cuối ĐB": oc["2 số cuối ĐB"]}
                        for oc in sorted(occurrences, key=lambda x: x["Ngày"], reverse=True)
                    ])

                    if current_week_hits:
                        st.subheader("Tuần hiện tại: đã xuất hiện")
                        st.table([
                            {"Ngày": h["Ngày"].strftime('%d-%m-%Y'), "Thứ": wd_names[h["Thứ"]], "2 số cuối ĐB": h["2 số cuối ĐB"]}
                            for h in sorted(current_week_hits, key=lambda x: x["Ngày"], reverse=True)
                        ])
                    else:
                        st.info("Tuần hiện tại: chưa thấy 2 số cuối ĐB thuộc 10 số mốc.")

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
                            st.success(f"Gợi ý tuần này (các ngày còn lại): ưu tiên {wd_names[pick_wd]} (dựa trên lịch sử {hist_days} ngày).")
                    else:
                        # Không hiển thị gợi ý tuần nếu không phải tuần hiện tại
                        pass
        except Exception as e:
            st.error(f"Lỗi phân tích: {e}")

st.divider()
st.caption("Nguồn: minhngoc.net.vn (chính), xoso.com.vn (dự phòng). Nếu nguồn đổi cấu trúc, cần chỉnh parser.")
