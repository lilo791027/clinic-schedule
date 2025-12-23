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
st.set_page_config(page_title="診所行政綜合工具", layout="wide", page_icon="🏥")
st.title("🏥 診所行政綜合工具箱 (完整版：含格式偵探)")

# ==========================================
# 側邊欄：格式偵探 & 設定
# ==========================================
with st.sidebar:
    st.header("🕵️ 格式偵探 (Format Detective)")
    st.info("如果不確定系統要什麼格式，請在此上傳「系統原本匯出且正常的檔案」，我幫您分析！")
    
    detect_file = st.file_uploader("上傳正常的排班表 (偵測用)", type=['csv', 'xlsx', 'xls'], key="detect_uploader")
    
    detected_sep = "空白 (Space)" # 預設
    detected_conn = "減號 (-)"    # 預設
    
    if detect_file is not None:
        try:
            # 讀取檔案以進行分析
            detect_file.seek(0)
            if detect_file.name.lower().endswith('.csv'):
                try: df_d = pd.read_csv(detect_file, encoding='cp950', dtype=str)
                except: 
                    detect_file.seek(0)
                    df_d = pd.read_csv(detect_file, encoding='utf-8', dtype=str)
            else:
                df_d = pd.read_excel(detect_file, dtype=str)
            
            # 尋找包含時間的格子進行分析
            found_sample = False
            for col in df_d.columns:
                for val in df_d[col].dropna():
                    val_str = str(val)
                    # 尋找看起來像時間的 (例如長度大於 10 且包含數字)
                    if len(val_str) > 10 and any(char.isdigit() for char in val_str):
                        if "\n" in val_str:
                            detected_sep = "換行 (Alt+Enter)"
                            st.success(f"🔍 偵測到：多時段使用「換行」分隔")
                        elif " " in val_str and not "\n" in val_str:
                            detected_sep = "空白 (Space)"
                            st.success(f"🔍 偵測到：多時段使用「空白」分隔")
                        
                        if "~" in val_str:
                            detected_conn = "波浪號 (~)"
                            st.success(f"🔍 偵測到：時間連接使用「波浪號 ~」")
                        elif "-" in val_str:
                            detected_conn = "減號 (-)"
                            st.success(f"🔍 偵測到：時間連接使用「減號 -」")
                        
                        st.code(f"原始內容範例:\n{repr(val_str)}", language="python")
                        found_sample = True
                        break
                if found_sample: break
            
            if not found_sample:
                st.warning("⚠️ 找不到明顯的時間資料，請手動選擇下方設定。")
                
        except Exception as e:
            st.error(f"偵測失敗: {e}")

    st.markdown("---")
    st.header("⚙️ 匯出格式設定")
    
    # 1. 設定多時段中間用什麼隔開
    sep_options = ["空白 (Space)", "換行 (Alt+Enter)", "逗號 (,)", "分號 (;)"]
    sep_index = sep_options.index(detected_sep) if detected_sep in sep_options else 0
    sep_option = st.selectbox(
        "1. 多時段「分隔」符號", 
        sep_options,
        index=sep_index
    )
    
    # 2. 設定時間中間用什麼連接
    conn_options = ["減號 (-)", "波浪號 (~)", "無符號 (08001200)"]
    conn_index = conn_options.index(detected_conn) if detected_conn in conn_options else 0
    conn_option = st.selectbox(
        "2. 時間「連接」符號", 
        conn_options,
        index=conn_index
    )

    # 對應符號邏輯
    sep_map = {"空白 (Space)": " ", "換行 (Alt+Enter)": "\n", "逗號 (,)": ",", "分號 (;)": ";"}
    conn_map = {"減號 (-)": "-", "波浪號 (~)": "~", "無符號 (08001200)": ""}
    
    selected_sep = sep_map[sep_option]
    selected_conn = conn_map[conn_option]

    if st.button("🔄 清除所有快取與狀態"):
        st.session_state.clear()
        st.rerun()

tab1, tab2 = st.tabs(["📅 排班修改工具 (整合回填版)", "⏱️ 完診分析 & 延診偵測"])

# ==========================================
# 通用函式
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

def parse_time_obj(raw_time_str):
    if not raw_time_str or str(raw_time_str).lower() == 'nan': return None
    try:
        t_str = str(raw_time_str).strip()
        t_str = t_str.replace("~", "-") # 統一處理
        
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

def format_time_range(start_str, end_str, connector):
    """根據使用者設定組合時間字串"""
    if connector == "": # 無符號模式 (08001200)
        return f"{start_str.replace(':','')}{end_str.replace(':','')}"
    return f"{start_str}{connector}{end_str}"

# ==========================================
# 分頁 1: 排班修改工具
# ==========================================
with tab1:
    st.header("排班表格式修正與管理")
    
    if 'working_df' not in st.session_state: st.session_state.working_df = None
    if 'last_uploaded_filename' not in st.session_state: st.session_state.last_uploaded_filename = ""

    uploaded_file = st.file_uploader("1. 請上傳原始排班表 (單一檔案)", type=['xlsx', 'xls', 'csv'], key="tab1_uploader")

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

                rename_dict = {}
                for col in df_raw.columns:
                    if any(x in str(col) for x in ['姓名', '編號', '班別', 'ID', 'Name']): continue
                    new_name = smart_date_parser(str(col))
                    if re.match(r'\d{4}-\d{2}-\d{2}', new_name):
                        rename_dict[col] = new_name
                
                if rename_dict: df_raw = df_raw.rename(columns=rename_dict)
                st.session_state.working_df = df_raw
                st.session_state.last_uploaded_filename = uploaded_file.name
                st.success("✅ 檔案讀取成功！")

            df = st.session_state.working_df

            if df is not None:
                all_columns = df.columns.tolist()
                date_cols_in_df = [c for c in df.columns if re.match(r'\d{4}-\d{2}-\d{2}', str(c))]
                
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
                        st.write("🕵️ **自動偵測結果：**")
                        special_morning_staff = st.multiselect(
                            "🕰️ 設定「純早班」人員 (08:00-13:00)", 
                            options=all_names,
                            default=detected_morning_staff,
                            help="選取的人員，其「早班」時段將以 13:00 為基準，且排班修正預設不勾選。"
                        )
                    else:
                        all_names = []
                        special_morning_staff = []

                st.markdown("---")
                st.subheader("2. 依照完診分析自動更新")
                st.caption(f"📍 目前設定：分隔符號=[{sep_option}]，連接符號=[{conn_option}] (可於側邊欄修改)")
                analysis_file = st.file_uploader("請上傳完診結果檔", type=['xlsx', 'xls', 'csv'], key="tab1_analysis")

                if analysis_file:
                    try:
                        if analysis_file.name.lower().endswith('.csv'):
                            df_ana = pd.read_csv(analysis_file, encoding='utf-8', dtype=str)
                        else: df_ana = pd.read_excel(analysis_file, dtype=str)
                        
                        if '診所名稱' in df_ana.columns and '日期' in df_ana.columns:
                            clinics = df_ana['診所名稱'].unique().tolist()
                            c_a, c_b = st.columns(2)
                            with c_a: selected_clinic = st.selectbox("A. 選擇診所：", clinics)
                            with c_b: target_dates = st.multiselect("B. 選擇日期 (⚠️留空即代表「自動檢查所有日期」)：", options=date_cols_in_df)

                            if st.button("🔍 產生預覽", type="primary"):
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
                                        if col in time_map:
                                            cell_val = str(row[col]).strip()
                                            is_doctor_cell = "醫師" in cell_val or is_doctor_row
                                            
                                            if cell_val and cell_val.lower()!='nan':
                                                shifts = re.split(r'[,\n\s]', cell_val)
                                                has_m, has_a, has_e = False, False, False
                                                for s in shifts:
                                                    if not s: continue
                                                    if "全" in s: has_m=has_a=has_e=True
                                                    if "早" in s: has_m=True
                                                    if "午" in s: has_a=True
                                                    if "晚" in s: has_e=True
                                                    if not any(x in s for x in ["早","午","晚","全"]):
                                                        try:
                                                            th = int(s.split(':')[0]) if ':' in s else int(s.split('-')[0].split(':')[0])
                                                            if th < 13: has_m=True
                                                            elif 13<=th<18: has_a=True
                                                            elif th>=18: has_e=True
                                                        except: pass
                                                
                                                vals = time_map[col]
                                                fm = calculate_time_rule(vals['早'], "早", selected_clinic, is_special) if has_m else None
                                                fa = calculate_time_rule(vals['午'], "午", selected_clinic) if has_a else None
                                                fe = calculate_time_rule(vals['晚'], "晚", selected_clinic) if has_e else None
                                                
                                                std_times = ["12:00", "13:00", "17:00", "18:00", "21:00", "21:30"]
                                                has_delay = False
                                                if fm and fm not in std_times: has_delay = True
                                                if fa and fa not in std_times: has_delay = True
                                                if fe and fe not in std_times: has_delay = True

                                                if is_doctor_cell or is_special:
                                                    default_execute = False
                                                elif has_delay:
                                                    default_execute = True
                                                else:
                                                    default_execute = False
                                                
                                                parts = []
                                                # 使用側邊欄設定的連接符號
                                                if has_m and fm: parts.append(format_time_range("08:00", fm, selected_conn))
                                                if is_licheng:
                                                    if has_a and fa: parts.append(format_time_range("14:00", fa, selected_conn))
                                                    if has_e and fe: parts.append(format_time_range("18:30", fe, selected_conn))
                                                else:
                                                    if has_m and has_a and not has_e:
                                                        if fa: parts.append(format_time_range("15:00", fa, selected_conn))
                                                    elif not has_m and has_a and has_e:
                                                        if fa: parts.insert(0 if not parts else len(parts), format_time_range("15:00", fa, selected_conn))
                                                    elif has_m and has_a and has_e:
                                                        pass 
                                                    elif not has_m and has_a and not has_e:
                                                        if fa: parts.append(format_time_range("15:00", fa, selected_conn))
                                                    elif not has_m and not has_a and has_e:
                                                        if fe: parts.append(format_time_range("18:30", fe, selected_conn))
                                                
                                                # 使用側邊欄設定的分隔符號
                                                final_val = selected_sep.join(parts)
                                                
                                                if final_val and final_val != cell_val:
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
                                    st.success(f"找到 {len(changes_list)} 筆資料可更新。(其中 {checked_count} 筆延診需確認，{skipped_count} 筆準時/醫師/純早班預設不勾選)")
                                else: 
                                    st.session_state['preview_df'] = None
                                    st.warning("無資料需要更新。")

                            if st.session_state.get('preview_df') is not None:
                                edited = st.data_editor(st.session_state['preview_df'], hide_index=True)
                                if st.button("🚀 確認寫入"):
                                    rows = edited[edited["✅執行"]==True]
                                    for _, r in rows.iterrows():
                                        idxs = st.session_state.working_df.index[st.session_state.working_df[name_col] == r['姓名']]
                                        if len(idxs)>0: st.session_state.working_df.at[idxs[0], r['日期']] = r['修正後內容']
                                    st.success("已寫入！")
                                    st.session_state['preview_df'] = None
                                    st.rerun()

                    except Exception as e: st.error(f"錯誤: {e}")

            st.markdown("---")
            c1, c2, c3 = st.columns(3)
            with c1:
                o = io.BytesIO()
                with pd.ExcelWriter(o, engine='openpyxl') as w: 
                    st.session_state.working_df.to_excel(w, index=False)
                    ws = w.sheets['Sheet1']
                    if selected_sep == "\n":
                        for row in ws.iter_rows():
                            for cell in row:
                                cell.alignment = Alignment(wrap_text=True)
                st.download_button("📥 下載 Excel (格式修正版)", o.getvalue(), '排班表_匯入用.xlsx')
            
            with c2:
                try:
                    # 修正：針對 CSV 匯出的特殊處理 (支援換行與雙引號)
                    csv_export = st.session_state.working_df.to_csv(index=False, encoding='cp950', errors='replace', quoting=csv.QUOTE_ALL)
                    st.download_button("📥 下載 Big5 CSV (系統專用)", csv_export, '排班表_Big5.csv', 'text/csv')
                except: pass
            with c3:
                u = st.session_state.working_df.to_csv(index=False, encoding='utf-8-sig')
                st.download_button("📥 下載 UTF-8 CSV", u, '排班表_UTF8.csv', 'text/csv')

        except Exception as e: st.error(f"發生錯誤: {e}")

# ==========================================
# 分頁 2: 完診分析 (含延診偵測)
# ==========================================
# (分頁 2 程式碼與前次相同，為節省空間略過，請保留您原本的分頁 2 程式碼)
with tab2:
    st.info("請切換至「排班修改工具」進行格式設定")
    # ... (貼上您原本運作正常的 Tab 2 程式碼) ...
