import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import re
from openpyxl.styles import Alignment, PatternFill
import csv

# ==========================================
# 頁面基本設定
# ==========================================
st.set_page_config(page_title="診所排班與完診管理工具", layout="wide", page_icon="🏥")
st.title("🏥 診所排班管理與延診自動化工具 (v2.5)")

# ==========================================
# 側邊欄：匯出參數設定
# ==========================================
with st.sidebar:
    st.header("⚙️ 系統參數設定")
    st.info("匯出格式已優化為系統可直接讀取的規格。")
    
    # 1. 分隔符號設定
    sep_options = ["逗號 (,)", "換行 (Alt+Enter)", "空白 (Space)", "分號 (;)"]
    sep_option = st.selectbox("1. 多時段「分隔」符號", sep_options, index=0)
    
    # 2. 連接符號設定
    conn_options = ["減號 (-)", "波浪號 (~)", "無符號 (08001200)"]
    conn_option = st.selectbox("2. 時間「連接」符號", conn_options, index=0)

    # 符號對照表
    sep_map = {"空白 (Space)": " ", "換行 (Alt+Enter)": "\n", "逗號 (,)": ",", "分號 (;)": ";"}
    conn_map = {"減號 (-)": "-", "波浪號 (~)": "~", "無符號 (08001200)": ""}
    
    selected_sep = sep_map[sep_option]
    selected_conn = conn_map[conn_option]

    st.divider()
    if st.button("🔄 重設所有操作狀態", use_container_width=True):
        st.session_state.clear()
        st.rerun()

tab1, tab2 = st.tabs(["📅 階段二：排班自動回填", "⏱️ 階段一：完診分析偵測"])

# ==========================================
# 核心邏輯函式
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
    if pd.isna(val) or str(val).lower() == 'nan': return ""
    s = str(val)
    s = re.sub(r'[,\s\n;]*00:00-00:00[,\s\n;]*[^\s,;]*', '', s)
    s = re.sub(r'[■□▲△]', '', s)
    if not re.search(r'[A-Za-z0-9\u4e00-\u9fa5\{\}\[\]\(\)]', s):
        return ""
    return s.strip(" \n\r\t,;，")

def parse_time_obj(raw_time_str):
    if not raw_time_str or str(raw_time_str).lower() == 'nan': return None
    try:
        t_str = str(raw_time_str).strip().replace("~", "-")
        if "-" in t_str: t_str = t_str.split("-")[-1] 
        if len(t_str.split(':')) == 3:
            t = datetime.strptime(t_str, "%H:%M:%S")
        else:
            t = datetime.strptime(t_str, "%H:%M")
        return datetime(2000, 1, 1, t.hour, t.minute)
    except:
        return None

def check_is_delayed(time_obj, shift_type, clinic_name, date_str=""):
    if not time_obj: return False, ""
    base = datetime(2000, 1, 1)
    is_licheng = "立丞" in str(clinic_name)
    
    is_saturday = False
    if date_str:
        try:
            is_saturday = datetime.strptime(str(date_str).strip(), "%Y-%m-%d").weekday() == 5
        except:
            pass
    is_special_sat_clinic = any(c in str(clinic_name) for c in ["立全", "立竹", "上京"])
    
    if shift_type == "早":
        threshold = base.replace(hour=12, minute=0)
        threshold_str = "12:00"
    elif shift_type == "午":
        if is_licheng:
            threshold = base.replace(hour=17, minute=0)
            threshold_str = "17:00"
        else:
            threshold = base.replace(hour=18, minute=0)
            threshold_str = "18:00"
            if not (is_saturday and is_special_sat_clinic):
                return False, threshold_str
    elif shift_type == "晚":
        if is_licheng:
            threshold = base.replace(hour=21, minute=0)
            threshold_str = "21:00"
        else:
            threshold = base.replace(hour=21, minute=30)
            threshold_str = "21:30"
    else:
        return False, ""
            
    if threshold and time_obj > threshold:
        return True, threshold_str
    return False, threshold_str

def calculate_time_rule(raw_time_str, shift_type, clinic_name, is_special_morning=False, date_str=""):
    t = parse_time_obj(raw_time_str)
    if not t: return None
    
    base = datetime(2000, 1, 1)
    is_licheng = "立丞" in str(clinic_name)

    is_saturday = False
    if date_str:
        try:
            is_saturday = datetime.strptime(str(date_str).strip(), "%Y-%m-%d").weekday() == 5
        except:
            pass
    is_special_sat_clinic = any(c in str(clinic_name) for c in ["立全", "立竹", "上京"])

    if shift_type == "早":
        std = base.replace(hour=13, minute=0) if is_special_morning else base.replace(hour=12, minute=0)
    elif shift_type == "午":
        if is_licheng:
            std = base.replace(hour=17, minute=0)
        else:
            std = base.replace(hour=18, minute=0)
            if not (is_saturday and is_special_sat_clinic):
                return "18:00"
    elif shift_type == "晚":
        std = base.replace(hour=21, minute=0) if is_licheng else base.replace(hour=21, minute=30)
    else:
        return None

    new_t = t + timedelta(minutes=5) if t > std else std
    return new_t.strftime("%H:%M")

# ==========================================
# 分頁 1: 排班回填工具
# ==========================================
with tab1:
    st.header("1️⃣ 排班表延診自動回填")
    if 'working_df' not in st.session_state: st.session_state.working_df = None

    st.subheader("第一步：讀取原始排班表")
    uploaded_file = st.file_uploader("請上傳 Excel 或 CSV 格式之排班表", type=['xlsx', 'xls', 'csv'], key="main_uploader")

    if uploaded_file:
        if st.session_state.working_df is None:
            with st.spinner("讀取中，確保非排班欄位資料不被更動..."):
                if uploaded_file.name.lower().endswith('.csv'):
                    try: df_raw = pd.read_csv(uploaded_file, dtype=str)
                    except: 
                        uploaded_file.seek(0)
                        df_raw = pd.read_csv(uploaded_file, encoding='cp950', dtype=str)
                else:
                    df_raw = pd.read_excel(uploaded_file, dtype=str)

                rename_dict = {}
                for col in df_raw.columns:
                    new_name = smart_date_parser(str(col))
                    if re.match(r'\d{4}-\d{2}-\d{2}', new_name):
                        rename_dict[col] = new_name
                        df_raw[col] = df_raw[col].apply(ultimate_clean)
                
                if rename_dict: df_raw = df_raw.rename(columns=rename_dict)
                st.session_state.working_df = df_raw
            st.success("✅ 檔案讀取成功。")

    df = st.session_state.working_df
    if df is not None:
        date_cols = [c for c in df.columns if re.match(r'\d{4}-\d{2}-\d{2}', str(c))]
        
        with st.expander("👤 人員與屬性設定", expanded=True):
            c1, c2 = st.columns(2)
            all_cols = df.columns.tolist()
            with c1:
                default_name_col = next((c for c in all_cols if "姓名" in c), all_cols[0])
                name_col = st.selectbox("姓名欄位", all_cols, index=all_cols.index(default_name_col))
            with c2:
                id_col = st.selectbox("員工編號欄位", ["(無編號)"] + all_cols, index=0)

            morning_keywords = ["純早", "早班人", "08:00-12:00"]
            auto_detected_morning = []
            
            for _, row in df.iterrows():
                row_str = " ".join([str(val) for val in row.values if pd.notna(val)])
                if any(k in row_str for k in morning_keywords):
                    auto_detected_morning.append(row[name_col])
            
            special_morning_staff = st.multiselect("🕰️ 指定「純早班」人員 (基準為 13:00)：", options=df[name_col].unique(), default=auto_detected_morning)

        st.divider()
        st.subheader("第二步：疊加完診分析資料")
        analysis_file = st.file_uploader("請上傳完診分析結果檔 (.xlsx)", type=['xlsx', 'csv'], key="ana_uploader")

        if analysis_file:
            try:
                is_csv = analysis_file.name.lower().endswith('.csv')
                if is_csv:
                    try: df_ana = pd.read_csv(analysis_file, dtype=str)
                    except:
                        analysis_file.seek(0)
                        df_ana = pd.read_csv(analysis_file, encoding='cp950', dtype=str)
                else:
                    df_ana = pd.read_excel(analysis_file, dtype=str)
                
                clinics = df_ana['診所名稱'].unique().tolist()
                ca, cb = st.columns(2)
                with ca: target_clinic = st.selectbox("選擇要處理的診所", clinics)
                with cb: target_dates = st.multiselect("選擇日期 (不選則處理全月)", date_cols)

                if st.button("🔍 執行延診比對並修正", type="primary"):
                    df_target_ana = df_ana[df_ana['診所名稱'] == target_clinic]
                    time_map = {smart_date_parser(r['日期']): r.to_dict() for _, r in df_target_ana.iterrows()}
                    is_licheng = "立丞" in target_clinic
                    
                    changes = []
                    dates_to_run = target_dates if target_dates else date_cols
                    
                    for idx, row in df.iterrows():
                        staff_name = row[name_col]
                        row_full_text = " ".join([str(val) for val in row.values if pd.notna(val)])
                        is_excluded = any(k in row_full_text for k in ["醫師", "店長", "主管"])
                        
                        for d_col in dates_to_run:
                            t_date = smart_date_parser(d_col)
                            cell_val = str(row[d_col]).strip()
                            
                            if t_date in time_map and any(k in cell_val for k in ["早", "午", "晚", "全"]):
                                ana_data = time_map[t_date]
                                shifts_detected = []
                                if "早" in cell_val or "全" in cell_val: shifts_detected.append("早")
                                if "午" in cell_val or "全" in cell_val: shifts_detected.append("午")
                                if "晚" in cell_val or "全" in cell_val: shifts_detected.append("晚")
                                
                                formatted_segments = []
                                has_update = False
                                
                                # 1. 處理早班
                                if "早" in shifts_detected:
                                    ana_time = ana_data.get("早")
                                    fixed_end = calculate_time_rule(ana_time, "早", target_clinic, staff_name in special_morning_staff, t_date)
                                    if fixed_end:
                                        formatted_segments.append(f"08:00{selected_conn}{fixed_end} 早班")
                                        has_update = True
                                
                                # 2. 處理午晚班
                                if "午" in shifts_detected and "晚" in shifts_detected:
                                    ana_time_evening = ana_data.get("晚")
                                    start_t_午 = "14:00" if is_licheng else "15:00"
                                    fixed_end_晚 = calculate_time_rule(ana_time_evening, "晚", target_clinic, False, t_date)
                                    if fixed_end_晚:
                                        formatted_segments.append(f"{start_t_午}{selected_conn}{fixed_end_晚} 午晚班一起")
                                        has_update = True
                                elif "午" in shifts_detected:
                                    ana_time_afternoon = ana_data.get("午")
                                    start_t_午 = "14:00" if is_licheng else "15:00"
                                    fixed_end_午 = calculate_time_rule(ana_time_afternoon, "午", target_clinic, False, t_date)
                                    if fixed_end_午:
                                        formatted_segments.append(f"{start_t_午}{selected_conn}{fixed_end_午} 午班")
                                        has_update = True
                                elif "晚" in shifts_detected:
                                    ana_time_evening = ana_data.get("晚")
                                    start_t_晚 = "18:00" if is_licheng else "18:30"
                                    fixed_end_晚 = calculate_time_rule(ana_time_evening, "晚", target_clinic, False, t_date)
                                    if fixed_end_晚:
                                        formatted_segments.append(f"{start_t_晚}{selected_conn}{fixed_end_晚} 晚班")
                                        has_update = True
                                
                                if has_update:
                                    final_str = selected_sep.join(formatted_segments)
                                    if final_str != cell_val:
                                        changes.append({
                                            "✅寫入": not is_excluded,
                                            "姓名": staff_name, "日期": d_col, "原內容": cell_val, "修正後": final_str
                                        })
                    
                    if changes:
                        st.session_state.preview_changes = pd.DataFrame(changes)
                        st.success(f"偵測到 {len(changes)} 筆更新建議。")
                    else:
                        st.warning("比對完成，無須更新。")

                if 'preview_changes' in st.session_state:
                    edited_df = st.data_editor(st.session_state.preview_changes, hide_index=True, use_container_width=True)
                    if st.button("🚀 確認寫入排班記憶體"):
                        for _, r in edited_df[edited_df["✅寫入"]].iterrows():
                            match_idx = df.index[df[name_col] == r['姓名']]
                            if len(match_idx) > 0:
                                df.at[match_idx[0], r['日期']] = r['修正後']
                        st.session_state.working_df = df
                        st.success("✅ 更新成功！")
                        del st.session_state.preview_changes
                        st.rerun()

            except Exception as e:
                st.error(f"發生錯誤: {e}")

        st.divider()
        st.subheader("第三步：填補其餘空白格 (例/休假)")
        c1, c2, c3 = st.columns([1,1,2])
        with c1: sta_c = st.text_input("例假日代碼", "{sta}")
        with c2: res_c = st.text_input("休息日代碼", "{res}")
        with c3:
            st.write("")
            if st.button("🚀 執行自動填假", use_container_width=True):
                df_temp = df.copy()
                fill_count = 0
                for idx, row in df_temp.iterrows():
                    emp_id = str(row.get(id_col, "")) if id_col != "(無編號)" else ""
                    row_txt = " ".join([str(val) for val in row.values if pd.notna(val)])
                    
                    if "醫師" in row_txt or emp_id.strip().upper().startswith('P'):
                        continue
                    is_sta = True
                    for col in date_cols:
                        if not ultimate_clean(row[col]):
                            df_temp.at[idx, col] = sta_c if is_sta else res_c
                            is_sta = not is_sta
                            fill_count += 1
                st.session_state.working_df = df_temp
                st.success(f"✅ 已填補 {fill_count} 格。")
                st.rerun()

        # ==========================================
        # 🚀 匯出階段：強制純文字格式防護罩
        # ==========================================
        if st.session_state.working_df is not None:
            st.divider()
            df_final = st.session_state.working_df.copy()
            
            for col in date_cols:
                df_final[col] = df_final[col].apply(lambda x: ultimate_clean(x).replace("\n", selected_sep))
            
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='openpyxl') as writer:
                df_final.to_excel(writer, index=False, sheet_name='Sheet1')
                ws = writer.sheets['Sheet1']
                
                for row in ws.iter_rows():
                    for cell in row:
                        cell.number_format = '@'
                        cell.alignment = Alignment(wrap_text=(selected_sep == "\n"), vertical='center')
                        
            st.download_button(
                "📥 下載最終排班匯入檔 (.xlsx)", 
                out.getvalue(), 
                "排班回填完成檔.xlsx", 
                type="primary", 
                use_container_width=True
            )

# ==========================================
# 分頁 2: 完診分析工具
# ==========================================
with tab2:
    st.header("2️⃣ 完診明細批次分析與偵測")
    upload_mode = st.radio("系統來源：", ["🏥 標題在第4列", "📄 標題在第1列"], horizontal=True)
    header_row = 3 if "第4列" in upload_mode else 0
    files = st.file_uploader("批次上傳完診明細", type=['xlsx', 'csv', 'XLSX', 'CSV'], accept_multiple_files=True)
    
    if files:
        if st.button("🚀 開始批次分析", type="primary"):
            all_results = []
            for f in files:
                try:
                    f.seek(0)
                    is_csv_file = f.name.lower().endswith('.csv')
                    
                    if is_csv_file:
                        try:
                            h_info = pd.read_csv(f, header=None, nrows=1, encoding='utf-8')
                        except:
                            f.seek(0)
                            h_info = pd.read_csv(f, header=None, nrows=1, encoding='cp950')
                    else:
                        h_info = pd.read_excel(f, header=None, nrows=1)
                        
                    c_name = str(h_info.iloc[0,0]).strip()[:4]
                    
                    f.seek(0)
                    if is_csv_file:
                        try:
                            data = pd.read_csv(f, header=header_row, encoding='utf-8')
                        except:
                            f.seek(0)
                            data = pd.read_csv(f, header=header_row, encoding='cp950')
                    else:
                        data = pd.read_excel(f, header=header_row)
                        
                    data.columns = data.columns.astype(str).str.strip()
                    
                    # 🛡️ 終極防護：嚴格分流欄位，保證不重複
                    d_col = next((c for c in data.columns if "日期" in c), None)
                    
                    # 抓班別，避開單純的 "時"，使用 "班", "時段", "早", "午", "晚"
                    s_col = next((c for c in data.columns if c != d_col and any(k in c for k in ["班", "時段", "早", "午", "晚"])), None)
                    
                    # 抓時間，避開已經被抓到的 d_col 跟 s_col
                    t_col = next((c for c in data.columns if c not in [d_col, s_col] and any(k in c for k in ["完診", "時間", "下診"])), None)
                    
                    # 如果標題太怪異導致抓不到，強硬使用欄位位置避免當機
                    if not d_col and len(data.columns) > 0: d_col = data.columns[0]
                    if not s_col and len(data.columns) > 1: s_col = data.columns[1]
                    if not t_col and len(data.columns) > 2: t_col = data.columns[2]
                    
                    if d_col and s_col and t_col:
                        clean_data = data.dropna(subset=[d_col, t_col]).copy()
                        summary = clean_data.groupby([d_col, s_col])[t_col].max().reset_index()
                        pivot = summary.pivot(index=d_col, columns=s_col, values=t_col).reset_index()
                        pivot.insert(0, '診所名稱', c_name)
                        pivot[d_col] = pivot[d_col].apply(smart_date_parser)
                        new_cols = {d_col: '日期'}
                        for col in pivot.columns:
                            if "早" in col: new_cols[col] = "早"
                            elif "午" in col: new_cols[col] = "午"
                            elif "晚" in col: new_cols[col] = "晚"
                        pivot = pivot.rename(columns=new_cols)
                        all_results.append(pivot)
                except Exception as e:
                    st.error(f"檔案 {f.name} 處理失敗: {e}")
            
            if all_results:
                final_ana = pd.concat(all_results, ignore_index=True).fillna("")
                existing_cols = [c for c in ["診所名稱", "日期", "早", "午", "晚"] if c in final_ana.columns]
                final_ana = final_ana[existing_cols].sort_values(by=["診所名稱", "日期"])
                st.dataframe(final_ana, use_container_width=True)
                
                output_ana = io.BytesIO()
                with pd.ExcelWriter(output_ana, engine='openpyxl') as writer:
                    final_ana.to_excel(writer, index=False, sheet_name="完診分析")
                    ws = writer.sheets["完診分析"]
                    yellow_fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
                    for row_idx, row_data in final_ana.iterrows():
                        clinic = row_data['診所名稱']
                        t_date_str = str(row_data['日期'])
                        for col_idx, s_type in enumerate(existing_cols):
                            if s_type in ["早", "午", "晚"]:
                                time_val = row_data[s_type]
                                if time_val:
                                    t_obj = parse_time_obj(time_val)
                                    is_d, _ = check_is_delayed(t_obj, s_type, clinic, t_date_str)
                                    if is_d:
                                        ws.cell(row=row_idx+2, column=col_idx+1).fill = yellow_fill
                                        
                st.download_button("📥 下載完診分析報表", output_ana.getvalue(), "完診分析結果檔.xlsx", type="primary")
