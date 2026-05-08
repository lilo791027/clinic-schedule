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
st.title("🏥 診所下診時間工具 (順序優化極淨版)")

# ==========================================
# 側邊欄：格式設定
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
# 通用函式 (強化日期與淨化)
# ==========================================
def smart_date_parser(date_str):
    s = str(date_str).strip()
    if s.lower() == 'nan' or not s: return ""
    s_clean = re.sub(r'\(.*?\)', '', s).strip().replace('-', '/')
    
    for fmt in ('%Y/%m/%d', '%m/%d', '%Y.%m.%d'):
        try:
            dt = datetime.strptime(s_clean, fmt)
            if dt.year == 1900: dt = dt.replace(year=datetime.now().year)
            return dt.strftime('%Y/%m/%d')
        except: continue
    
    match = re.search(r'(\d{1,2})/(\d{1,2})', s_clean)
    if match:
        m, d = match.groups()
        return f"{datetime.now().year}/{int(m):02d}/{int(d):02d}"
    
    if len(s_clean) == 7 and s_clean.isdigit(): 
        y_roc = int(s_clean[:3])
        return f"{y_roc + 1911}/{s_clean[3:5]}/{s_clean[5:]}"
    return s_clean

def ultimate_clean(val):
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
        if "-" in t_str: t_str = t_str.split("-")[-1]
        if isinstance(raw_time_str, (datetime, pd.Timestamp)): t = raw_time_str
        else:
            if len(t_str.split(':')) == 3: t = datetime.strptime(t_str, "%H:%M:%S")
            else: t = datetime.strptime(t_str, "%H:%M")
        return datetime(2000, 1, 1).replace(hour=t.hour, minute=t.minute, second=0)
    except: return None

def check_is_delayed(time_obj, shift_type, clinic_name, date_val=""):
    if not time_obj: return False, ""
    base_date = datetime(2000, 1, 1)
    is_licheng = "立丞" in str(clinic_name)
    is_special_sat = any(c in str(clinic_name) for c in ["立全", "立竹", "上京"])
    is_sat = False
    try:
        if date_val: is_sat = datetime.strptime(str(date_val).strip(), "%Y/%m/%d").weekday() == 5
    except: pass

    if shift_type == "早":
        threshold = base_date.replace(hour=12, minute=0); threshold_str = "12:00"
    elif shift_type == "午":
        if is_licheng:
            threshold = base_date.replace(hour=17, minute=0); threshold_str = "17:00"
        else:
            threshold = base_date.replace(hour=18, minute=0); threshold_str = "18:00"
            if not (is_sat and is_special_sat): return False, threshold_str
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
    is_special_sat = any(c in str(clinic_name) for c in ["立全", "立竹", "上京"])
    is_sat = False
    try:
        if date_val: is_sat = datetime.strptime(str(date_val).strip(), "%Y/%m/%d").weekday() == 5
    except: pass

    if shift_type == "早":
        std = base_date.replace(hour=13, minute=0) if is_special_morning else base_date.replace(hour=12, minute=0)
    elif shift_type == "午":
        if is_licheng: std = base_date.replace(hour=17, minute=0)
        else:
            if is_sat and is_special_sat: std = base_date.replace(hour=18, minute=0)
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
                    if any(x in str(col) for x in ['姓名', '編號', '班別', 'ID', 'Name']): continue
                    new_name = smart_date_parser(str(col))
                    if re.match(r'\d{4}/\d{2}/\d{2}', new_name):
                        rename_dict[col] = new_name
                        df_raw[col] = df_raw[col].apply(ultimate_clean)
                
                if rename_dict: df_raw = df_raw.rename(columns=rename_dict)
                st.session_state.working_df = df_raw
                st.session_state.last_uploaded_filename = uploaded_file.name
                st.success("✅ 步驟 1 完成！")

            df = st.session_state.working_df
            if df is not None:
                all_columns = df.columns.tolist()
                date_cols_in_df = [c for c in df.columns if re.match(r'\d{4}/\d{2}/\d{2}', str(c))]
                date_cols_in_df.sort()

                with st.expander("👤 人員設定", expanded=False):
                    c1, c2 = st.columns(2)
                    with c1:
                        default_name = next((c for c in all_columns if "姓名" in c), all_columns[0])
                        name_col = st.selectbox("姓名欄位：", all_columns, index=all_columns.index(default_name))
                    with c2:
                        default_id = next((c for c in all_columns if "編號" in c), "(不修正)")
                        id_col = st.selectbox("員工編號欄位：", ["(不修正)"] + all_columns, index=(all_columns.index(default_id)+1 if default_id in all_columns else 0))
                    
                    all_names = df[name_col].dropna().unique().tolist()
                    special_morning_staff = st.multiselect("🕰️ 指定「純早班」人員 (基準 13:00)：", options=all_names)

                st.markdown("---")
                st.subheader("2. 疊加延診時間")
                analysis_file = st.file_uploader("上傳完診報表", type=['xlsx', 'xls', 'csv', 'XLSX', 'CSV'], key="tab1_analysis")

                if analysis_file:
                    try:
                        if analysis_file.name.lower().endswith('.csv'):
                            try: df_ana = pd.read_csv(analysis_file, encoding='utf-8', dtype=str)
                            except: df_ana = pd.read_csv(analysis_file, encoding='cp950', dtype=str)
                        else: df_ana = pd.read_excel(analysis_file, dtype=str)
                        
                        if '診所名稱' in df_ana.columns and '日期' in df_ana.columns:
                            clinics = df_ana['診所名稱'].unique().tolist()
                            selected_clinic = st.selectbox("選擇診所：", clinics)
                            target_dates = st.multiselect("選擇日期：", options=date_cols_in_df)

                            if st.button("🔍 產生修正預覽", type="primary"):
                                ana_cols = df_ana.columns.tolist()
                                col_m = next((c for c in ana_cols if "早" in c and "原始" not in c), "早")
                                col_a = next((c for c in ana_cols if "午" in c and "原始" not in c), "午")
                                col_e = next((c for c in ana_cols if "晚" in c and "原始" not in c), "晚")
                                
                                df_target = df_ana[df_ana['診所名稱'] == selected_clinic]
                                time_map = {smart_date_parser(r['日期']): {'早': r.get(col_m), '午': r.get(col_a), '晚': r.get(col_e)} for _, r in df_target.iterrows()}
                                
                                changes_list = []
                                dates_to_run = target_dates if target_dates else date_cols_in_df
                                is_licheng = "立丞" in str(selected_clinic)

                                for idx, row in df.iterrows():
                                    staff_name = str(row[name_col]); is_special = staff_name in special_morning_staff
                                    row_txt = " ".join([str(v) for v in row.values if pd.notna(v)])
                                    is_doctor_manager = any(k in row_txt for k in ["醫師", "店長", "主管"])

                                    for col in dates_to_run:
                                        t_date_key = smart_date_parser(col)
                                        if t_date_key in time_map:
                                            cell_val = str(row[col]).strip()
                                            if not any(k in cell_val for k in ["早", "午", "晚", "全", ":"]): continue
                                            
                                            shifts = []
                                            if "早" in cell_val or "全" in cell_val: shifts.append("早")
                                            if "午" in cell_val or "全" in cell_val: shifts.append("午")
                                            if "晚" in cell_val or "全" in cell_val: shifts.append("晚")
                                            
                                            vals = time_map[t_date_key]; has_any_delay = False; shift_segments = []
                                            has_a = "午" in shifts; has_e = "晚" in shifts

                                            if "早" in shifts:
                                                st_t = "08:00"; ed_t = "13:00" if is_special else "12:00"
                                                if pd.notna(vals.get("早")):
                                                    t_obj = parse_time_obj(vals["早"])
                                                    if t_obj and check_is_delayed(t_obj, "早", selected_clinic, t_date_key)[0]:
                                                        has_any_delay = True; ed_t = calculate_time_rule(vals["早"], "早", selected_clinic, is_special, t_date_key)
                                                shift_segments.append(f"{st_t}{selected_conn}{ed_t}")

                                            if has_a and has_e:
                                                st_t = "14:00" if is_licheng else "15:00"; ed_t = "21:00" if is_licheng else "21:30"
                                                if pd.notna(vals.get("晚")):
                                                    t_obj = parse_time_obj(vals["晚"])
                                                    if t_obj and check_is_delayed(t_obj, "晚", selected_clinic, t_date_key)[0]:
                                                        has_any_delay = True; ed_t = calculate_time_rule(vals["晚"], "晚", selected_clinic, False, t_date_key)
                                                shift_segments.append(f"{st_t}{selected_conn}{ed_t}")
                                            elif has_a:
                                                st_t = "14:00" if is_licheng else "15:00"; ed_t = "17:00" if is_licheng else "18:00"
                                                if pd.notna(vals.get("午")):
                                                    t_obj = parse_time_obj(vals["午"])
                                                    if t_obj and check_is_delayed(t_obj, "午", selected_clinic, t_date_key)[0]:
                                                        has_any_delay = True; ed_t = calculate_time_rule(vals["午"], "午", selected_clinic, False, t_date_key)
                                                shift_segments.append(f"{st_t}{selected_conn}{ed_t}")
                                            elif has_e:
                                                st_t = "18:00" if is_licheng else "18:30"; ed_t = "21:00" if is_licheng else "21:30"
                                                if pd.notna(vals.get("晚")):
                                                    t_obj = parse_time_obj(vals["晚"])
                                                    if t_obj and check_is_delayed(t_obj, "晚", selected_clinic, t_date_key)[0]:
                                                        has_any_delay = True; ed_t = calculate_time_rule(vals["晚"], "晚", selected_clinic, False, t_date_key)
                                                shift_segments.append(f"{st_t}{selected_conn}{ed_t}")

                                            if has_any_delay:
                                                final_v = selected_sep.join(shift_segments)
                                                if final_v != cell_val:
                                                    changes_list.append({"✅執行": not is_doctor_manager, "姓名": staff_name, "日期": col, "原始": cell_val, "修正後": final_v})

                                if changes_list:
                                    st.session_state['preview_df'] = pd.DataFrame(changes_list)
                                    st.success(f"找到 {len(changes_list)} 筆延診。(醫師/主管預設不勾選)")
                                else: st.warning("未發現需要更新的資料。")

                            if st.session_state.get('preview_df') is not None:
                                edited = st.data_editor(st.session_state['preview_df'], hide_index=True)
                                if st.button("🚀 確認寫入記憶體"):
                                    for _, r in edited[edited["✅執行"]].iterrows():
                                        idx = st.session_state.working_df.index[st.session_state.working_df[name_col] == r['姓名']]
                                        if len(idx)>0: st.session_state.working_df.at[idx[0], r['日期']] = r['修正後']
                                    st.success("✅ 已寫入！"); st.session_state['preview_df'] = None; st.rerun()
                    except Exception as e: st.error(f"錯誤: {e}")

                st.markdown("---")
                st.subheader("3. 自動填補空白格")
                c1, c2, c3 = st.columns([1,1,2])
                with c1: sta_c = st.text_input("例假日代號", "{sta}")
                with c2: res_c = st.text_input("休息日代號", "{res}")
                with c3:
                    st.write(""); 
                    if st.button("🚀 執行：自動填補", use_container_width=True):
                        df_temp = st.session_state.working_df.copy(); fill_c = 0
                        for idx, row in df_temp.iterrows():
                            emp_id = str(row.get(id_col, "")) if id_col != "(不修正)" else ""
                            if "醫師" in " ".join(row.astype(str)) or emp_id.strip().upper().startswith('P'): continue 
                            is_sta = True
                            for col in date_cols_in_df:
                                if pd.isna(row[col]) or str(row[col]).strip() == "":
                                    df_temp.at[idx, col] = sta_c if is_sta else res_c
                                    is_sta = not is_sta; fill_c += 1
                        st.session_state.working_df = df_temp; st.success(f"✅ 補了 {fill_c} 格。"); st.rerun()

            if st.session_state.working_df is not None:
                st.divider(); df_exp = st.session_state.working_df.copy()
                for col in date_cols_in_df: df_exp[col] = df_exp[col].apply(lambda x: final_export_clean(x, selected_sep))
                data_exp = generate_excel_bytes(df_exp, selected_sep)
                c1, c2, c3 = st.columns(3)
                with c1: st.download_button(f"📥 Excel", data_exp, '排班回填.xlsx', type="primary")
                with c2: st.download_button("📥 Big5 CSV", df_exp.to_csv(index=False, encoding='cp950', errors='replace', quoting=csv.QUOTE_ALL), '排班_Big5.csv', 'text/csv')
                with c3: st.download_button("📥 UTF8 CSV", df_exp.to_csv(index=False, encoding='utf-8-sig'), '排班_UTF8.csv', 'text/csv')
        except Exception as e: st.error(f"錯誤: {e}")

# ==========================================
# 分頁 2: 完診分析 (還原所有對照欄位與預覽)
# ==========================================
with tab2:
    st.header("批次完診分析 & 異常偵測")
    fs = st.radio("檔案類型：", ("🏥 原始匯出 (第4列)", "📄 已整理 (第1列)"), horizontal=True)
    hr_idx = (4 if "第4列" in fs else 1) - 1
    upl = st.file_uploader("上傳完診明細", type=['xlsx','xls','csv','XLSX','CSV'], accept_multiple_files=True, key="t2")
    
    if upl:
        try:
            f1 = upl[0]; f1.seek(0)
            if f1.name.lower().endswith('.csv'):
                try: df_s = pd.read_csv(f1, header=hr_idx, encoding='cp950', nrows=5)
                except: f1.seek(0); df_s = pd.read_csv(f1, header=hr_idx, encoding='utf-8', nrows=5)
            else: df_s = pd.read_excel(f1, header=hr_idx, nrows=5)
            
            df_s.columns = df_s.columns.astype(str).str.strip()
            cols = df_s.columns.tolist(); c1, c2, c3 = st.columns(3)
            idx_d = next((i for i, x in enumerate(cols) if "日期" in x), 0)
            idx_s = next((i for i, x in enumerate(cols) if i != idx_d and any(k in x for k in ["班", "時段"])), 1)
            idx_t = next((i for i, x in enumerate(cols) if i != idx_d and i != idx_s and any(k in x for k in ["時間", "完診"])), len(cols)-1)
            with c1: d_c = st.selectbox("「日期」欄位", cols, index=idx_d)
            with c2: s_c = st.selectbox("「時段」欄位", cols, index=idx_s)
            with c3: t_c = st.selectbox("「時間」欄位", cols, index=idx_t)

            if st.button("🚀 開始分析", key="an_btn"):
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
                    final = pd.concat(res, ignore_index=True); shifts = [c for c in final.columns if c not in ['診所名稱', d_c]]
                    def sk(n): return 0 if "早" in n else 1 if "午" in n else 2 if "晚" in n else 99
                    shifts.sort(key=sk); final = final[['診所名稱', d_c] + shifts].fillna("").sort_values(by=d_c)
                    
                    export_rows = []; delayed_records = []
                    col_m = next((c for c in shifts if "早" in c), None)
                    col_a = next((c for c in shifts if "午" in c), None)
                    col_e = next((c for c in shifts if "晚" in c), None)
                    
                    for _, row in final.iterrows():
                        clinic = row['診所名稱']; date_v = row[d_c]; raw_m = str(row[col_m]) if col_m else ""; raw_a = str(row[col_a]) if col_a else ""; raw_e = str(row[col_e]) if col_e else ""
                        f_m, f_a, f_e = "", "", ""
                        if raw_m:
                            t = parse_time_obj(raw_m)
                            if t and check_is_delayed(t, "早", clinic, date_v)[0]: 
                                delayed_records.append({"日期": date_v, "診所": clinic, "班別": "早", "時間": raw_m})
                                f_m = calculate_time_rule(raw_m, "早", clinic, False, date_v)
                        if raw_a:
                            t = parse_time_obj(raw_a)
                            if t and check_is_delayed(t, "午", clinic, date_v)[0]:
                                delayed_records.append({"日期": date_v, "診所": clinic, "班別": "午", "時間": raw_a})
                                f_a = calculate_time_rule(raw_a, "午", clinic, False, date_v)
                        if raw_e:
                            t = parse_time_obj(raw_e)
                            if t and check_is_delayed(t, "晚", clinic, date_v)[0]:
                                delayed_records.append({"日期": date_v, "診所": clinic, "班別": "晚", "時間": raw_e})
                                f_e = calculate_time_rule(raw_e, "晚", clinic, False, date_v)
                        export_rows.append({"診所名稱": clinic, "日期": date_v, "早上(原始)": raw_m, "早上": f_m, "下午(原始)": raw_a, "下午": f_a, "晚上(原始)": raw_e, "晚上": f_e})
                    
                    st.success("分析完成！")
                    if delayed_records:
                        st.error(f"🚨 偵測到 {len(delayed_records)} 筆延診紀錄：")
                        st.dataframe(pd.DataFrame(delayed_records), use_container_width=True)
                    
                    df_final = pd.DataFrame(export_rows)
                    st.dataframe(df_final, use_container_width=True)
                    o = io.BytesIO()
                    with pd.ExcelWriter(o, engine='openpyxl') as w: df_final.to_excel(w, index=False)
                    st.download_button("📥 下載對照報表", o.getvalue(), "完診分析結果.xlsx", type="primary")
        except Exception as e: st.error(f"發生錯誤: {e}")
