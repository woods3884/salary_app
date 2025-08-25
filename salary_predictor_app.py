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

st.title("🚖 給与予測アプリ")

# ====== 永続化（Railway Volume） ======
DATA_DIR = Path("/app/data")
DATA_DIR.mkdir(exist_ok=True)
CSV_PATH = DATA_DIR / "entries.csv"

# アーカイブ（15日締め）
ARCHIVE_DIR = DATA_DIR / "archive"
ARCHIVE_DIR.mkdir(exist_ok=True)

COLUMNS = ["日付", "営収", "出庫時刻", "帰庫時刻"]

# ====== CSV読込・保存 ======
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

# ====== 一覧・編集 ======
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

# ====== 集計 ======
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

# ====== CSVから歩合給テーブル読込 ======
try:
    rate_df = pd.read_csv("稼高水準別基準額と歩率.csv")
    rate_df = rate_df.dropna()
    rate_table = dict(zip(rate_df.iloc[:,0], rate_df.iloc[:,1]))  # {稼高: 基準額}
except Exception as e:
    st.error(f"歩合給テーブルのCSV読込に失敗しました: {e}")
    rate_table = {}

# ====== 給与計算 ======
total_sales = int(df["営収"].sum()) if not df.empty else 0
night_hours = float(df["深夜時間(h)"].sum()) if "深夜時間(h)" in df else 0.0
over_hours  = float(df["超過時間(h)"].sum())  if "超過時間(h)" in df  else 0.0

# 最低稼高から反映
thresholds = sorted(rate_table.items(), key=lambda x: x[0])
base_pay = thresholds[0][1] if thresholds else 0
for thr, amt in thresholds:
    if total_sales >= thr:
        base_pay = amt
    else:
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
st.success(f"👉 手取り金額：¥{take_home:,}")

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
