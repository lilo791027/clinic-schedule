import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import re
from openpyxl.styles import Alignment
import csv

# ==========================================
# 頁面基本設定
# ==========================================
st.set_page_config(page_title="診所下診時間工具", layout="wide", page_icon="🏥")
st.title("🏥 診所下診時間工具 (終極極淨版)")

# ==========================================
# 側邊欄：格式設定
# ==========================================
with st.sidebar:
    st.header("⚙️ 匯出格式設定")
    st.info("已預設為系統可讀取的「逗號分隔」格式。")
    
    # 1. 設定多時段中間用什麼隔開 (預設改為逗號)
    sep_options = ["逗號 (,)", "換行 (Alt+Enter)", "空白 (Space)", "分號 (;)"]
    sep_option = st.selectbox("1. 多時段「分隔」符號", sep_options, index=0)
    
    # 2. 設定時間中間用什麼連接
    conn_options = ["減號 (-)", "波浪號 (~)", "無符號 (08001200)"]
    conn_option = st.selectbox("2. 時間「連接」符號", conn_options, index=0)

    # 對應符號邏輯
    sep_map = {"空白 (Space)": " ", "換行 (Alt+Enter)": "\n", "逗號 (,)": ",", "分號 (;)": ";"}
    conn_map = {"減號 (-)": "-", "波浪號 (~)": "~", "無符號 (08001200)": ""}
    
    selected_sep = sep_map[sep_option]
    selected_conn = conn_map[conn_option]

    if st.button("🔄 清除所有快取與狀態"):
        st.session_state.clear()
        st.rerun()

tab1, tab2 = st.tabs(["📅 階段二：排班回填", "⏱️ 階段一：完診分析"])

# ==========================================
# 通用函式 (含終極淨化過濾器)
# ==========================================
def smart_date_parser(date_str):
    s = str(date_str).strip()
    if s.lower() == 'nan' or not s: return ""
    match = re.search(r'(\d{1,2})/(\d{1,2})', s)
    if match:
        m, d = match.groups()
        return f"{datetime.now().year}-{int(m):02d}-{int(d):02d}"
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

def ultimate_clean(val):
    """最核心的淨化函式：殺除假時間、正方形、拯救文字、消滅孤立逗號"""
    if pd.isna(val) or str(val).lower() == 'nan': return ""
    s = str(val)
    
    # 🚀 專武殺手：無情剿滅 Femas 產生的佔位時間 "00:00-00:00" 以及附帶的診所代碼 (如 上京、立全)
    # 它會抓出 ",00:00-00:00,上京" 這樣的組合並直接拔除
    s = re.sub(r'[,\s\n;]*00:00-00:00[,\s\n;]*[^\s,;]*', '', s)

    # 1. 根除正方形
    s = re.sub(r'[■□]', '', s)
    
    # 2. 如果裡面沒有中文字、英文字母或數字，直接判定為無效內容，回傳乾淨空白
    if not re.search(r'[A-Za-z0-9\u4e00-\u9fa5]', s):
        return ""
        
    # 3. 削去頭尾因轉換殘留的逗號、分號、換行與空白
    return s.strip(" \n\r\t,;，")

def final_export_clean(val, sep):
    """匯出前的最終整理，套用使用者選擇的分隔符號"""
    s = ultimate_clean(val)
    if not s: return ""
    
    # 轉換換行符號為使用者選擇的符號
    s = s.replace("\n", sep)
    
    # 防止產生 ",," 這種連續符號
    if sep != "\n" and sep != " ":
        esc_sep = re.escape(sep)
        s = re.sub(f"[{esc_sep}]+", sep, s)
        
    # 最後再削一次邊緣
    return s.strip(" \n\r\t,;，" + sep)

def parse_time_obj(raw_time_str):
    if not raw_time_str or str(raw_time_str).lower() == 'nan': return None
    try:
        t_str = str(raw_time_str).strip().replace("~", "-")
        if isinstance(raw_time_str, (datetime, pd.Timestamp)):
            t = raw_time_str
        else:
            if len(t_str.split(':')) == 3:
                t = datetime.strptime(t_str, "%H:%M:%S")
            else:
                t = datetime.strptime(t_str, "%H:%M")
        base_date = datetime(2000, 1, 1)
        return base_date.replace(hour=t.hour, minute=t.minute, second=0)
    except:
        return None

def check_is_delayed(time_obj, shift_type, clinic_name):
    if not time_obj: return False, ""
    base_date = datetime(2000, 1, 1)
    is_licheng = "立丞" in str(clinic_name)
    threshold = None
    threshold_str = ""

    if shift_type == "早":
        threshold = base_date.replace(hour=12, minute=0)
        threshold_str = "12:00"
    elif shift_type == "午":
        if is_licheng:
            threshold = base_date.replace(hour=17, minute=0)
            threshold_str = "17:00"
        else:
            threshold = base_date.replace(hour=18, minute=0)
            threshold_str = "18:00"
    elif shift_type == "晚":
        if is_licheng:
            threshold = base_date.replace(hour=21, minute=0)
            threshold_str = "21:00"
        else:
            threshold = base_date.replace(hour=21, minute=30)
            threshold_str = "21:30"
    
    if threshold and time_obj > threshold:
        return True, threshold_str
    return False, threshold_str

def calculate_time_rule(raw_time_str, shift_type, clinic_name, is_special_morning=False):
    t = parse_time_obj(raw_time_str)
    if not t: return None
    new_t = t
    base_date = datetime(2000, 1, 1)
    is_licheng = "立丞" in str(clinic_name)

    if shift_type == "早":
        std = base_date.replace(hour=13, minute=0) if is_special_morning else base_date.replace(hour=12, minute=0)
        if t > std: new_t = t + timedelta(minutes=5)
        elif t < std: new_t = std
    elif shift_type == "午":
        if not is_licheng: return "18:00"
        std = base_date.replace(hour=17, minute=0)
        if t > std: new_t = t + timedelta(minutes=5)
        else: new_t = std
    elif shift_type == "晚":
        std = base_date.replace(hour=21, minute=0) if is_licheng else base_date.replace(hour=21, minute=30)
        if t > std: new_t = t + timedelta(minutes=5)
        elif t < std: new_t = std
            
    return new_t.strftime("%H:%M")

def generate_excel_bytes(df, separator):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as w:
        df.to_excel(w, index=False)
        ws = w.sheets['Sheet1']
        for row in ws.iter_rows():
            for cell in row:
                cell.number_format = '@'
                cell.alignment = Alignment(wrap_text=(separator=="\n"), vertical='center')
    return output.getvalue()

# ==========================================
# 分頁 1: 排班修改工具
# ==========================================
with tab1:
    st.header("排班表延診回填工具")
    st.info("💡 下載的結果檔會經過精準過濾，把礙眼的「■,」或「00:00-00:00,上京」全部淨化為乾淨版。")
    
    if 'working_df' not in st.session_state: st.session_state.working_df = None
    if 'last_uploaded_filename' not in st.session_state: st.session_state.last_uploaded_filename = ""

    uploaded_file = st.file_uploader("1. 請上傳從系統匯出的【原始排班表】", type=['xlsx', 'xls', 'csv'], key="tab1_uploader")

    if uploaded_file is not None:
        try:
            if st.session_state.working_df is None or uploaded_file.name != st.session_state.last_uploaded_filename:
                if uploaded_file.name.lower().endswith('.csv'):
                    try: df_raw = pd.read_csv(uploaded_file, encoding='utf-8', dtype=str)
                    except: 
                        uploaded_file.seek(0)
                        df_raw = pd.read_csv(uploaded_file, encoding='cp950', dtype=str)
                else:
                    df_raw = pd.read_excel(uploaded_file, dtype=str)

                # 🚀 第一道防線：上傳時立刻執行「終極淨化」
                for col in df_raw.columns:
                    if re.search(r'\d{1,2}/\d{1,2}', str(col)) or re.match(r'\d{4}-\d{2}-\d{2}', str(col)):
                        df_raw[col] = df_raw[col].apply(ultimate_clean)

                rename_dict = {}
                for col in df_raw.columns:
                    if any(x in str(col) for x in ['姓名', '編號', '班別', 'ID', 'Name']): continue
                    new_name = smart_date_parser(str(col))
                    if re.match(r'\d{4}-\d{2}-\d{2}', new_name):
                        rename_dict[col] = new_name
                
                if rename_dict: df_raw = df_raw.rename(columns=rename_dict)
                st.session_state.working_df = df_raw
                st.session_state.last_uploaded_filename = uploaded_file.name
                st.success("✅ 排班表讀取成功！已自動淨化所有無意義的符號與假時間。")

            df = st.session_state.working_df

            if df is not None:
                all_columns = df.columns.tolist()
                date_cols_in_df = [c for c in df.columns if re.match(r'\d{4}-\d{2}-\d{2}', str(c)) or re.search(r'\d{1,2}/\d{1,2}', str(c))]
                
                if not date_cols_in_df:
                    excludes = ['姓名', '編號', '班別', 'ID', 'Name', '診所名稱', '來源檔案', '✅選取', 'Unnamed']
                    date_cols_in_df = [c for c in df.columns if not any(ex in str(c) for ex in excludes)]
                date_cols_in_df.sort()

                with st.expander("⚙️ 欄位與人員設定", expanded=True):
                    c1, c2 = st.columns(2)
                    with c1:
                        default_name = next((c for c in all_columns if "姓名" in c), all_columns[1] if len(all_columns)>1 else all_columns[0])
                        name_col = st.selectbox("姓名欄位：", all_columns, index=all_columns.index(default_name))
                    with c2:
                        default_id = next((c for c in all_columns if "編號" in c), "(不修正)")
                        id_idx = 0 if default_id not in all_columns else all_columns.index(default_id) + 1
                        id_col = st.selectbox("員工編號欄位：", ["(不修正)"] + all_columns, index=id_idx)
                    
                    if id_col != "(不修正)":
                        df[id_col] = df[id_col].apply(lambda x: str(x).strip().split('.')[0].zfill(4) if str(x).lower()!='nan' else "")
                        st.session_state.working_df = df

                    if name_col:
                        all_names = df[name_col].dropna().unique().tolist()
                        detected_morning_staff = []
                        keywords = ["純早"]
                        for idx, row in df.iterrows():
                            row_content = " ".join([str(val) for val in row.values if not pd.isna(val)])
                            if any(k in row_content for k in keywords):
                                if row[name_col] not in detected_morning_staff:
                                    detected_morning_staff.append(row[name_col])

                        st.markdown("---")
                        special_morning_staff = st.multiselect(
                            "🕰️ 偵測到「純早班」人員 (其早班將以 13:00 為基準)：", 
                            options=all_names,
                            default=detected_morning_staff
                        )
                    else:
                        all_names = []
                        special_morning_staff = []

                st.markdown("---")
                st.subheader("2. 請上傳已確認的【完診分析結果檔】進行比對")
                analysis_file = st.file_uploader("上傳完診報表 (Excel / CSV)", type=['xlsx', 'xls', 'csv'], key="tab1_analysis")

                if analysis_file:
                    try:
                        if analysis_file.name.lower().endswith('.csv'):
                            df_ana = pd.read_csv(analysis_file, encoding='utf-8', dtype=str)
                        else: df_ana = pd.read_excel(analysis_file, dtype=str)
                        
                        if '診所名稱' in df_ana.columns and '日期' in df_ana.columns:
                            clinics = df_ana['診所名稱'].unique().tolist()
                            c_a, c_b = st.columns(2)
                            with c_a: selected_clinic = st.selectbox("A. 選擇要套用的診所：", clinics)
                            with c_b: target_dates = st.multiselect("B. 選擇要檢查的日期 (留空即檢查全月)：", options=date_cols_in_df)

                            if st.button("🔍 產生修正預覽", type="primary"):
                                ana_cols = df_ana.columns.tolist()
                                col_m = next((c for c in ana_cols if "早" in c), None)
                                col_a = next((c for c in ana_cols if "午" in c), None)
                                col_e = next((c for c in ana_cols if "晚" in c), None)
                                
                                df_target = df_ana[df_ana['診所名稱'] == selected_clinic]
                                time_map = {smart_date_parser(r['日期']): {'早': r.get(col_m), '午': r.get(col_a), '晚': r.get(col_e)} for _, r in df_target.iterrows()}

                                changes_list = []
                                dates_to_check = target_dates if target_dates else date_cols_in_df
                                is_licheng = "立丞" in str(selected_clinic)

                                for idx, row in df.iterrows():
                                    is_special = row[name_col] in special_morning_staff
                                    row_content_str = " ".join([str(v) for v in row.values if not pd.isna(v)])
                                    is_doctor_row = "醫師" in row_content_str 

                                    for col in dates_to_check:
                                        t_date = smart_date_parser(col)
                                        if t_date in time_map:
                                            cell_val = str(row[col]).strip()
                                            
                                            # 空白或無班別關鍵字直接跳過
                                            if not any(k in cell_val for k in ["早", "午", "晚", "全", "班", ":"]):
                                                continue
                                                
                                            is_doctor_cell = "醫師" in cell_val or is_doctor_row
                                            
                                            if cell_val and cell_val.lower()!='nan':
                                                shifts = []
                                                if "早" in cell_val or "全" in cell_val: shifts.append("早")
                                                if "午" in cell_val or "全" in cell_val: shifts.append("午")
                                                if "晚" in cell_val or "全" in cell_val: shifts.append("晚")
                                                
                                                if not shifts:
                                                    times = re.findall(r'(\d{2}:\d{2})', cell_val)
                                                    for t_str in times:
                                                        t_h = int(t_str.split(':')[0])
                                                        if t_h < 13: shifts.append("早")
                                                        elif 13 <= t_h < 18: shifts.append("午")
                                                        elif t_h >= 18: shifts.append("晚")
                                                shifts = list(set(shifts))
                                                
                                                vals = time_map[t_date]
                                                final_val = cell_val
                                                has_delay = False
                                                
                                                shift_times = []
                                                
                                                for s in ["早", "午", "晚"]:
                                                    if s in shifts:
                                                        start_t = {"早": "08:00", "午": "15:00", "晚": "18:30"}[s]
                                                        if is_licheng and s == "午": start_t = "14:00"
                                                        
                                                        end_t = {"早": "12:00", "午": "18:00", "晚": "21:30"}[s]
                                                        if is_special and s == "早": end_t = "13:00"
                                                        if is_licheng and s == "午": end_t = "17:00"
                                                        if is_licheng and s == "晚": end_t = "21:00"

                                                        orig_t_str = vals.get(s)
                                                        if pd.notna(orig_t_str) and str(orig_t_str).strip().lower() != 'nan':
                                                            t_obj = parse_time_obj(orig_t_str)
                                                            if t_obj:
                                                                is_d, _ = check_is_delayed(t_obj, s, selected_clinic)
                                                                if is_d:
                                                                    has_delay = True
                                                                    fixed_t_str = calculate_time_rule(orig_t_str, s, selected_clinic, is_special)
                                                                    if fixed_t_str:
                                                                        end_t = fixed_t_str
                                                        
                                                        shift_times.append(f"{start_t}{selected_conn}{end_t}")

                                                if has_delay:
                                                    final_val = selected_sep.join(shift_times)
                                                
                                                if has_delay and final_val != cell_val:
                                                    default_execute = not (is_doctor_cell or is_special)
                                                    changes_list.append({
                                                        "✅執行": default_execute, 
                                                        "姓名": row[name_col], 
                                                        "日期": col, 
                                                        "原始內容": cell_val, 
                                                        "修正後內容": final_val
                                                    })

                                if changes_list:
                                    st.session_state['preview_df'] = pd.DataFrame(changes_list)
                                    checked_count = len([x for x in changes_list if x['✅執行']])
                                    skipped_count = len(changes_list) - checked_count
                                    st.success(f"找到 {len(changes_list)} 筆資料可更新。(醫師班預設不勾選)")
                                else: 
                                    st.session_state['preview_df'] = None
                                    st.warning("比對完畢。所有人員皆準時完診，無需更新任何班表時間。")

                            if st.session_state.get('preview_df') is not None:
                                edited = st.data_editor(st.session_state['preview_df'], hide_index=True)
                                if st.button("🚀 確認寫入記憶體"):
                                    rows = edited[edited["✅執行"]==True]
                                    for _, r in rows.iterrows():
                                        idxs = st.session_state.working_df.index[st.session_state.working_df[name_col] == r['姓名']]
                                        if len(idxs)>0: st.session_state.working_df.at[idxs[0], r['日期']] = r['修正後內容']
                                    st.success("✅ 已寫入！請點擊下方按鈕下載最終檔案。")
                                    st.session_state['preview_df'] = None
                                    st.rerun()

                    except Exception as e: st.error(f"錯誤: {e}")

            st.markdown("---")
            
            # 🚀 第二道防線：匯出前再次過濾，並套用自訂分隔符號
            if st.session_state.working_df is not None:
                df_export = st.session_state.working_df.copy()
                
                for col in date_cols_in_df:
                    df_export[col] = df_export[col].apply(lambda x: final_export_clean(x, selected_sep))
                
                data_export = generate_excel_bytes(df_export, selected_sep)
                
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.download_button(f"📥 下載 Excel 匯入檔 ({sep_option})", data_export, '排班表_含延診_準備匯入.xlsx', type="primary")
                with c2:
                    try:
                        csv_export = df_export.to_csv(index=False, encoding='cp950', errors='replace', quoting=csv.QUOTE_ALL)
                        st.download_button("📥 下載 Big5 CSV", csv_export, '排班表_含延診_準備匯入.csv', 'text/csv')
                    except: pass
                with c3:
                    u = df_export.to_csv(index=False, encoding='utf-8-sig')
                    st.download_button("📥 下載 UTF-8 CSV", u, '排班表_UTF8.csv', 'text/csv')

        except Exception as e: st.error(f"發生錯誤: {e}")

# ==========================================
# 分頁 2: 完診分析 (含延診偵測)
# ==========================================
with tab2:
    st.header("批次完診分析 & 異常偵測")
    fs = st.radio("請選擇檔案類型：", ("🏥 原始系統匯出檔 (標題在第4列)", "📄 標準/分析結果檔 (標題在第1列)"), horizontal=True)
    default_hr = 4 if "第4列" in fs else 1
    upl = st.file_uploader("上傳完診明細 (可多檔)", type=['xlsx','xls','csv'], accept_multiple_files=True, key="t2")
    hr_idx = st.number_input("資料標題在第幾列？", min_value=1, value=default_hr) - 1
    
    if upl:
        st.subheader("📋 檔案預覽")
        try:
            f1 = upl[0]; f1.seek(0)
            if f1.name.lower().endswith('.csv'): 
                try: df_s = pd.read_csv(f1, header=hr_idx, encoding='cp950', nrows=5)
                except: 
                    f1.seek(0)
                    df_s = pd.read_csv(f1, header=hr_idx, encoding='utf-8', nrows=5)
            else: df_s = pd.read_excel(f1, header=hr_idx, nrows=5)
            
            df_s.columns = df_s.columns.astype(str).str.strip()
            st.dataframe(df_s.head(3))
            
            cols = df_s.columns.tolist()
            c1, c2, c3 = st.columns(3)
            idx_d = next((i for i, x in enumerate(cols) if "日期" in x), 0)
            idx_s = next((i for i, x in enumerate(cols) if any(k in x for k in ["午", "班", "時"])), 1 if len(cols)>1 else 0)
            idx_t = next((i for i, x in enumerate(cols) if any(k in x for k in ["時間", "完診"])), len(cols)-1)

            with c1: d_c = st.selectbox("請確認「日期」欄位", cols, index=idx_d)
            with c2: s_c = st.selectbox("請確認「時段別」欄位", cols, index=idx_s)
            with c3: t_c = st.selectbox("請確認「時間」欄位", cols, index=idx_t)

            if st.button("🚀 開始分析並偵測延診", key="an_btn"):
                res = []
                bar = st.progress(0)
                error_log = []

                for i, f in enumerate(upl):
                    try:
                        f.seek(0)
                        if f.name.lower().endswith('.csv'): 
                            try: h = pd.read_csv(f, header=None, nrows=1, encoding='cp950')
                            except: 
                                f.seek(0); h = pd.read_csv(f, header=None, nrows=1, encoding='utf-8')
                        else: h = pd.read_excel(f, header=None, nrows=1)
                        c_name = str(h.iloc[0,0]).strip()[:4]

                        f.seek(0)
                        if f.name.lower().endswith('.csv'): 
                            try: d = pd.read_csv(f, header=hr_idx, encoding='cp950')
                            except: 
                                f.seek(0); d = pd.read_csv(f, header=hr_idx, encoding='utf-8')
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
                    except Exception as e: error_log.append(f"{f.name}: {e}")
                    bar.progress((i+1)/len(upl))
                
                if res:
                    final = pd.concat(res, ignore_index=True)
                    base = ['診所名稱', d_c]
                    shifts = [c for c in final.columns if c not in base]
                    def sk(n): return 0 if "早" in n else 1 if "午" in n else 2 if "晚" in n else 99
                    shifts.sort(key=sk)
                    final = final[base + shifts].fillna("")
                    final = final.sort_values(by=d_c)
                    
                    export_rows = []
                    delayed_records = []
                    col_m = next((c for c in shifts if "早" in c), None)
                    col_a = next((c for c in shifts if "午" in c), None)
                    col_e = next((c for c in shifts if "晚" in c), None)
                    
                    for idx, row in final.iterrows():
                        clinic = row['診所名稱']
                        date_val = row[d_c]
                        raw_m = str(row[col_m]).strip() if col_m and pd.notna(row[col_m]) else ""
                        raw_a = str(row[col_a]).strip() if col_a and pd.notna(row[col_a]) else ""
                        raw_e = str(row[col_e]).strip() if col_e and pd.notna(row[col_e]) else ""
                        
                        fix_m, fix_a, fix_e = "", "", ""

                        if raw_m and raw_m.lower()!='nan':
                            t = parse_time_obj(raw_m)
                            if t:
                                is_d, lim = check_is_delayed(t, "早", clinic)
                                if is_d: delayed_records.append({"日期": date_val, "診所": clinic, "班別": "早", "標準時間": lim, "實際完診": t.strftime("%H:%M"), "狀態": "⚠️ 延診"})
                                fix_m = calculate_time_rule(raw_m, "早", clinic) or raw_m
                        
                        if raw_a and raw_a.lower()!='nan':
                            t = parse_time_obj(raw_a)
                            if t:
                                is_d, lim = check_is_delayed(t, "午", clinic)
                                if is_d: delayed_records.append({"日期": date_val, "診所": clinic, "班別": "午", "標準時間": lim, "實際完診": t.strftime("%H:%M"), "狀態": "⚠️ 延診"})
                                fix_a = calculate_time_rule(raw_a, "午", clinic) or raw_a

                        if raw_e and raw_e.lower()!='nan':
                            t = parse_time_obj(raw_e)
                            if t:
                                is_d, lim = check_is_delayed(t, "晚", clinic)
                                if is_d: delayed_records.append({"日期": date_val, "診所": clinic, "班別": "晚", "標準時間": lim, "實際完診": t.strftime("%H:%M"), "狀態": "⚠️ 延診"})
                                fix_e = calculate_time_rule(raw_e, "晚", clinic) or raw_e

                        export_rows.append({
                            "診所名稱": clinic,
                            "日期": date_val,
                            "早上(原始)": raw_m if raw_m and raw_m.lower()!='nan' else "",
                            "早上": fix_m,
                            "下午(原始)": raw_a if raw_a and raw_a.lower()!='nan' else "",
                            "下午": fix_a,
                            "晚上(原始)": raw_e if raw_e and raw_e.lower()!='nan' else "",
                            "晚上": fix_e
                        })

                    df_export = pd.DataFrame(export_rows)
                    cols_order = ["診所名稱", "日期", "早上(原始)", "早上", "下午(原始)", "下午", "晚上(原始)", "晚上"]
                    df_export = df_export[cols_order]

                    st.success(f"分析完成！共處理 {len(res)} 個檔案。")
                    st.markdown("---")
                    st.subheader("🚨 延診異常偵測報告")
                    if delayed_records:
                        df_delay = pd.DataFrame(delayed_records)
                        df_delay = df_delay.sort_values(by="日期")
                        st.error(f"注意！偵測到 {len(df_delay)} 筆延診紀錄：")
                        st.dataframe(df_delay, use_container_width=True)
                    else:
                        st.success("🎉 太棒了！本批資料完全沒有延診紀錄。")
                    
                    st.markdown("---")
                    
                    def highlight_delay_rows(row):
                        styles = ['' for _ in row.index]
                        clinic = str(row['診所名稱'])
                        
                        def apply_yellow(val_str, shift_type):
                            if val_str:
                                t = parse_time_obj(val_str)
                                is_d, _ = check_is_delayed(t, shift_type, clinic)
                                if is_d: return 'background-color: #FFFF00' 
                            return ''

                        if '早上(原始)' in row.index and '早上' in row.index:
                            s = apply_yellow(row['早上(原始)'], '早')
                            if s:
                                styles[row.index.get_loc('早上(原始)')] = s
                                styles[row.index.get_loc('早上')] = s

                        if '下午(原始)' in row.index and '下午' in row.index:
                            s = apply_yellow(row['下午(原始)'], '午')
                            if s:
                                styles[row.index.get_loc('下午(原始)')] = s
                                styles[row.index.get_loc('下午')] = s

                        if '晚上(原始)' in row.index and '晚上' in row.index:
                            s = apply_yellow(row['晚上(原始)'], '晚')
                            if s:
                                styles[row.index.get_loc('晚上(原始)')] = s
                                styles[row.index.get_loc('晚上')] = s
                        
                        return styles

                    st.subheader("📥 下載分析結果")
                    o = io.BytesIO()
                    with pd.ExcelWriter(o, engine='openpyxl') as w: 
                        df_export.style.apply(highlight_delay_rows, axis=1).to_excel(w, index=False)
                    
                    st.download_button(
                        label="📥 下載完整分析報表 (.xlsx)",
                        data=o.getvalue(),
                        file_name='完診分析報表_含延診標記.xlsx',
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        type="primary"
                    )

        except Exception as e: 
            st.error(f"發生錯誤: {e}")
