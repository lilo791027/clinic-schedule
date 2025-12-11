import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import re

st.set_page_config(page_title="診所行政綜合工具", layout="wide")
st.title("🏥 診所行政綜合工具箱")

tab1, tab2 = st.tabs(["📅 排班修改工具 (單檔)", "⏱️ 完診分析 (雙向規則修正版)"])

# ==========================================
# 分頁 1: 排班修改工具 (維持不變)
# ==========================================
with tab1:
    st.header("排班表格式修正與批次設定")
    st.markdown("### 🚀 功能：單檔上傳 ➔ 格式標準化 ➔ 批次排班")

    if 'schedule_queue' not in st.session_state:
        st.session_state.schedule_queue = []

    uploaded_file = st.file_uploader("請上傳排班表 (單一檔案)", type=['xlsx', 'xls', 'csv'], key="tab1_uploader")

    if uploaded_file is not None:
        try:
            if uploaded_file.name.lower().endswith('.csv'):
                try:
                    df = pd.read_csv(uploaded_file, encoding='utf-8', dtype=str)
                except UnicodeDecodeError:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, encoding='cp950', dtype=str)
            else:
                df = pd.read_excel(uploaded_file, dtype=str)

            rename_dict = {}
            for col in df.columns:
                col_str = str(col).strip()
                if any(x in col_str for x in ['姓名', '編號', '班別', 'ID']): continue
                try:
                    date_obj = pd.to_datetime(col_str, errors='coerce')
                    if not pd.isna(date_obj):
                        new_name = date_obj.strftime('%Y-%m-%d')
                        if new_name != col_str: rename_dict[col] = new_name
                except: pass
            if rename_dict: df = df.rename(columns=rename_dict)
            
            all_columns = df.columns.tolist()

            with st.expander("⚙️ 欄位設定", expanded=True):
                c1, c2 = st.columns(2)
                with c1:
                    default_name = next((c for c in all_columns if "姓名" in c), all_columns[1] if len(all_columns)>1 else all_columns[0])
                    name_col = st.selectbox("姓名欄位：", all_columns, index=all_columns.index(default_name))
                with c2:
                    default_id = next((c for c in all_columns if "編號" in c), "(不修正)")
                    id_idx = 0
                    if default_id in all_columns: id_idx = all_columns.index(default_id) + 1
                    id_col = st.selectbox("員工編號欄位：", ["(不修正)"] + all_columns, index=id_idx)

                if id_col != "(不修正)":
                    def force_fix_id(val):
                        s = str(val).strip()
                        if s.lower() == 'nan' or s == '': return ""
                        if '.' in s: s = s.split('.')[0]
                        return s.zfill(4)
                    df[id_col] = df[id_col].apply(force_fix_id)

            if name_col:
                all_names = df[name_col].dropna().unique().tolist()
                date_cols = [c for c in df.columns if re.match(r'\d{4}-\d{2}-\d{2}', str(c))]
                date_cols.sort()

                st.markdown("---")
                with st.form("queue_form", clear_on_submit=False):
                    c1, c2 = st.columns([1, 1.5])
                    with c1:
                        sel_names = st.multiselect("選擇人員：", all_names)
                        sel_dates = st.multiselect("選擇日期：", options=date_cols)
                    with c2:
                        st.write("時段設定 (自動逗號分隔)")
                        def get_time_str(t): return t.strftime('%H:%M')
                        
                        cc1, cc2, cc3 = st.columns([0.2, 0.4, 0.4])
                        with cc1: e_m = st.checkbox("早", True)
                        with cc2: m_s = st.time_input("早起", datetime.strptime("08:00", "%H:%M").time(), label_visibility="collapsed")
                        with cc3: m_e = st.time_input("早迄", datetime.strptime("12:00", "%H:%M").time(), label_visibility="collapsed")
                        
                        cc1, cc2, cc3 = st.columns([0.2, 0.4, 0.4])
                        with cc1: e_a = st.checkbox("午", True)
                        with cc2: a_s = st.time_input("午起", datetime.strptime("15:00", "%H:%M").time(), label_visibility="collapsed")
                        with cc3: a_e = st.time_input("午迄", datetime.strptime("18:00", "%H:%M").time(), label_visibility="collapsed")
                        
                        cc1, cc2, cc3 = st.columns([0.2, 0.4, 0.4])
                        with cc1: e_e = st.checkbox("晚", True)
                        with cc2: e_s = st.time_input("晚起", datetime.strptime("18:30", "%H:%M").time(), label_visibility="collapsed")
                        with cc3: e_e_time = st.time_input("晚迄", datetime.strptime("21:30", "%H:%M").time(), label_visibility="collapsed")

                    add_btn = st.form_submit_button("➕ 加入清單", type="primary")

                if add_btn:
                    segs = []
                    if e_m: segs.append(f"{get_time_str(m_s)}-{get_time_str(m_e)}")
                    if e_a: segs.append(f"{get_time_str(a_s)}-{get_time_str(a_e)}")
                    if e_e: segs.append(f"{get_time_str(e_s)}-{get_time_str(e_e_time)}")
                    final_str = ",".join(segs)
                    if sel_names and sel_dates:
                        st.session_state.schedule_queue.append({"names": sel_names, "dates": sel_dates, "str": final_str})
                        st.success("已加入")
                    else: st.error("缺資料")

                if len(st.session_state.schedule_queue) > 0:
                    st.markdown("---")
                    prev_data = [{"人員": ",".join(i['names']), "日期數": len(i['dates']), "時間": i['str']} for i in st.session_state.schedule_queue]
                    st.table(prev_data)
                    c_a, c_b = st.columns([1, 4])
                    if c_a.button("🗑️ 清空"):
                        st.session_state.schedule_queue = []
                        st.rerun()
                    if c_b.button("🚀 執行", type="primary"):
                        final_df = df.copy()
                        for task in st.session_state.schedule_queue:
                            mask = final_df[name_col].isin(task['names'])
                            for d in task['dates']:
                                if d in final_df.columns:
                                    final_df[d] = final_df[d].astype(str)
                                    final_df.loc[mask, d] = task['str']
                        
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            out = io.BytesIO()
                            with pd.ExcelWriter(out, engine='openpyxl') as w: final_df.to_excel(w, index=False)
                            st.download_button("Excel", out.getvalue(), '排班.xlsx')
                        with c2:
                            import csv
                            try:
                                csv_b = final_df.to_csv(index=False, encoding='cp950', errors='replace', quoting=csv.QUOTE_ALL)
                                st.download_button("Big5 CSV", csv_b, '排班_Big5.csv', 'text/csv')
                            except: pass
                        with c3:
                            csv_u = final_df.to_csv(index=False).encode('utf-8-sig')
                            st.download_button("UTF8 CSV", csv_u, '排班_UTF8.csv', 'text/csv')
        except Exception as e:
            st.error(f"讀取錯誤: {e}")


# ==========================================
# 分頁 2: 多檔完診分析 (雙向規則 + 午診過濾)
# ==========================================
with tab2:
    st.header("批次完診分析 (雙向修正版)")
    st.markdown("### 🚀 規則：早診(>12點+5分, <12點補滿) / 午診只留立丞 / 晚診分流")

    files_analyze = st.file_uploader(
        "請上傳多個時間明細表", 
        type=['xlsx', 'xls', 'csv'], 
        accept_multiple_files=True,
        key="tab2_uploader"
    )
    
    header_row_idx = st.number_input("資料標題在第幾列？(預設 4)", min_value=1, value=4, step=1) - 1

    if files_analyze:
        first_file = files_analyze[0]
        try:
            # 預讀
            first_file.seek(0)
            if first_file.name.lower().endswith('.csv'):
                try: df_sample = pd.read_csv(first_file, header=header_row_idx, encoding='cp950', nrows=5)
                except: 
                    first_file.seek(0)
                    df_sample = pd.read_csv(first_file, header=header_row_idx, encoding='utf-8', nrows=5)
            else:
                df_sample = pd.read_excel(first_file, header=header_row_idx, nrows=5)
            
            df_sample.columns = df_sample.columns.astype(str).str.strip()
            all_cols = df_sample.columns.tolist()

            st.info(f"📂 共上傳 {len(files_analyze)} 個檔案。使用「{first_file.name}」設定欄位...")

            c1, c2, c3 = st.columns(3)
            with c1:
                default_d = next((c for c in all_cols if "日期" in c), all_cols[0])
                target_date_col = st.selectbox("1. 日期欄位：", all_cols, index=all_cols.index(default_d) if default_d in all_cols else 0)
            with c2:
                default_s = next((c for c in all_cols if "午別" in c or "班別" in c or "時段" in c), all_cols[1])
                target_shift_col = st.selectbox("2. 午別(時段)欄位：", all_cols, index=all_cols.index(default_s) if default_s in all_cols else 1)
            with c3:
                default_t = next((c for c in all_cols if "時間" in c or "完診" in c), all_cols[-1])
                target_time_col = st.selectbox("3. 時間欄位：", all_cols, index=all_cols.index(default_t) if default_t in all_cols else 0)

            if st.button("🚀 開始分析與計算", type="primary"):
                all_results = []
                progress_bar = st.progress(0)

                for i, file in enumerate(files_analyze):
                    try:
                        # 1. 讀診所名
                        file.seek(0)
                        if file.name.lower().endswith('.csv'):
                            try: df_h = pd.read_csv(file, header=None, nrows=1, encoding='cp950')
                            except: 
                                file.seek(0)
                                df_h = pd.read_csv(file, header=None, nrows=1, encoding='utf-8')
                        else:
                            df_h = pd.read_excel(file, header=None, nrows=1)
                        
                        clinic_name = str(df_h.iloc[0, 0]).strip()[:4] 

                        # 2. 讀資料
                        file.seek(0)
                        if file.name.lower().endswith('.csv'):
                            try: df_d = pd.read_csv(file, header=header_row_idx, encoding='cp950')
                            except: 
                                file.seek(0)
                                df_d = pd.read_csv(file, header=header_row_idx, encoding='utf-8')
                        else:
                            df_d = pd.read_excel(file, header=header_row_idx)

                        df_d.columns = df_d.columns.astype(str).str.strip()

                        # 3. 邏輯計算
                        req_cols = [target_date_col, target_shift_col, target_time_col]
                        if all(col in df_d.columns for col in req_cols):
                            df_clean = df_d.dropna(subset=[target_date_col]).copy()
                            df_clean[target_time_col] = df_clean[target_time_col].astype(str)
                            
                            # Group by
                            grouped = df_clean.groupby([target_date_col, target_shift_col])[target_time_col].max().reset_index()
                            
                            # Pivot
                            pivoted = grouped.pivot(index=target_date_col, columns=target_shift_col, values=target_time_col).reset_index()
                            pivoted.insert(0, '診所名稱', clinic_name)
                            pivoted['來源檔案'] = file.name
                            
                            all_results.append(pivoted)

                    except Exception as e:
                        st.error(f"❌ {file.name} 錯誤: {e}")
                    
                    progress_bar.progress((i + 1) / len(files_analyze))

                if all_results:
                    # 合併與排序
                    final_combined = pd.concat(all_results, ignore_index=True)
                    cols = final_combined.columns.tolist()
                    base_cols = ['診所名稱', target_date_col]
                    shift_cols = [c for c in cols if c not in base_cols and c != '來源檔案']
                    
                    def shift_sort_key(col_name):
                        if "早" in col_name: return 0
                        if "午" in col_name: return 1
                        if "晚" in col_name: return 2
                        return 99
                    shift_cols.sort(key=shift_sort_key)
                    
                    final_cols = base_cols + shift_cols + ['來源檔案']
                    final_combined = final_combined.reindex(columns=final_cols).fillna("")

                    # --- 修改邏輯 ---
                    df_mod = final_combined.copy()

                    def fix_time_logic_advanced(time_str, shift_type, clinic_name):
                        # 午診非立丞 -> 清空
                        if "午" in shift_type and "立丞" not in clinic_name:
                            return ""

                        if not time_str or time_str == "": return ""
                        
                        try:
                            t = datetime.strptime(str(time_str).strip(), "%H:%M")
                            new_t = t
                            changed = False
                            
                            # === 早診 (所有診所) ===
                            if "早" in shift_type:
                                # 規則 1: 超過 12:00 -> 加 5 分
                                if t > datetime.strptime("12:00", "%H:%M"):
                                    new_t = t + timedelta(minutes=5)
                                    changed = True
                                # 規則 2: 早於 12:00 -> 12:00
                                elif t < datetime.strptime("12:00", "%H:%M"):
                                    new_t = datetime.strptime("12:00", "%H:%M")
                                    changed = True
                            
                            # === 午診 (只剩立丞) ===
                            elif "午" in shift_type:
                                # 規則 1: 超過 17:00 -> 加 5 分
                                if t > datetime.strptime("17:00", "%H:%M"):
                                    new_t = t + timedelta(minutes=5)
                                    changed = True
                                # 規則 2: 早於 17:00 -> 17:00
                                elif t < datetime.strptime("17:00", "%H:%M"):
                                    new_t = datetime.strptime("17:00", "%H:%M")
                                    changed = True
                            
                            # === 晚診 ===
                            elif "晚" in shift_type:
                                if "立丞" in clinic_name:
                                    # 規則 1: 超過 21:00 -> 加 5 分
                                    if t > datetime.strptime("21:00", "%H:%M"):
                                        new_t = t + timedelta(minutes=5)
                                        changed = True
                                    # 規則 2: 早於 21:00 -> 21:00
                                    elif t < datetime.strptime("21:00", "%H:%M"):
                                        new_t = datetime.strptime("21:00", "%H:%M")
                                        changed = True
                                else:
                                    # 規則 1: 超過 21:30 -> 加 5 分
                                    if t > datetime.strptime("21:30", "%H:%M"):
                                        new_t = t + timedelta(minutes=5)
                                        changed = True
                                    # 規則 2: 早於 21:30 -> 21:30
                                    elif t < datetime.strptime("21:30", "%H:%M"):
                                        new_t = datetime.strptime("21:30", "%H:%M")
                                        changed = True

                            if changed:
                                return new_t.strftime("%H:%M")
                            else:
                                return time_str
                        except:
                            return time_str

                    for col in shift_cols:
                        df_mod[col] = df_mod.apply(lambda row: fix_time_logic_advanced(row[col], col, row['診所名稱']), axis=1)

                    st.success(f"🎉 分析完成！")
                    
                    st.subheader("📊 預覽 (上：原始 / 下：修正後)")
                    st.dataframe(final_combined.head(3), use_container_width=True)
                    st.dataframe(df_mod.head(3), use_container_width=True)

                    st.markdown("---")
                    col_org, col_mod = st.columns(2)

                    with col_org:
                        st.subheader("1. 下載原始資料")
                        out_f = io.BytesIO()
                        with pd.ExcelWriter(out_f, engine='openpyxl') as w: final_combined.to_excel(w, index=False)
                        st.download_button("📥 原始 Excel", out_f.getvalue(), '原始完診總表.xlsx')
                        csv_f = final_combined.to_csv(index=False).encode('utf-8-sig')
                        st.download_button("📥 原始 CSV", csv_f, '原始完診總表.csv', 'text/csv')

                    with col_mod:
                        st.subheader("2. 下載修正資料")
                        out_m = io.BytesIO()
                        with pd.ExcelWriter(out_m, engine='openpyxl') as w: df_mod.to_excel(w, index=False)
                        st.download_button("📥 修正 Excel", out_m.getvalue(), '修正完診總表.xlsx', type="primary")
                        csv_m = df_mod.to_csv(index=False).encode('utf-8-sig')
                        st.download_button("📥 修正 CSV", csv_m, '修正完診總表.csv', 'text/csv', type="primary")

                else:
                    st.warning("無資料產生")

        except Exception as e:
            st.error(f"預讀錯誤: {e}")
