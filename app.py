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
st.title("🏥 診所下診時間工具 (v2.7 延診精準填入版)")

# ==========================================
# 側邊欄：格式設定 (完全保留原始設定)
# ==========================================
with st.sidebar:
    st.header("⚙️ 匯出格式設定")
    st.info("已預設為系統可讀取的「逗號分隔」格式。")
    
    sep_options = ["逗號 (,)", "換行 (Alt+Enter)", "空白 (Space)", "分號 (;)"]
    sep_option = st.selectbox("1. 多時段「分隔」符號", sep_options, index=0)
    
    conn_options = ["減號 (-)", "波浪號 (~)", "無符號 (08001200)"]
    conn_option = st.selectbox("2. 時間「連接」符號", conn_options, index=0)

    sep_map = {"空白 (Space)": " ", "換行 (Alt+Enter)": "\n", "逗號 (,)": ",", "分號 (;)": ";"}
    conn_map = {"減號 (-)": "-", "波浪號 (~)": "~", "無符號 (08001200)": ""}
    
    selected_sep = sep_map[sep_option]
    selected_conn = conn_map[conn_option]

    if st.button("🔄 清除所有快取與狀態"):
        st.session_state.clear()
        st.rerun()

tab1, tab2 = st.tabs(["📅 階段二：排班回填", "⏱️ 階段一：完診分析"])

# ==========================================
# 通用函式 (強化日期與淨化邏輯)
# ==========================================
def smart_date_parser(date_str):
    """將所有日期統一轉換為 YYYY/MM/DD，並嚴格修剪空白"""
    s = str(date_str).strip()
    if s.lower() == 'nan' or not s: return ""
    # 處理 M/D 格式
    match = re.search(r'(\d{1,2})/(\d{1,2})', s)
    if match:
        m, d = match.groups()
        return f"{datetime.now().year}/{int(m):02d}/{int(d):02d}"
    # 處理民國
    if len(s) == 7 and s.isdigit(): 
        y_roc = int(s[:3])
        return f"{y_roc + 1911}/{s[3:5]}/{s[5:]}"
    # 其他標準格式
    s_clean = re.sub(r'\(.*?\)', '', s).strip()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%m/%d', '%m-%d', '%Y.%m.%d'):
        try:
            dt = datetime.strptime(s_clean, fmt)
            if dt.year == 1900: dt = dt.replace(year=datetime.now().year)
            return dt.strftime('%Y/%m/%d')
        except: continue
    return s

def ultimate_clean(val):
    """保留特殊符號與文字，僅移除系統假時間"""
    if pd.isna(val) or str(val).lower() == 'nan': return ""
    s = str(val)
    s = re.sub(r'[,\s\n;]*00:00-00:00[,\s\n;]*[^\s,;]*', '', s)
    s = re.sub(r'[■□▲△]', '', s)
    if not re.search(r'[A-Za-z0-9\u4e00-\u9fa5\{\}\[\]\(\)]', s): return ""
    return s.strip(" \n\r\t,;，")

def final_export_clean(val, sep):
    s = ultimate_clean(val)
    if not s: return ""
    s = s.replace("\n", sep)
    if sep != "\n" and sep != " ":
        esc_sep = re.escape(sep)
        s = re.sub(f"[{esc_sep}]+", sep, s)
    return s.strip(" \n\r\t,;，" + sep)

def parse_time_obj(raw_time_str):
    if not raw_time_str or str(raw_time_str).lower() == 'nan': return None
    try:
        t_str = str(raw_time_str).strip().replace("~", "-")
        if isinstance(raw_time_str, (datetime, pd.Timestamp)):
            t = raw_time_str
        else:
            if "-" in t_str: t_str = t_str.split("-")[-1]
            if len(t_str.split(':')) == 3: t = datetime.strptime(t_str, "%H:%M:%S")
            else: t = datetime.strptime(t_str, "%H:%M")
        return datetime(2000, 1, 1).replace(hour=t.hour, minute=t.minute, second=0)
    except: return None

def check_is_delayed(time_obj, shift_type, clinic_name, date_val=""):
    """精準延診判斷邏輯"""
    if not time_obj: return False, ""
    base_date = datetime(2000, 1, 1)
    is_licheng = "立丞" in str(clinic_name)
    is_special_sat_clinic = any(c in str(clinic_name) for c in ["立全", "立竹", "上京"])
    
    is_sat = False
    try:
        if date_val: 
            # 確保用相同的格式解析日期來判斷星期六
            parsed_d = datetime.strptime(str(date_val).strip(), "%Y/%m/%d")
            is_sat = (parsed_d.weekday() == 5)
    except: pass

    if shift_type == "早":
        threshold = base_date.replace(hour=12, minute=0); threshold_str = "12:00"
    elif shift_type == "午":
        if is_licheng:
            threshold = base_date.replace(hour=17, minute=0); threshold_str = "17:00"
        else:
            threshold = base_date.replace(hour=18, minute=0); threshold_str = "18:00"
            # 星期六特定診所午診才算延診，否則不加
            if not (is_sat and is_special_sat_clinic): return False, threshold_str
    elif shift_type == "晚":
        if is_licheng:
            threshold = base_date.replace(hour=21, minute=0); threshold_str = "21:00"
        else:
            threshold = base_date.replace(hour=21, minute=30); threshold_str = "21:30"
    else: return False, ""
    
    if time_obj > threshold: return True, threshold_str
    return False, threshold_str

def calculate_time_rule(raw_time_str, shift_type, clinic_name, is_special_morning=False, date_val=""):
    t = parse_time_obj(raw_time_str)
    if not t: return None
    base_date = datetime(2000, 1, 1)
    is_licheng = "立丞" in str(clinic_name)
    is_special_sat_clinic = any(c in str(clinic_name) for c in ["立全", "立竹", "上京"])
    
    is_sat = False
    try:
        if date_val: is_sat = datetime.strptime(str(date_val).strip(), "%Y/%m/%d").weekday() == 5
    except: pass

    if shift_type == "早":
        std = base_date.replace(hour=13, minute=0) if is_special_morning else base_date.replace(hour=12, minute=0)
    elif shift_type == "午":
        if is_licheng: std = base_date.replace(hour=17, minute=0)
        else:
            if is_sat and is_special_sat_clinic: std = base_date.replace(hour=18, minute=0)
            else: return "18:00"
    elif shift_type == "晚":
        std = base_date.replace(hour=21, minute=0) if is_licheng else base_date.replace(hour=21, minute=30)
    else: return None

    new_t = t + timedelta(minutes=5) if t > std else std
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
    if 'working_df' not in st.session_state: st.session_state.working_df = None
    if 'last_uploaded_filename' not in st.session_state: st.session_state.last_uploaded_filename = ""

    st.markdown("### 1. 請上傳從系統匯出的【原始排班表】")
    uploaded_file = st.file_uploader("上傳排班表 (Excel / CSV)", type=['xlsx', 'xls', 'csv'], key="tab1_uploader")

    if uploaded_file is not None:
        try:
            if st.session_state.working_df is None or uploaded_file.name != st.session_state.last_uploaded_filename:
                if uploaded_file.name.lower().endswith('.csv'):
                    try: df_raw = pd.read_csv(uploaded_file, encoding='utf-8', dtype=str)
                    except: df_raw = pd.read_csv(uploaded_file, encoding='cp950', dtype=str)
                else: df_raw = pd.read_excel(uploaded_file, dtype=str)

                rename_dict = {}
                for col in df_raw.columns:
                    col_str = str(col).strip()
                    # 統一將標題日期也轉為斜線文字格式，確保對接
                    new_name = smart_date_parser(col_str)
                    if re.match(r'\d{4}/\d{2}/\d{2}', new_name):
                        rename_dict[col] = new_name
                        df_raw[col] = df_raw[col].apply(ultimate_clean)
                
                if rename_dict: df_raw = df_raw.rename(columns=rename_dict)
                st.session_state.working_df = df_raw
                st.session_state.last_uploaded_filename = uploaded_file.name
                st.success("✅ 步驟 1 完成！已成功格式化日期欄位。")

            df = st.session_state.working_df
            if df is not None:
                all_columns = df.columns.tolist()
                date_cols_in_df = [c for c in df.columns if re.match(r'\d{4}/\d{2}/\d{2}', str(c))]
                date_cols_in_df.sort()

                with st.expander("👤 人員與屬性設定", expanded=False):
                    c1, c2 = st.columns(2)
                    with c1:
                        default_name = next((c for c in all_columns if "姓名" in c), all_columns[0])
                        name_col = st.selectbox("姓名欄位：", all_columns, index=all_columns.index(default_name))
                    with c2:
                        default_id = next((c for c in all_columns if "編號" in c), "(不修正)")
                        id_idx = 0 if default_id not in all_columns else all_columns.index(default_id) + 1
                        id_col = st.selectbox("員工編號欄位：", ["(不修正)"] + all_columns, index=id_idx)
                    
                    if name_col:
                        all_names = df[name_col].dropna().unique().tolist()
                        special_morning_staff = st.multiselect("🕰️ 指定「純早班」人員 (基準 13:00)：", options=all_names)
                    else: special_morning_staff = []

                st.markdown("---")
                st.subheader("2. 疊加延診時間 (請上傳【完診分析結果檔】)")
                analysis_file = st.file_uploader("上傳完診報表 (Excel / CSV)", type=['xlsx', 'xls', 'csv'], key="tab1_analysis")

                if analysis_file:
                    try:
                        if analysis_file.name.lower().endswith('.csv'):
                            try: df_ana = pd.read_csv(analysis_file, encoding='utf-8', dtype=str)
                            except: df_ana = pd.read_csv(analysis_file, encoding='cp950', dtype=str)
                        else: df_ana = pd.read_excel(analysis_file, dtype=str)
                        
                        if '診所名稱' in df_ana.columns and '日期' in df_ana.columns:
                            clinics = df_ana['診所名稱'].unique().tolist()
                            c_a, c_b = st.columns(2)
                            with c_a: selected_clinic = st.selectbox("A. 選擇診所：", clinics)
                            with c_b: target_dates = st.multiselect("B. 選擇日期 (不選即檢查整月)：", options=date_cols_in_df)

                            if st.button("🔍 產生修正預覽", type="primary"):
                                # 🛡️ 智慧標題偵測：防止「早班下診」這類標題導致抓不到資料
                                ana_cols = df_ana.columns.tolist()
                                col_m = next((c for c in ana_cols if "早" in c), "早")
                                col_a = next((c for c in ana_cols if "午" in c), "午")
                                col_e = next((c for c in ana_cols if "晚" in c), "晚")
                                
                                df_target = df_ana[df_ana['診所名稱'] == selected_clinic]
                                # 統一建立對照表，日期格式絕對匹配
                                time_map = {smart_date_parser(r['日期']): {'早': r.get(col_m), '午': r.get(col_a), '晚': r.get(col_e)} for _, r in df_target.iterrows()}
                                
                                changes_list = []
                                dates_to_check = target_dates if target_dates else date_cols_in_df
                                is_licheng = "立丞" in str(selected_clinic)

                                for idx, row in df.iterrows():
                                    staff_name = str(row[name_col])
                                    is_special = staff_name in special_morning_staff
                                    row_content_str = " ".join([str(v) for v in row.values if pd.notna(v)])
                                    is_doctor_manager = any(k in row_content_str for k in ["醫師", "店長", "主管"])
                                    
                                    for col in dates_to_check:
                                        t_date = smart_date_parser(col)
                                        if t_date in time_map:
                                            cell_val = str(row[col]).strip()
                                            if not any(k in cell_val for k in ["早", "午", "晚", "全", ":"]): continue
                                            
                                            shifts = []
                                            if "早" in cell_val or "全" in cell_val: shifts.append("早")
                                            if "午" in cell_val or "全" in cell_val: shifts.append("午")
                                            if "晚" in cell_val or "全" in cell_val: shifts.append("晚")
                                            
                                            vals = time_map[t_date]
                                            has_any_delay = False
                                            shift_segments = []
                                            
                                            # 早班處理
                                            if "早" in shifts:
                                                st_t = "08:00"; ed_t = "13:00" if is_special else "12:00"
                                                if pd.notna(vals.get("早")):
                                                    t_obj = parse_time_obj(vals["早"])
                                                    if t_obj:
                                                        is_d, _ = check_is_delayed(t_obj, "早", selected_clinic, t_date)
                                                        if is_d:
                                                            has_any_delay = True
                                                            ed_t = calculate_time_rule(vals["早"], "早", selected_clinic, is_special, t_date)
                                                shift_segments.append(f"{st_t}{selected_conn}{ed_t} 早班")

                                            # 午晚班合併處理
                                            has_a = "午" in shifts
                                            has_e = "晚" in shifts
                                            if has_a and has_e:
                                                st_t = "14:00" if is_licheng else "15:00"
                                                ed_t = "21:00" if is_licheng else "21:30"
                                                if pd.notna(vals.get("晚")):
                                                    t_obj = parse_time_obj(vals["晚"])
                                                    if t_obj:
                                                        is_d, _ = check_is_delayed(t_obj, "晚", selected_clinic, t_date)
                                                        if is_d:
                                                            has_any_delay = True
                                                            ed_t = calculate_time_rule(vals["晚"], "晚", selected_clinic, False, t_date)
                                                shift_segments.append(f"{st_t}{selected_conn}{ed_t} 午晚班一起")
                                            elif has_a:
                                                st_t = "14:00" if is_licheng else "15:00"
                                                ed_t = "17:00" if is_licheng else "18:00"
                                                if pd.notna(vals.get("午")):
                                                    t_obj = parse_time_obj(vals["午"])
                                                    if t_obj:
                                                        is_d, _ = check_is_delayed(t_obj, "午", selected_clinic, t_date)
                                                        if is_d:
                                                            has_any_delay = True
                                                            ed_t = calculate_time_rule(vals["午"], "午", selected_clinic, False, t_date)
                                                shift_segments.append(f"{st_t}{selected_conn}{ed_t} 午班")
                                            elif has_e:
                                                st_t = "18:00" if is_licheng else "18:30"
                                                ed_t = "21:00" if is_licheng else "21:30"
                                                if pd.notna(vals.get("晚")):
                                                    t_obj = parse_time_obj(vals["晚"])
                                                    if t_obj:
                                                        is_d, _ = check_is_delayed(t_obj, "晚", selected_clinic, t_date)
                                                        if is_d:
                                                            has_any_delay = True
                                                            ed_t = calculate_time_rule(vals["晚"], "晚", selected_clinic, False, t_date)
                                                shift_segments.append(f"{st_t}{selected_conn}{ed_t} 晚班")

                                            if has_any_delay:
                                                final_v = selected_sep.join(shift_segments)
                                                # 如果拼出來的字串跟原本格子不同，才列入修正
                                                if final_v != cell_val:
                                                    changes_list.append({
                                                        "✅執行": not is_doctor_manager, 
                                                        "姓名": staff_name, "日期": col, "原始": cell_val, "修正後": final_v
                                                    })

                                if changes_list:
                                    st.session_state['preview_df'] = pd.DataFrame(changes_list)
                                    st.success(f"找到 {len(changes_list)} 筆延診更新！(醫師/主管/店長預設不勾選)")
                                else: st.warning("比對完畢，未發現需要更新的延診資料。請確認日期格式是否正確。")

                            if st.session_state.get('preview_df') is not None:
                                edited = st.data_editor(st.session_state['preview_df'], hide_index=True)
                                if st.button("🚀 確認寫入記憶體"):
                                    rows = edited[edited["✅執行"]==True]
                                    for _, r in rows.iterrows():
                                        idxs = st.session_state.working_df.index[st.session_state.working_df[name_col] == r['姓名']]
                                        if len(idxs)>0: st.session_state.working_df.at[idxs[0], r['日期']] = r['修正後']
                                    st.success("✅ 資料已成功寫入！")
                                    st.session_state['preview_df'] = None
                                    st.rerun()
                    except Exception as e: st.error(f"分析時發生錯誤: {e}")

                st.markdown("---")
                st.subheader("3. 自動填補剩餘空白格")
                c_b1, c_b2, c_b3 = st.columns([1,1,2])
                with c_b1: sta_code = st.text_input("例假日代號", "{sta}")
                with c_b2: res_code = st.text_input("休息日代號", "{res}")
                with c_b3:
                    st.write("")
                    if st.button("🚀 執行：自動填滿空白格", use_container_width=True):
                        df_temp = st.session_state.working_df.copy()
                        fill_count = 0
                        for idx, row in df_temp.iterrows():
                            emp_id = str(row.get(id_col, "")) if id_col != "(不修正)" else ""
                            row_str = " ".join([str(v) for v in row.values if pd.notna(v)])
                            if "醫師" in row_str or emp_id.strip().upper().startswith('P'): continue 
                            next_is_sta = True
                            for col in date_cols_in_df:
                                if pd.isna(row[col]) or str(row[col]).strip() == "":
                                    df_temp.at[idx, col] = sta_code if next_is_sta else res_code
                                    next_is_sta = not next_is_sta; fill_count += 1
                        st.session_state.working_df = df_temp; st.rerun()

            st.markdown("---")
            if st.session_state.working_df is not None:
                df_export = st.session_state.working_df.copy()
                for col in date_cols_in_df: df_export[col] = df_export[col].apply(lambda x: final_export_clean(x, selected_sep))
                data_export = generate_excel_bytes(df_export, selected_sep)
                c1, c2, c3 = st.columns(3)
                with c1: st.download_button(f"📥 下載 Excel 匯入檔", data_export, '排班回填_已格式化.xlsx', type="primary")
                with c2: 
                    try: st.download_button("📥 下載 Big5 CSV", df_export.to_csv(index=False, encoding='cp950', errors='replace', quoting=csv.QUOTE_ALL), '排班回填_Big5.csv', 'text/csv')
                    except: pass
                with c3: st.download_button("📥 下載 UTF-8 CSV", df_export.to_csv(index=False, encoding='utf-8-sig'), '排班回填_UTF8.csv', 'text/csv')
        except Exception as e: st.error(f"讀取排班表失敗: {e}")

# ==========================================
# 分頁 2: 完診分析 (含延診自動標記)
# ==========================================
with tab2:
    st.header("批次完診分析 & 異常偵測")
    fs = st.radio("檔案類型：", ("🏥 原始系統匯出檔 (第4列標題)", "📄 標準/分析結果檔 (第1列標題)"), horizontal=True)
    upl = st.file_uploader("上傳完診明細 (可多檔)", type=['xlsx','xls','csv','XLSX','CSV'], accept_multiple_files=True, key="t2")
    hr_idx = (4 if "第4列" in fs else 1) - 1
    if upl:
        try:
            f1 = upl[0]; f1.seek(0)
            if f1.name.lower().endswith('.csv'):
                try: df_s = pd.read_csv(f1, header=hr_idx, encoding='cp950', nrows=5)
                except: f1.seek(0); df_s = pd.read_csv(f1, header=hr_idx, encoding='utf-8', nrows=5)
            else: df_s = pd.read_excel(f1, header=hr_idx, nrows=5)
            df_s.columns = df_s.columns.astype(str).str.strip()
            cols = df_s.columns.tolist()
            c1, c2, c3 = st.columns(3)
            idx_d = next((i for i, x in enumerate(cols) if "日期" in x), 0)
            idx_s_cands = [i for i, x in enumerate(cols) if i != idx_d and any(k in x for k in ["班", "時段", "早", "午", "晚"])]
            idx_s = idx_s_cands[0] if idx_s_cands else 1
            idx_t_cands = [i for i, x in enumerate(cols) if i != idx_d and i != idx_s and any(k in x for k in ["時間", "完診", "下診"])]
            idx_t = idx_t_cands[0] if idx_t_cands else len(cols)-1
            with c1: d_c = st.selectbox("「日期」欄位", cols, index=idx_d)
            with c2: s_c = st.selectbox("「時段」欄位", cols, index=idx_s)
            with c3: t_c = st.selectbox("「時間」欄位", cols, index=idx_t)

            if st.button("🚀 開始分析並自動偵測延診", key="an_btn"):
                res = []
                for f in upl:
                    try:
                        f.seek(0)
                        if f.name.lower().endswith('.csv'):
                            try: h = pd.read_csv(f, header=None, nrows=1, encoding='cp950'); d = pd.read_csv(f, header=hr_idx, encoding='cp950')
                            except: f.seek(0); h = pd.read_csv(f, header=None, nrows=1, encoding='utf-8'); d = pd.read_csv(f, header=hr_idx, encoding='utf-8')
                        else: h = pd.read_excel(f, header=None, nrows=1); d = pd.read_excel(f, header=hr_idx)
                        c_name = str(h.iloc[0,0]).strip()[:4]
                        d.columns = d.columns.astype(str).str.strip()
                        if all(x in d.columns for x in [d_c, s_c, t_c]):
                            clean = d.dropna(subset=[d_c]).copy(); clean[t_c] = clean[t_c].astype(str)
                            g = clean.groupby([d_c, s_c])[t_c].max().reset_index()
                            p = g.pivot(index=d_c, columns=s_c, values=t_c).reset_index()
                            p.insert(0, '診所名稱', c_name); p[d_c] = p[d_c].apply(smart_date_parser); res.append(p)
                    except: pass
                if res:
                    final = pd.concat(res, ignore_index=True)
                    shifts = [c for c in final.columns if c not in ['診所名稱', d_c]]
                    def sk(n): return 0 if "早" in n else 1 if "午" in n else 2 if "晚" in n else 99
                    shifts.sort(key=sk)
                    final = final[['診所名稱', d_c] + shifts].fillna("").sort_values(by=d_c)
                    st.dataframe(final, use_container_width=True)
                    
                    # 匯出分析結果 (用於 Tab 1 疊加)
                    o = io.BytesIO()
                    with pd.ExcelWriter(o, engine='openpyxl') as w: final.to_excel(w, index=False)
                    st.download_button("📥 下載完診分析結果檔", o.getvalue(), "完診分析結果.xlsx", type="primary")
        except Exception as e: st.error(f"分析失敗: {e}")
