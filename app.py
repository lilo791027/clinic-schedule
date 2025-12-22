import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import re

# ==========================================
# 1. 頁面與全域設定
# ==========================================
st.set_page_config(page_title="診所行政智能排班", layout="wide", page_icon="🏥")

st.markdown("""
    <style>
    .stDataFrame {border: 1px solid #f0f2f6; border-radius: 8px;}
    .stSuccess {background-color: #d4edda; color: #155724;}
    .stWarning {background-color: #fff3cd; color: #856404;}
    </style>
""", unsafe_allow_html=True)

st.title("🏥 診所行政智能排班系統")

with st.sidebar:
    st.header("🔧 工具箱")
    if st.button("🔄 重置所有狀態", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    st.info("""
    **規則說明：**
    - 🏥 **立丞診所**：
        - 午診：**14:00** 開始，結束依實際時間。
    - 🏥 **其他診所**：
        - 午診：**15:00-18:00** 固定。
    - 🔴 **變更機制**：僅在「延診」時更新時間。
    """)

if 'working_df' not in st.session_state: st.session_state.working_df = None
if 'last_filename' not in st.session_state: st.session_state.last_filename = ""

# ==========================================
# 2. 通用邏輯函式
# ==========================================
def smart_date_parser(date_str):
    s = str(date_str).strip()
    if s.lower() == 'nan' or not s: return ""
    if len(s) == 7 and s.isdigit(): 
        y_roc = int(s[:3])
        return f"{y_roc + 1911}-{s[3:5]}-{s[5:]}"
    s_clean = re.sub(r'\(.*?\)', '', s).strip()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%m/%d', '%m-%d', '%Y.%m.%d'):
        try:
            dt = datetime.strptime(s_clean, fmt)
            if dt.year == 1900: dt = dt.replace(year=datetime.now().year)
            return dt.strftime('%Y-%m-%d')
        except: continue
    return s

def calculate_time_rule(raw_time_str, shift_type, clinic_name, is_pure_morning):
    """
    回傳: (修正後時間字串, 是否延診Boolean)
    """
    if not raw_time_str or str(raw_time_str).lower() == 'nan': return None, False
    try:
        t_str = str(raw_time_str).strip()
        if isinstance(raw_time_str, (datetime, pd.Timestamp)):
            t = raw_time_str
        else:
            t = datetime.strptime(t_str, "%H:%M:%S") if len(t_str.split(':')) == 3 else datetime.strptime(t_str, "%H:%M")
        
        base_date = datetime(2000, 1, 1)
        t = base_date.replace(hour=t.hour, minute=t.minute, second=0)
        new_t = t
        is_licheng = "立丞" in str(clinic_name)
        
        # 設定標準時間
        if shift_type == "早":
            std = base_date.replace(hour=13, minute=0) if is_pure_morning else base_date.replace(hour=12, minute=0)
        elif shift_type == "午":
            if not is_licheng: return "18:00", False 
            std = base_date.replace(hour=17, minute=0)
        elif shift_type == "晚":
            std = base_date.replace(hour=21, minute=0) if is_licheng else base_date.replace(hour=21, minute=30)
        
        # 判斷是否延診
        if t > std:
            new_t = t + timedelta(minutes=5)
            return new_t.strftime("%H:%M"), True
        else:
            return std.strftime("%H:%M"), False
            
    except: return None, False

# ==========================================
# 3. 頁面分頁結構
# ==========================================
tab_main, tab_tool = st.tabs(["🚀 智能排班回填 (主功能)", "📊 完診資料前處理 (工具)"])

# ==========================================
# 分頁 A: 完診資料前處理
# ==========================================
with tab_tool:
    st.header("📊 原始資料轉檔工具")
    st.markdown("請在此處上傳診所系統匯出的原始 Excel/CSV，系統會將其整理成標準格式供主功能使用。")
    
    fs = st.radio("請選擇檔案來源格式：", ("🏥 原始系統匯出檔 (標題在第4列)", "📄 標準/已處理檔 (標題在第1列)"), horizontal=True)
    default_hr = 4 if "第4列" in fs else 1
    upl = st.file_uploader("上傳完診明細 (可多檔)", type=['xlsx','xls','csv'], accept_multiple_files=True, key="tool_uploader")
    hr_idx = st.number_input("資料標題在第幾列？", min_value=1, value=default_hr) - 1
    
    if upl:
        st.subheader("📋 欄位確認")
        try:
            f1 = upl[0]; f1.seek(0)
            if f1.name.lower().endswith('.csv'): 
                try: df_s = pd.read_csv(f1, header=hr_idx, encoding='cp950', nrows=5)
                except: f1.seek(0); df_s = pd.read_csv(f1, header=hr_idx, encoding='utf-8', nrows=5)
            else: df_s = pd.read_excel(f1, header=hr_idx, nrows=5)
            
            cols = df_s.columns.astype(str).str.strip().tolist()
            c1, c2, c3 = st.columns(3)
            idx_d = next((i for i, x in enumerate(cols) if "日期" in x), 0)
            idx_s = next((i for i, x in enumerate(cols) if any(k in x for k in ["午", "班", "時"])), 1 if len(cols)>1 else 0)
            idx_t = next((i for i, x in enumerate(cols) if any(k in x for k in ["時間", "完診"])), len(cols)-1)

            with c1: d_c = st.selectbox("「日期」欄位", cols, index=idx_d, key="t_d")
            with c2: s_c = st.selectbox("「時段別」欄位", cols, index=idx_s, key="t_s")
            with c3: t_c = st.selectbox("「時間」欄位", cols, index=idx_t, key="t_t")

            if st.button("⚡ 開始轉檔", key="tool_btn"):
                res = []
                for f in upl:
                    try:
                        f.seek(0)
                        if f.name.lower().endswith('.csv'): 
                            try: h = pd.read_csv(f, header=None, nrows=1, encoding='cp950')
                            except: f.seek(0); h = pd.read_csv(f, header=None, nrows=1, encoding='utf-8')
                        else: h = pd.read_excel(f, header=None, nrows=1)
                        c_name = str(h.iloc[0,0]).strip()[:4] # 抓取 A1 作為診所名

                        f.seek(0)
                        if f.name.lower().endswith('.csv'): 
                            try: d = pd.read_csv(f, header=hr_idx, encoding='cp950')
                            except: f.seek(0); d = pd.read_csv(f, header=hr_idx, encoding='utf-8')
                        else: d = pd.read_excel(f, header=hr_idx)
                        d.columns = d.columns.astype(str).str.strip()

                        if all(x in d.columns for x in [d_c, s_c, t_c]):
                            clean = d.dropna(subset=[d_c]).copy()
                            clean[t_c] = clean[t_c].astype(str)
                            g = clean.groupby([d_c, s_c])[t_c].max().reset_index()
                            p = g.pivot(index=d_c, columns=s_c, values=t_c).reset_index()
                            p.insert(0, '診所名稱', c_name)
                            p[d_c] = p[d_c].apply(smart_date_parser)
                            res.append(p)
                    except: pass
                
                if res:
                    final = pd.concat(res, ignore_index=True)
                    st.success(f"✅ 成功處理！共 {len(res)} 個檔案。")
                    
                    o = io.BytesIO()
                    with pd.ExcelWriter(o, engine='openpyxl') as w: final.to_excel(w, index=False)
                    st.download_button("📥 下載標準完診分析檔 (Excel)", o.getvalue(), '標準完診分析檔.xlsx', type="primary")
                    st.info("💡 下載後，請切換到 **「🚀 智能排班回填」** 分頁進行下一步。")
                else:
                    st.error("處理失敗，請檢查欄位設定。")
        except: st.error("檔案預覽失敗。")


# ==========================================
# 分頁 B: 智能排班回填 (主功能)
# ==========================================
with tab_main:
    st.subheader("步驟 1：上傳排班表")
    st.caption("請直接上傳原始排班表，系統會顯示內容讓您確認。")
    uploaded_file = st.file_uploader("拖或是點擊上傳 (Excel/CSV)", type=['xlsx', 'xls', 'csv'], label_visibility="collapsed")

    if uploaded_file:
        try:
            if st.session_state.working_df is None or uploaded_file.name != st.session_state.last_filename:
                if uploaded_file.name.lower().endswith('.csv'):
                    try: df_raw = pd.read_csv(uploaded_file, encoding='utf-8', dtype=str)
                    except: uploaded_file.seek(0); df_raw = pd.read_csv(uploaded_file, encoding='cp950', dtype=str)
                else:
                    df_raw = pd.read_excel(uploaded_file, dtype=str)

                # 日期欄位正規化
                rename_dict = {}
                for col in df_raw.columns:
                    if any(x in str(col) for x in ['姓名', '編號', '班別', 'ID', 'Name']): continue
                    new_name = smart_date_parser(str(col))
                    if re.match(r'\d{4}-\d{2}-\d{2}', new_name): rename_dict[col] = new_name
                if rename_dict: df_raw = df_raw.rename(columns=rename_dict)
                
                # 自動加入「選取」欄位
                # 邏輯：預設全選 (True)，但若整列出現「醫師」則不選 (False)
                df_raw.insert(0, "✅選取", True)
                
                for idx, row in df_raw.iterrows():
                    # 掃描整列內容
                    row_content = " ".join([str(val) for val in row.values if not pd.isna(val)])
                    if "醫師" in row_content or "★" in str(row.get('姓名', '')):
                        df_raw.at[idx, "✅選取"] = False
                
                st.session_state.working_df = df_raw
                st.session_state.last_filename = uploaded_file.name

        except Exception as e:
            st.error(f"檔案讀取失敗: {e}")
            st.stop()

    # --- 顯示排班表預覽與勾選 (這是您要的表格) ---
    if st.session_state.working_df is not None:
        st.info("👇 請確認下方名單，**打勾** 代表要執行更新。醫師預設已取消勾選。")
        
        # 使用 data_editor 讓使用者可以直接勾選/取消
        edited_df = st.data_editor(
            st.session_state.working_df,
            hide_index=True,
            use_container_width=True,
            height=400,
            column_config={
                "✅選取": st.column_config.CheckboxColumn("執行?", width="small", default=True)
            }
        )
        
        # 更新 working_df 為使用者編輯後的結果
        st.session_state.working_df = edited_df

    st.divider()
    st.subheader("步驟 2：上傳完診分析檔並執行")
    
    analysis_file = st.file_uploader("上傳完診結果檔 (請先至「完診資料前處理」分頁製作)", type=['xlsx', 'xls', 'csv'], key="main_ana_uploader")

    if not analysis_file: st.stop()
    if st.session_state.working_df is None: st.warning("請先完成步驟 1。"); st.stop()

    try:
        if analysis_file.name.lower().endswith('.csv'): df_ana = pd.read_csv(analysis_file, encoding='utf-8', dtype=str)
        else: df_ana = pd.read_excel(analysis_file, dtype=str)
        
        if '診所名稱' in df_ana.columns and '日期' in df_ana.columns:
            clinics = df_ana['診所名稱'].unique().tolist()
            c1, c2, c3 = st.columns([1,2,1])
            with c1: selected_clinic = st.selectbox("選擇診所", clinics)
            with c2: 
                st.write(""); st.write("")
                run_btn = st.button("🚀 開始智能回填", type="primary", use_container_width=True)

            if run_btn:
                # 篩選出使用者勾選的 Rows
                target_rows = st.session_state.working_df[st.session_state.working_df["✅選取"] == True]
                
                df_target = df_ana[df_ana['診所名稱'] == selected_clinic]
                ana_cols = df_ana.columns.tolist()
                col_m = next((c for c in ana_cols if "早" in c), None)
                col_a = next((c for c in ana_cols if "午" in c), None)
                col_e = next((c for c in ana_cols if "晚" in c), None)
                
                time_map = {smart_date_parser(r['日期']): {'早': r.get(col_m), '午': r.get(col_a), '晚': r.get(col_e)} for _, r in df_target.iterrows()}

                changes_list = []
                # 取得原本的 DF 做操作，但只處理 target_rows 的 index
                df_work = st.session_state.working_df
                date_cols = [c for c in df_work.columns if re.match(r'\d{4}-\d{2}-\d{2}', str(c))]
                
                # 找出姓名欄位
                cols_list = df_work.columns.tolist()
                name_col = next((c for c in cols_list if "姓名" in c), cols_list[1]) # 0是勾選框
                is_licheng = "立丞" in str(selected_clinic)

                progress_bar = st.progress(0)
                total_rows = len(target_rows)
                current_proc = 0
                
                # 只遍歷有勾選的 Rows
                for idx, row in target_rows.iterrows():
                    current_proc += 1
                    name = row[name_col]
                    
                    # 判斷是否純早 (直接掃描該列內容)
                    row_content = " ".join([str(v) for v in row.values if not pd.isna(v)])
                    is_pure_morning = "純早" in row_content

                    for col in date_cols:
                        if col in time_map:
                            cell_val = str(row[col]).strip()
                            if cell_val and cell_val.lower() != 'nan':
                                shifts = re.split(r'[,\n\s]', cell_val)
                                has_m, has_a, has_e = False, False, False
                                for s in shifts:
                                    if not s: continue
                                    if "全" in s: has_m=True; has_a=True; has_e=True
                                    if "早" in s: has_m=True
                                    if "午" in s: has_a=True
                                    if "晚" in s: has_e=True
                                    if not any(k in s for k in ["早","午","晚","全"]):
                                        try:
                                            th = int(s.split(':')[0]) if ':' in s else int(s.split('-')[0].split(':')[0])
                                            if th < 13: has_m=True
                                            elif 13<=th<18: has_a=True
                                            elif th>=18: has_e=True
                                        except: pass

                                vals = time_map[col]
                                fm, md = calculate_time_rule(vals['早'], "早", selected_clinic, is_pure_morning)
                                fa, ad = calculate_time_rule(vals['午'], "午", selected_clinic, is_pure_morning)
                                fe, ed = calculate_time_rule(vals['晚'], "晚", selected_clinic, is_pure_morning)

                                is_any_delayed = False
                                if has_m and md: is_any_delayed = True
                                if has_a and ad: is_any_delayed = True
                                if has_e and ed: is_any_delayed = True

                                if not is_any_delayed:
                                    continue
                                
                                parts = []
                                if has_m and fm: parts.append(f"08:00-{fm}")
                                if is_licheng:
                                    if has_a and fa: parts.append(f"14:00-{fa}") 
                                    if has_e and fe: parts.append(f"18:30-{fe}")
                                else:
                                    if has_m and has_a and not has_e:
                                        if fa: parts.append(f"15:00-{fa}")
                                    elif not has_m and has_a and has_e:
                                        if fa: parts.insert(0 if not parts else len(parts), f"15:00-{fa}")
                                    elif not has_m and has_a and not has_e:
                                        if fa: parts.append(f"15:00-{fa}")
                                    elif not has_m and not has_a and has_e:
                                        if fe: parts.append(f"18:30-{fe}")
                                
                                final_val = ",".join(parts)
                                if final_val and final_val != cell_val:
                                    # 更新 session state 的資料
                                    st.session_state.working_df.at[idx, col] = final_val
                                    changes_list.append({"姓名": name, "日期": col, "原內容": cell_val, "新內容": final_val})
                    
                    progress_bar.progress(current_proc / total_rows)

                if changes_list:
                    st.success(f"🎉 成功更新 {len(changes_list)} 筆排班資料！(僅包含延診資料)")
                    with st.expander("查看更新明細"): st.dataframe(pd.DataFrame(changes_list))
                    
                    st.subheader("📥 下載更新後的排班表")
                    c_d1, c_d2, c_d3 = st.columns(3)
                    # 輸出前把「✅選取」欄位拿掉，比較乾淨
                    final_df = st.session_state.working_df.drop(columns=["✅選取"])
                    
                    with c_d1:
                        o = io.BytesIO()
                        with pd.ExcelWriter(o, engine='openpyxl') as w: final_df.to_excel(w, index=False)
                        st.download_button("Excel 檔案", o.getvalue(), '排班表_更新.xlsx', key='dl_xlsx')
                    with c_d2:
                        u = final_df.to_csv(index=False, encoding='utf-8-sig')
                        st.download_button("CSV (UTF-8)", u, '排班表_UTF8.csv', key='dl_csv_u')
                    with c_d3:
                        try:
                            c = final_df.to_csv(index=False, encoding='cp950', errors='replace')
                            st.download_button("CSV (Big5)", c, '排班表_Big5.csv', key='dl_csv_b')
                        except: st.warning("無法產生 Big5 CSV")
                else: st.warning("✅ 比對完成：所有勾選人員皆準時或提早完診，無需更新任何資料。")
    except Exception as e: st.error(f"分析錯誤: {e}")
