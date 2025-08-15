# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, date as DateType, time as TimeType
from io import BytesIO
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

st.title("🚖 タクシー給与予測アプリ")

# ====== 永続化（Railway Volume） ======
DATA_DIR = Path("/app/data")
DATA_DIR.mkdir(exist_ok=True)
CSV_PATH = DATA_DIR / "entries.csv"

# アーカイブ（15日締め）
ARCHIVE_DIR = DATA_DIR / "archive"
ARCHIVE_DIR.mkdir(exist_ok=True)

COLUMNS = ["日付", "営収", "出庫時刻", "帰庫時刻"]

def load_entries():
    if CSV_PATH.exists():
        try:
            df = pd.read_csv(CSV_PATH, dtype=str).fillna("")
            df["営収"] = df["営収"].astype(int)
            return df[COLUMNS].to_dict(orient="records")
        except Exception as e:
            st.warning(f"CSV読込に失敗しました: {e}")
    return []

def save_entries(entries):
    try:
        df = pd.DataFrame(entries)
        if not df.empty:
            df = df[COLUMNS]
        df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
    except Exception as e:
        st.error(f"CSV保存に失敗しました: {e}")

# ====== ヘルパー ======
def _fmt_date(v):
    if isinstance(v, DateType): return v.strftime("%Y-%m-%d")
    return pd.to_datetime(v).date().strftime("%Y-%m-%d")

def _fmt_time(v):
    if isinstance(v, TimeType): return v.strftime("%H:%M")
    return pd.to_datetime(v).time().strftime("%H:%M")

def period_16to15(today: DateType):
    """今日を基準に直近の 16日〜翌月15日の (開始日, 終了日) を返す"""
    base = pd.Timestamp(today)
    if base.day >= 16:
        start = pd.Timestamp(base.year, base.month, 16)
        end_m = base + pd.offsets.MonthBegin(1)
        end = pd.Timestamp(end_m.year, end_m.month, 15)
    else:
        prev = base - pd.offsets.MonthBegin(1)
        start = pd.Timestamp(prev.year, prev.month, 16)
        end = pd.Timestamp(base.year, base.month, 15)
    return start.date(), end.date()

def archive_filename(start_d: DateType, end_d: DateType):
    return ARCHIVE_DIR / f"entries_{start_d.isoformat()}_{end_d.isoformat()}.csv"

# ====== セッション初期化 ======
ss = st.session_state
if "entries" not in ss:
    ss.entries = load_entries()
if "show_editor" not in ss:
    ss.show_editor = False
if "row_edit_idx" not in ss:
    ss.row_edit_idx = None  # 行別編集ターゲット

# ====== 入力フォーム ======
st.markdown("### 📋 データ入力フォーム")
with st.form("input_form"):
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        date_v = st.date_input("日付", value=datetime.today())
    with col2:
        revenue_v = st.number_input("営収（円）", min_value=0, step=1000)
    with col3:
        departure_v = st.time_input("出庫時刻", value=datetime.strptime("17:00", "%H:%M").time())
    with col4:
        return_v = st.time_input("帰庫時刻", value=datetime.strptime("03:30", "%H:%M").time())
    submitted = st.form_submit_button("➕ 追加")

if submitted:
    ss.entries.append({
        "日付": _fmt_date(date_v),
        "営収": int(revenue_v),
        "出庫時刻": _fmt_time(departure_v),
        "帰庫時刻": _fmt_time(return_v),
    })
    save_entries(ss.entries)
    st.success("追加しました。")

# ====== 一覧・行別編集／削除（エントリがあるときだけ） ======
if ss.entries:
    df_list = pd.DataFrame(ss.entries)
    st.markdown("### 📝 入力済みデータ（行ごと編集/削除）")
    for idx, row in df_list.iterrows():
        cols = st.columns([2, 2, 2, 2, 1.2, 1])
        cols[0].write(row["日付"])
        cols[1].write(f"¥{int(row['営収']):,}")
        cols[2].write(row["出庫時刻"])
        cols[3].write(row["帰庫時刻"])

        if cols[4].button("編集", key=f"edit_{idx}"):
            ss.row_edit_idx = idx
            st.rerun()

        if cols[5].button("削除", key=f"del_{idx}"):
            ss.entries.pop(idx)
            save_entries(ss.entries)
            st.success("削除しました。")
            st.rerun()

    # ── 行別編集フォーム ──
    if ss.row_edit_idx is not None and 0 <= ss.row_edit_idx < len(ss.entries):
        i = ss.row_edit_idx
        target = ss.entries[i]

        st.divider()
        st.markdown(f"#### ✏️ 行を編集（{target['日付']}）")

        _date  = pd.to_datetime(target["日付"]).date()
        _dep   = pd.to_datetime(target["出庫時刻"], format="%H:%M").time()
        _ret   = pd.to_datetime(target["帰庫時刻"], format="%H:%M").time()
        _sales = int(target["営収"])

        with st.form(f"row_edit_form_{i}", clear_on_submit=False):
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                date_ev = st.date_input("日付", value=_date, key=f"edit_date_{i}")
            with c2:
                revenue_ev = st.number_input("営収（円）", min_value=0, step=1000, value=_sales, key=f"edit_rev_{i}")
            with c3:
                departure_ev = st.time_input("出庫時刻", value=_dep, key=f"edit_dep_{i}")
            with c4:
                return_ev = st.time_input("帰庫時刻", value=_ret, key=f"edit_ret_{i}")

            save_col, cancel_col = st.columns(2)
            save_clicked = save_col.form_submit_button("✅ 保存", type="primary")
            cancel_clicked = cancel_col.form_submit_button("↩️ キャンセル")

        if save_clicked:
            ss.entries[i] = {
                "日付": _fmt_date(date_ev),
                "営収": int(revenue_ev),
                "出庫時刻": _fmt_time(departure_ev),
                "帰庫時刻": _fmt_time(return_ev),
            }
            save_entries(ss.entries)
            ss.row_edit_idx = None
            st.success("更新しました。")
            st.rerun()

        if cancel_clicked:
            ss.row_edit_idx = None
            st.info("編集をキャンセルしました。")
            st.rerun()

    # ── 一括編集グリッド（任意） ──
    st.markdown("### 🧰 一覧をまとめて編集（任意）")
    btn_cols = st.columns([1, 4])
    if not ss.show_editor:
        if btn_cols[0].button("✏️ グリッド編集を開く"):
            ss.show_editor = True
            st.rerun()
    else:
        btn_cols[0].write("編集中…（保存 or キャンセルを押してください）")
        df_edit = pd.DataFrame(ss.entries).copy()
        df_edit["日付"] = pd.to_datetime(df_edit["日付"]).dt.date
        df_edit["出庫時刻"] = pd.to_datetime(df_edit["出庫時刻"], format="%H:%M").dt.time
        df_edit["帰庫時刻"] = pd.to_datetime(df_edit["帰庫時刻"], format="%H:%M").dt.time

        edited = st.data_editor(
            df_edit, hide_index=True, use_container_width=True, num_rows="fixed",
            column_config={
                "日付": st.column_config.DateColumn("日付", format="YYYY-MM-DD"),
                "営収": st.column_config.NumberColumn("営収（円）", min_value=0, step=1000),
                "出庫時刻": st.column_config.TimeColumn("出庫時刻"),
                "帰庫時刻": st.column_config.TimeColumn("帰庫時刻"),
            },
            key="editor_grid",
        )

        save_col, cancel_col = st.columns(2)
        if save_col.button("✅ 変更を保存", type="primary"):
            ss.entries = [
                {
                    "日付": _fmt_date(r["日付"]),
                    "営収": int(r["営収"]) if pd.notna(r["営収"]) else 0,
                    "出庫時刻": _fmt_time(r["出庫時刻"]),
                    "帰庫時刻": _fmt_time(r["帰庫時刻"]),
                }
                for _, r in edited.iterrows()
            ]
            save_entries(ss.entries)
            ss.show_editor = False
            st.success("保存しました。")
            st.rerun()

        if cancel_col.button("↩️ キャンセル"):
            ss.show_editor = False
            st.info("編集を破棄しました。")
            st.rerun()

# ====== 集計（常に安全に計算） ======
df = pd.DataFrame(ss.entries).copy()
if not df.empty:
    df["深夜時間(h)"], df["超過時間(h)"] = 0.0, 0.0
    for i, row in df.iterrows():
        out_time = datetime.strptime(f"{row['日付']} {row['出庫時刻']}", "%Y-%m-%d %H:%M")
        in_time = datetime.strptime(f"{row['日付']} {row['帰庫時刻']}", "%Y-%m-%d %H:%M")
        if in_time <= out_time:
            in_time += timedelta(days=1)
        total_hours = (in_time - out_time).total_seconds() / 3600.0

        night_h = 0.0
        current = out_time
        while current < in_time:
            if current.hour >= 22 or current.hour < 5:
                nxt = min(current + timedelta(minutes=30), in_time)
                night_h += (nxt - current).total_seconds() / 3600.0
            current += timedelta(minutes=30)

        over_h = max(0.0, total_hours - 9.0)
        df.at[i, "深夜時間(h)"] = round(night_h, 2)
        df.at[i, "超過時間(h)"] = round(over_h, 2)

st.markdown("### 📊 入力済みデータ")
st.dataframe(df if not df.empty else pd.DataFrame(columns=COLUMNS + ["深夜時間(h)", "超過時間(h)"]),
             use_container_width=True)

# ====== 給与計算（dfが空でも0で表示） ======
total_sales = int(df["営収"].sum()) if not df.empty else 0
night_hours = float(df["深夜時間(h)"].sum()) if "深夜時間(h)" in df else 0.0
over_hours  = float(df["超過時間(h)"].sum())  if "超過時間(h)" in df  else 0.0

rate_table = {
    900000: 508712, 850000: 471015, 800000: 438359, 750000: 404286,
    700000: 369718, 650000: 329678, 600000: 288907, 550000: 252054,
    500000: 211921, 450000: 170255, 400000: 122505
}
base_pay = 0
for thr, amt in sorted(rate_table.items(), reverse=True):
    if total_sales >= thr:
        base_pay = amt
        break

night_pay = int(night_hours * 600)
over_pay  = int(over_hours * 250)
total_pay = base_pay + night_pay + over_pay
deduction = int(total_pay * 0.115)
take_home = total_pay - deduction

st.markdown("### 💰 給与予測結果")
st.write(f"総営収：¥{total_sales:,}")
st.write(f"歩合給（基準額）：¥{base_pay:,}")
st.write(f"深夜手当：¥{night_pay:,}（{night_hours:.1f}時間）")
st.write(f"超過手当：¥{over_pay:,}（{over_hours:.1f}時間）")
st.write(f"支給合計：¥{total_pay:,}")
st.write(f"控除（11.5%）：¥{deduction:,}")
st.success(f"👉 手取り見込み：¥{take_home:,}")

# ====== 15日締め：保存してクリア（常に表示） ======
st.markdown("### 🗂 15日締め（保存してクリア）")
today = datetime.today().date()
p_start, p_end = period_16to15(today)
st.caption(f"対象期間: {p_start} ～ {p_end}（毎月16日開始〜翌月15日締め）")

df_entries = pd.DataFrame(ss.entries)
if not df_entries.empty:
    df_entries["日付_dt"] = pd.to_datetime(df_entries["日付"]).dt.date
    mask = (df_entries["日付_dt"] >= p_start) & (df_entries["日付_dt"] <= p_end)
    df_to_save = df_entries.loc[mask, COLUMNS]
else:
    mask = pd.Series([], dtype=bool)
    df_to_save = pd.DataFrame(columns=COLUMNS)

colA, colB = st.columns([1.4, 2])
do_close = colA.button("📦 この期間を保存してクリア")
if do_close:
    if df_to_save.empty:
        st.warning("対象期間のデータがありません。保存は行いませんでした。")
    else:
        out_path = archive_filename(p_start, p_end)
        df_to_save.to_csv(out_path, index=False, encoding="utf-8-sig")
        # 対象分のみ削除
        remain = df_entries.loc[~mask, COLUMNS].to_dict(orient="records") if not df_entries.empty else []
        ss.entries = remain
        save_entries(ss.entries)
        st.success(f"保存しました：{out_path.name}。対象分をクリアしました。")
        st.rerun()

st.markdown("#### 📚 アーカイブ一覧")
arch_files = sorted(ARCHIVE_DIR.glob("entries_*.csv"))
if not arch_files:
    st.caption("まだアーカイブはありません。")
else:
    for p in arch_files[::-1]:
        with open(p, "rb") as f:
            st.download_button(
                label=f"⬇️ {p.name}",
                data=f.read(),
                file_name=p.name,
                mime="text/csv",
                key=f"dl_{p.name}"
            )

# ====== PDF 出力 ======
def generate_pdf(df_src, total_sales, base_pay, night_pay, night_hours, over_pay, over_hours, deduction, take_home):
    buf = BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    c.setFont('HeiseiKakuGo-W5', 12)

    c.drawString(50, height-50, "🚖 タクシー給与レポート")
    start = str(pd.to_datetime(df_src["日付"]).min().date()) if not df_src.empty else "-"
    end   = str(pd.to_datetime(df_src["日付"]).max().date()) if not df_src.empty else "-"
    c.drawString(50, height-80, f"対象期間：{start} ～ {end}")

    ypos = height-120
    c.drawString(50, ypos, f"総営収：¥{total_sales:,}"); ypos -= 20
    c.drawString(50, ypos, f"歩合給：¥{base_pay:,}"); ypos -= 20
    c.drawString(50, ypos, f"深夜手当：¥{night_pay:,}（{night_hours:.1f}h）"); ypos -= 20
    c.drawString(50, ypos, f"超過手当：¥{over_pay:,}（{over_hours:.1f}h）"); ypos -= 20
    c.drawString(50, ypos, f"控除：¥{deduction:,}"); ypos -= 20
    c.drawString(50, ypos, f"手取り見込み：¥{take_home:,}")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf

if st.button("📄 PDFレポートを生成"):
    pdf_data = generate_pdf(
        pd.DataFrame(ss.entries),
        total_sales, base_pay, night_pay, night_hours, over_pay, over_hours, deduction, take_home
    )
    st.download_button("⬇️ ダウンロード", data=pdf_data, file_name="salary_report.pdf", mime="application/pdf")
