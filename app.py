import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import re

# 設定頁面配置
st.set_page_config(page_title="診所行政綜合工具", layout="wide", page_icon="🏥")
st.title("🏥 診所行政綜合工具箱 (午診規則修正版)")

# 側邊欄：全域功能
with st.sidebar:
    st.info("💡 提示：若頁面卡住或資料顯示異常，請點擊下方按鈕重置。")
    if st.button("🔄 清除所有快取與狀態"):
        st.session_state.clear()
        st.rerun()

tab1, tab2 = st.tabs(["📅 排班修改工具 (整合回填版)", "⏱️ 完診分析"])

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

def calculate_time_rule(raw_time_str, shift_type, clinic_name, is_special_morning=False):
    if not raw_time_str or str(raw_time_str).lower() == 'nan': return None
    try:
        t_str = str(raw_time_str).strip()
        if isinstance(raw_time_str, datetime) or isinstance(raw_time_str, pd.Timestamp):
            t = raw_time_str
        else:
            t = datetime.strptime(t_str, "%H:%M:%S") if len(t_str.split(':')) == 3 else datetime.strptime(t_str, "%H:%M")
        
        base_date = datetime(2000, 1, 1)
        t = base_date.replace(hour=t.hour, minute=t.minute, second=0) # Normalize date
        new_t = t
        is_licheng = "立丞" in str(clinic_name)

        if shift_type == "早":
            # 純早班基準 13:00，一般班 12:00
            std = base_date.replace(hour=13, minute=0) if is_special_morning else base_date.replace(hour=12, minute=0)
            if t > std: new_t = t + timedelta(minutes=5)
            elif t < std: new_t = std
        
        elif shift_type == "午":
            # --- 修改重點：非立丞診所固定為 18:00 ---
            if not is_licheng:
                return "18:00" # 強制回傳固定結束時間
            
            # 立丞診所維持動態計算 (依實際時間)
            std = base_date.replace(hour=17, minute=0) # 立丞午診基準 17:00
            if t > std: new_t = t + timedelta(minutes=5)
            elif t < std: new_t = std

        elif shift_type == "晚":
            std = base_date.replace(hour=21, minute=0) if is_licheng else base_date.replace(hour=21, minute=30)
            if t > std: new_t = t + timedelta(minutes=5)
            elif t < std: new_t = std
            
        return new_t.strftime("%H:%M")
    except: return None

# ==========================================
# 分頁 1: 排班修改工具
# ==========================================
with tab1:
    st.header("排班表格式修正與管理")
    
    if 'working_df' not in st.session_state: st.session_state.working_df = None
    if 'last_uploaded_filename' not in st.session_state: st.session_state.last_uploaded_filename = ""
    if 'modification_history' not in st.session_state: st.session_state.modification_history = [] 

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
                st.session_state.modification_history = []
                st.success("✅ 檔案讀取成功！")

            df = st.session_state.working_df

            if df is not None:
                all_columns = df.columns.tolist()
                date_cols_in_df = [c for c in df.columns if re.match(r'\d{4}-\d{2}-\d{2}', str(c))]
                if not date_cols_in_df:
                    excludes = ['姓名', '編號', '班別', 'ID', 'Name', '診所名稱', '來源檔案', '✅選取', 'Unnamed']
                    date_cols_in_df = [c for c in df.columns if not any(ex in str(c) for ex in excludes)]
                date_cols_in_df.sort()

                # --- 欄位與自動偵測設定 ---
                with st.expander("⚙️ 欄位與人員設定 (全欄位偵測「純早」)", expanded=True):
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
                        
                        # --- 自動偵測邏輯 ---
                        detected_morning_staff = []
                        keywords = ["純早"]
                        
                        for idx, row in df.iterrows():
                            # 掃描整列 (含日期欄位)
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
                            help="選取的人員，其「早班」時段將以 13:00 為基準。(午、晚班規則不變)"
                        )
                        if detected_morning_staff:
                            st.caption(f"✅ 已自動選取 {len(detected_morning_staff)} 位人員")
                    else:
                        all_names = []
                        special_morning_staff = []

                # --- 自動回填邏輯 ---
                st.markdown("---")
                st.subheader("2. 依照完診分析自動更新")
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
                            with c_b: target_dates = st.multiselect("B. 選擇日期：", options=date_cols_in_df)

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
                                    for col in dates_to_check:
                                        if col in time_map:
                                            cell_val = str(row[col]).strip()
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
                                                # 計算與格式化
                                                fm = calculate_time_rule(vals['早'], "早", selected_clinic, is_special) if has_m else None
                                                fa = calculate_time_rule(vals['午'], "午", selected_clinic) if has_a else None
                                                fe = calculate_time_rule(vals['晚'], "晚", selected_clinic) if has_e else None
                                                
                                                parts = []
                                                if has_m and fm: parts.append(f"08:00-{fm}")
                                                
                                                # 午班顯示邏輯
                                                if is_licheng:
                                                    if has_a and fa: parts.append(f"15:00-{fa}")
                                                    if has_e and fe: parts.append(f"18:30-{fe}")
                                                else:
                                                    # 非立丞：午班固定 15:00-18:00 (fa已在函式中固定為18:00)
                                                    if has_m and has_a and not has_e:
                                                        if fa: parts.append(f"15:00-{fa}")
                                                    elif not has_m and has_a and has_e:
                                                        if fe: parts.append(f"15:00-{fe}") # 午晚: 這裡只加晚班? 根據需求，午晚班通常要顯示午班
                                                        # 修正：午晚班若有午班，應該要顯示午班
                                                        if fa: parts.insert(0 if not parts else len(parts), f"15:00-{fa}")
                                                    elif has_m and has_a and has_e:
                                                        if fe: parts.append(f"15:00-{fe}") # 全天通常會被壓縮顯示? 這裡保留您的邏輯
                                                        # 若是全天，通常需要顯示中間段嗎？
                                                        # 原本邏輯：全天 -> 只顯示早跟晚(15:00-21:30)? 
                                                        # 根據您的舊程式碼： elif has_m and has_a and has_e: if final_e: new_parts.append(f"15:00-{final_e}")
                                                        # 這看起來是把午晚接在一起變成 15:00-晚迄。
                                                        pass 
                                                    elif not has_m and has_a and not has_e:
                                                        if fa: parts.append(f"15:00-{fa}")
                                                    elif not has_m and not has_a and has_e:
                                                        if fe: parts.append(f"18:30-{fe}")
                                                
                                                final_val = ",".join(parts)
                                                if final_val and final_val != cell_val:
                                                    changes_list.append({"✅執行": True, "姓名": row[name_col], "日期": col, "原始內容": cell_val, "修正後內容": final_val})

                                if changes_list:
                                    st.session_state['preview_df'] = pd.DataFrame(changes_list)
                                    st.success(f"找到 {len(changes_list)} 筆更新。")
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

            # --- 下載區塊 ---
            st.markdown("---")
            c1, c2, c3 = st.columns(3)
            with c1:
                o = io.BytesIO()
                with pd.ExcelWriter(o, engine='openpyxl') as w: st.session_state.working_df.to_excel(w, index=False)
                st.download_button("📥 下載 Excel", o.getvalue(), '排班表.xlsx')
            with c2:
                try:
                    import csv
                    c = st.session_state.working_df.to_csv(index=False, encoding='cp950', errors='replace', quoting=csv.QUOTE_ALL)
                    st.download_button("📥 下載 Big5 CSV", c, '排班表_Big5.csv', 'text/csv')
                except: pass
            with c3:
                u = st.session_state.working_df.to_csv(index=False, encoding='utf-8-sig')
                st.download_button("📥 下載 UTF-8 CSV", u, '排班表_UTF8.csv', 'text/csv')

        except Exception as e: st.error(f"發生錯誤: {e}")

# ==========================================
# 分頁 2: 完診分析
# ==========================================
with tab2:
    st.header("批次完診分析")
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

            if st.button("🚀 開始分析", key="an_btn"):
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
                    
                    mod = final.copy()
                    for c in shifts:
                        shift_type = "早" if "早" in c else "午" if "午" in c else "晚"
                        mod[c] = mod.apply(lambda r: calculate_time_rule(r[c], shift_type, r['診所名稱']) or r[c], axis=1)
                    
                    st.success(f"完成！共合併 {len(res)} 個檔案。")
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        o = io.BytesIO()
                        with pd.ExcelWriter(o, engine='openpyxl') as w: final.to_excel(w, index=False)
                        st.download_button("📥 原始完診總表", o.getvalue(), '原始完診總表.xlsx')
                    with c2:
                        o = io.BytesIO()
                        with pd.ExcelWriter(o, engine='openpyxl') as w: mod.to_excel(w, index=False)
                        st.download_button("📥 修正完診總表", o.getvalue(), '修正完診總表.xlsx', type="primary")
        except Exception as e: 
            st.error(f"發生錯誤: {e}")
