import streamlit as st
import pandas as pd
from datetime import datetime
import io
import re

st.set_page_config(page_title="診所排班 (強力修正版)", layout="wide")
st.title("🏥 診所排班：強制日期格式 + 員工編號補 0")

# --- 初始化 Session State ---
if 'schedule_queue' not in st.session_state:
    st.session_state.schedule_queue = []

# --- 1. 上傳檔案 ---
uploaded_file = st.file_uploader("請上傳排班表", type=['xlsx', 'xls', 'csv'])

if uploaded_file is not None:
    try:
        # 1-1. 強制所有欄位讀取為字串 (保護 '0075' 不被轉成 75)
        if uploaded_file.name.lower().endswith('.csv'):
            try:
                df = pd.read_csv(uploaded_file, encoding='utf-8', dtype=str)
            except UnicodeDecodeError:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, encoding='cp950', dtype=str)
        else:
            df = pd.read_excel(uploaded_file, dtype=str)

        # 1-2. [強力修正] 日期標題標準化
        # 建立一個字典來重新命名欄位
        rename_dict = {}
        for col in df.columns:
            col_str = str(col).strip()
            # 略過姓名、編號等非日期欄位
            if any(x in col_str for x in ['姓名', '編號', '班別', 'ID']):
                continue
            
            try:
                # 嘗試解析日期 (自動處理 2025/12/1, 12-1 等各種格式)
                date_obj = pd.to_datetime(col_str, errors='coerce')
                if not pd.isna(date_obj):
                    # 成功解析，格式化為 YYYY-MM-DD
                    new_name = date_obj.strftime('%Y-%m-%d')
                    if new_name != col_str:
                        rename_dict[col] = new_name
            except:
                pass
        
        # 執行欄位改名
        if rename_dict:
            df = df.rename(columns=rename_dict)
            st.success(f"✅ 已自動修正 {len(rename_dict)} 個日期標題格式 (例如: {list(rename_dict.values())[0]})")
        
        all_columns = df.columns.tolist()

        # --- 2. 欄位設定與即時預覽 ---
        st.subheader("1. 欄位設定與修正預覽")
        
        c1, c2 = st.columns(2)
        with c1:
            # 嘗試自動抓取「姓名」
            default_name_idx = 0
            for i, col in enumerate(all_columns):
                if "姓名" in col or "Name" in col:
                    default_name_idx = i
                    break
            name_col = st.selectbox("姓名欄位：", all_columns, index=default_name_idx)

        with c2:
            # 嘗試自動抓取「編號」
            default_id_idx = 0
            for i, col in enumerate(all_columns):
                if "編號" in col or "ID" in col or "code" in col.lower():
                    default_id_idx = i + 1 # +1 因為有 (不修正) 選項
                    break
            
            id_col = st.selectbox("員工編號欄位 (修正目標)：", ["(不修正)"] + all_columns, index=default_id_idx)

        # 1-3. [強力修正] 員工編號補 0
        if id_col != "(不修正)":
            # 定義修正函數
            def force_fix_id(val):
                s = str(val).strip()
                if s.lower() == 'nan' or s == '': return ""
                # 去除 .0 (Excel 有時會讀成 75.0)
                if '.' in s:
                    s = s.split('.')[0]
                # 補 0
                return s.zfill(4)

            # 顯示修正前的前 3 筆 (讓使用者對照)
            original_sample = df[id_col].head(3).tolist()
            
            # 執行修正
            df[id_col] = df[id_col].apply(force_fix_id)
            
            # 顯示修正後的前 3 筆
            fixed_sample = df[id_col].head(3).tolist()
            
            # 預覽區塊
            st.info(f"🔧 編號修正預覽： {original_sample} ➔ **{fixed_sample}**")
            if fixed_sample and len(fixed_sample[0]) == 4:
                st.caption("✅ 確認已修正為 4 碼")

        # --- 3. 設定排班內容 ---
        if name_col:
            all_names = df[name_col].dropna().unique().tolist()
            # 抓出看起來像日期的欄位 (YYYY-MM-DD)
            date_cols = [c for c in df.columns if re.match(r'\d{4}-\d{2}-\d{2}', str(c))]
            
            st.markdown("---")
            st.subheader("2. 批次排班設定")

            with st.form("queue_form", clear_on_submit=False):
                col_info, col_time = st.columns([1, 1.5])
                
                with col_info:
                    st.markdown("#### 👤 與 📅")
                    selected_names = st.multiselect("選擇人員：", all_names)
                    
                    selected_dates = st.multiselect(
                        "選擇日期 (已修正格式)：", 
                        options=date_cols,
                        placeholder="請選擇日期..."
                    )
                    st.caption(f"已選 {len(selected_dates)} 個日期")

                with col_time:
                    st.markdown("#### ⏰ 時段 (自動逗號分隔)")
                    def get_time_str(t): return t.strftime('%H:%M')

                    # 早診
                    c1, c2, c3 = st.columns([0.2, 0.4, 0.4])
                    with c1: enable_morning = st.checkbox("早診", value=True)
                    with c2: m_start = st.time_input("早-開始", value=datetime.strptime("08:00", "%H:%M").time(), label_visibility="collapsed")
                    with c3: m_end = st.time_input("早-結束", value=datetime.strptime("12:00", "%H:%M").time(), label_visibility="collapsed")

                    # 午診
                    c1, c2, c3 = st.columns([0.2, 0.4, 0.4])
                    with c1: enable_afternoon = st.checkbox("午診", value=True)
                    with c2: a_start = st.time_input("午-開始", value=datetime.strptime("15:00", "%H:%M").time(), label_visibility="collapsed")
                    with c3: a_end = st.time_input("午-結束", value=datetime.strptime("18:00", "%H:%M").time(), label_visibility="collapsed")

                    # 晚診
                    c1, c2, c3 = st.columns([0.2, 0.4, 0.4])
                    with c1: enable_evening = st.checkbox("晚診", value=True)
                    with c2: e_start = st.time_input("晚-開始", value=datetime.strptime("18:30", "%H:%M").time(), label_visibility="collapsed")
                    with c3: e_end = st.time_input("晚-結束", value=datetime.strptime("21:30", "%H:%M").time(), label_visibility="collapsed")

                add_btn = st.form_submit_button("➕ 加入待辦清單", type="primary")

            if add_btn:
                # 組合字串
                sep = "-"
                join_c = ","
                segs = []
                if enable_morning: segs.append(f"{get_time_str(m_start)}{sep}{get_time_str(m_end)}")
                if enable_afternoon: segs.append(f"{get_time_str(a_start)}{sep}{get_time_str(a_end)}")
                if enable_evening: segs.append(f"{get_time_str(e_start)}{sep}{get_time_str(e_end)}")
                
                final_str = join_c.join(segs)

                if not selected_names or not selected_dates:
                    st.error("請選擇人員與日期")
                else:
                    st.session_state.schedule_queue.append({
                        "names": selected_names,
                        "dates": selected_dates,
                        "str": final_str
                    })
                    st.success(f"已加入 (目前 {len(st.session_state.schedule_queue)} 筆)")

            # --- 4. 執行與下載 ---
            st.markdown("---")
            if len(st.session_state.schedule_queue) > 0:
                st.subheader("3. 確認與下載")
                
                # 預覽清單
                preview_data = [{"人員": ",".join(i['names']), "日期數": len(i['dates']), "時間": i['str']} for i in st.session_state.schedule_queue]
                st.table(preview_data)

                col_do1, col_do2 = st.columns([1, 4])
                with col_do1:
                    if st.button("🗑️ 清空重來"):
                        st.session_state.schedule_queue = []
                        st.rerun()
                
                with col_do2:
                    run_btn = st.button("🚀 執行並產生檔案", type="primary")

                if run_btn:
                    # 執行修改
                    final_df = df.copy()
                    for task in st.session_state.schedule_queue:
                        mask = final_df[name_col].isin(task['names'])
                        for d in task['dates']:
                            if d in final_df.columns:
                                final_df[d] = final_df[d].astype(str) # 強制文字
                                final_df.loc[mask, d] = task['str']
                    
                    st.success("處理完成！")
                    
                    # --- 下載區 ---
                    c1, c2, c3 = st.columns(3)
                    
                    # 1. Excel (強制文字格式)
                    with c1:
                        output_xlsx = io.BytesIO()
                        # 使用 xlsxwriter 引擎可以更強硬地設定格式，但 openpyxl 比較通用
                        # 這裡我們依靠 dataframe 已經是字串的特性
                        with pd.ExcelWriter(output_xlsx, engine='openpyxl') as writer:
                            final_df.to_excel(writer, index=False)
                        st.download_button("1️⃣ 下載 Excel", output_xlsx.getvalue(), '排班結果.xlsx')

                    # 2. CSV Big5 (強制引號)
                    with c2:
                        try:
                            # quoting=1 (QUOTE_ALL) 會把所有欄位都用 "" 包起來，這能強迫 Excel 讀取時保留 0
                            import csv
                            csv_big5 = final_df.to_csv(index=False, encoding='cp950', errors='replace', quoting=csv.QUOTE_ALL)
                            st.download_button("2️⃣ 下載 Big5 CSV (推薦)", csv_big5, '排班結果_Big5.csv', 'text/csv')
                        except:
                            st.error("Big5 轉檔失敗")
                    
                    # 3. CSV UTF-8
                    with c3:
                        csv_utf8 = final_df.to_csv(index=False).encode('utf-8-sig')
                        st.download_button("3️⃣ 下載 UTF-8 CSV", csv_utf8, '排班結果_UTF8.csv', 'text/csv')

            else:
                st.info("暫無待辦事項")

    except Exception as e:
        st.error(f"系統錯誤: {e}")