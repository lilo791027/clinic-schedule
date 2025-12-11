import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import re

st.set_page_config(page_title="診所行政綜合工具", layout="wide")
st.title("🏥 診所行政綜合工具箱")

tab1, tab2 = st.tabs(["📅 排班修改工具 (整合回填版)", "⏱️ 完診分析 (強力除錯版)"])

# ==========================================
# 通用函式
# ==========================================
def smart_date_parser(date_str):
    s = str(date_str).strip()
    if len(s) == 7 and s.isdigit(): # 1141201
        y_roc = int(s[:3])
        return f"{y_roc + 1911}-{s[3:5]}-{s[5:]}"
    s_clean = re.sub(r'\(.*?\)', '', s).strip()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%m/%d', '%m-%d'):
        try:
            dt = datetime.strptime(s_clean, fmt)
            if dt.year == 1900: dt = dt.replace(year=2025)
            return dt.strftime('%Y-%m-%d')
        except: continue
    return s

def calculate_time_rule(raw_time_str, shift_type, clinic_name):
    if not raw_time_str or str(raw_time_str).lower() == 'nan': return None
    try:
        t = datetime.strptime(str(raw_time_str).strip(), "%H:%M")
        new_t = t
        is_licheng = "立丞" in str(clinic_name)

        if shift_type == "早":
            std = datetime.strptime("12:00", "%H:%M")
            if t > std: new_t = t + timedelta(minutes=5)
            elif t < std: new_t = std
        
        elif shift_type == "午":
            if is_licheng:
                std = datetime.strptime("17:00", "%H:%M")
                if t > std: new_t = t + timedelta(minutes=5)
                elif t < std: new_t = std
            else:
                std = datetime.strptime("18:00", "%H:%M")
                if t > std: new_t = t + timedelta(minutes=5)
                elif t < std: new_t = std

        elif shift_type == "晚":
            if is_licheng:
                std = datetime.strptime("21:00", "%H:%M")
                if t > std: new_t = t + timedelta(minutes=5)
                elif t < std: new_t = std
            else:
                std = datetime.strptime("21:30", "%H:%M")
                if t > std: new_t = t + timedelta(minutes=5)
                elif t < std: new_t = std
        
        return new_t.strftime("%H:%M")
    except:
        return None

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
                    col_str = str(col).strip()
                    if any(x in col_str for x in ['姓名', '編號', '班別', 'ID', 'Name']): continue
                    new_name = smart_date_parser(col_str)
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
                    excludes = ['姓名', '編號', '班別', 'ID', 'Name', '診所名稱', '來源檔案', '✅選取']
                    date_cols_in_df = [c for c in df.columns if not any(ex in str(c) for ex in excludes)]
                date_cols_in_df.sort()

                with st.expander("⚙️ 欄位設定", expanded=False):
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
                        df[id_col] = df[id_col].apply(lambda x: str(x).strip().split('.')[0].zfill(4) if str(x).lower()!='nan' else "")
                        st.session_state.working_df = df

                if name_col:
                    all_names = df[name_col].dropna().unique().tolist()
                else:
                    all_names = []

                # --- 自動回填 ---
                st.markdown("---")
                st.subheader("2. 依照完診分析自動更新")
                analysis_file = st.file_uploader("請上傳完診結果檔", type=['xlsx', 'xls', 'csv'], key="tab1_analysis")

                if analysis_file:
                    try:
                        if analysis_file.name.lower().endswith('.csv'):
                            df_ana = pd.read_csv(analysis_file, encoding='utf-8', dtype=str)
                        else:
                            df_ana = pd.read_excel(analysis_file, dtype=str)
                        
                        if '診所名稱' in df_ana.columns and '日期' in df_ana.columns:
                            clinics = df_ana['診所名稱'].unique().tolist()
                            col_a, col_b = st.columns(2)
                            with col_a: selected_clinic = st.selectbox("A. 選擇診所：", clinics)
                            with col_b: target_dates = st.multiselect("B. 選擇日期：", options=date_cols_in_df, placeholder="未選則檢查全部")

                            if st.button("🔍 產生預覽", type="primary"):
                                ana_cols = df_ana.columns.tolist()
                                col_m = next((c for c in ana_cols if "早" in c), None)
                                col_a = next((c for c in ana_cols if "午" in c), None)
                                col_e = next((c for c in ana_cols if "晚" in c), None)

                                df_ana_target = df_ana[df_ana['診所名稱'] == selected_clinic].copy()
                                time_map = {}
                                for _, row in df_ana_target.iterrows():
                                    d = smart_date_parser(row['日期'])
                                    time_map[d] = {
                                        '早': row[col_m] if col_m and not pd.isna(row[col_m]) else None,
                                        '午': row[col_a] if col_a and not pd.isna(row[col_a]) else None,
                                        '晚': row[col_e] if col_e and not pd.isna(row[col_e]) else None
                                    }

                                changes_list = []
                                dates_to_check = target_dates if target_dates else date_cols_in_df
                                is_licheng = "立丞" in selected_clinic

                                for idx, row in df.iterrows():
                                    for col in df.columns:
                                        if col in dates_to_check and col in time_map:
                                            cell_val = str(row[col]).strip()
                                            if cell_val and cell_val.lower() != 'nan':
                                                shifts = re.split(r'[,\n]', cell_val)
                                                has_m, has_a, has_e = False, False, False
                                                for s in shifts:
                                                    if "全" in s: has_m=True; has_a=True; has_e=True
                                                    if "早" in s: has_m=True
                                                    if "午" in s: has_a=True
                                                    if "晚" in s: has_e=True
                                                    if not any(x in s for x in ["早","午","晚","全"]):
                                                        ts = re.split(r'[-~]', s)
                                                        if len(ts)==2:
                                                            try:
                                                                th = datetime.strptime(ts[0].strip(), "%H:%M").hour
                                                                if th < 13: has_m=True
                                                                elif 13<=th<18: has_a=True
                                                                elif th>=18: has_e=True
                                                            except: pass

                                                raw_m = time_map[col]['早']
                                                raw_a = time_map[col]['午']
                                                raw_e = time_map[col]['晚']
                                                
                                                final_m = calculate_time_rule(raw_m, "早", selected_clinic) if has_m else None
                                                final_a = calculate_time_rule(raw_a, "午", selected_clinic) if has_a else None
                                                final_e = calculate_time_rule(raw_e, "晚", selected_clinic) if has_e else None

                                                new_parts = []
                                                if has_m and final_m: new_parts.append(f"08:00-{final_m}")
                                                
                                                if is_licheng:
                                                    if has_a and final_a: new_parts.append(f"15:00-{final_a}")
                                                    if has_e and final_e: new_parts.append(f"18:30-{final_e}")
                                                else:
                                                    if has_m and has_a and not has_e: # 早午: 顯示早+午 (修正)
                                                        if final_a: new_parts.append(f"15:00-{final_a}")
                                                    elif not has_m and has_a and has_e: # 午晚
                                                        if final_e: new_parts.append(f"15:00-{final_e}")
                                                    elif has_m and has_a and has_e: # 全天
                                                        if final_e: new_parts.append(f"15:00-{final_e}")
                                                    elif not has_m and has_a and not has_e: # 只有午
                                                        if final_a: new_parts.append(f"15:00-{final_a}")
                                                    elif not has_m and not has_a and has_e: # 只有晚
                                                        if final_e: new_parts.append(f"18:30-{final_e}")

                                                final_val = ",".join(new_parts)
                                                if not final_val and (has_m or has_a or has_e): pass
                                                elif final_val != cell_val:
                                                    changes_list.append({
                                                        "✅執行": True,
                                                        "姓名": row[name_col],
                                                        "日期": col,
                                                        "原始內容": cell_val,
                                                        "修正後內容": final_val
                                                    })

                                if changes_list:
                                    st.session_state['preview_df'] = pd.DataFrame(changes_list)
                                    st.success(f"找到 {len(changes_list)} 筆資料可更新。")
                                else:
                                    st.session_state['preview_df'] = None
                                    st.warning("無資料更新。")

                            if st.session_state.get('preview_df') is not None:
                                edited_df = st.data_editor(st.session_state['preview_df'], hide_index=True)
                                if st.button("🚀 確認寫入", type="primary"):
                                    rows = edited_df[edited_df["✅執行"] == True]
                                    cnt = 0
                                    for _, row in rows.iterrows():
                                        idxs = st.session_state.working_df.index[st.session_state.working_df[name_col] == row['姓名']].tolist()
                                        if idxs:
                                            st.session_state.working_df.at[idxs[0], row['日期']] = row['修正後內容']
                                            cnt += 1
                                    st.session_state.modification_history.append(f"自動更新: {selected_clinic} {cnt}筆")
                                    st.success("已寫入！")
                                    st.session_state['preview_df'] = None
                                    st.rerun()
                    except Exception as e: st.error(f"分析檔錯誤: {e}")

            # --- 手動排班 ---
            st.markdown("---")
            st.subheader("3. 手動修改")
            if name_col and all_names:
                with st.form("man_form", clear_on_submit=True):
                    c1, c2 = st.columns([1, 1.5])
                    with c1:
                        sn = st.multiselect("人員", all_names)
                        sd = st.multiselect("日期", date_cols_in_df)
                    with c2:
                        st.write("時段")
                        c_1, c_2, c_3 = st.columns(3)
                        with c_1: em=st.checkbox("早",True); ms=st.time_input("早起",datetime.strptime("08:00","%H:%M").time()); me=st.time_input("早迄",datetime.strptime("12:00","%H:%M").time())
                        with c_2: ea=st.checkbox("午",True); as_=st.time_input("午起",datetime.strptime("15:00","%H:%M").time()); ae=st.time_input("午迄",datetime.strptime("18:00","%H:%M").time())
                        with c_3: ee=st.checkbox("晚",True); es=st.time_input("晚起",datetime.strptime("18:30","%H:%M").time()); ee_t=st.time_input("晚迄",datetime.strptime("21:30","%H:%M").time())
                    if st.form_submit_button("寫入"):
                        s = []
                        if em: s.append(f"{ms.strftime('%H:%M')}-{me.strftime('%H:%M')}")
                        if ea: s.append(f"{as_.strftime('%H:%M')}-{ae.strftime('%H:%M')}")
                        if ee: s.append(f"{es.strftime('%H:%M')}-{ee_t.strftime('%H:%M')}")
                        f_s = ",".join(s)
                        if sn and sd:
                            for n in sn:
                                m = st.session_state.working_df[name_col]==n
                                for d in sd: 
                                    if d in st.session_state.working_df.columns:
                                        st.session_state.working_df.loc[m,d] = f_s
                            st.session_state.modification_history.append("手動修改")
                            st.rerun()

            # --- 下載 ---
            st.markdown("---")
            c1, c2, c3 = st.columns(3)
            final = st.session_state.working_df
            with c1:
                o = io.BytesIO()
                with pd.ExcelWriter(o, engine='openpyxl') as w: final.to_excel(w, index=False)
                st.download_button("下載 Excel", o.getvalue(), '排班表.xlsx')
            with c2:
                try:
                    import csv
                    c = final.to_csv(index=False, encoding='cp950', errors='replace', quoting=csv.QUOTE_ALL)
                    st.download_button("下載 Big5 CSV", c, '排班表_Big5.csv', 'text/csv')
                except: pass
            with c3:
                u = final.to_csv(index=False, encoding='utf-8-sig')
                st.download_button("下載 UTF-8 CSV", u, '排班表_UTF8.csv', 'text/csv')

        except Exception as e: st.error(f"讀取錯誤: {e}")

# ==========================================
# 分頁 2: 完診分析 (除錯修正版)
# ==========================================
with tab2:
    st.header("批次完診分析")
    
    # 檔案類型選擇
    fs = st.radio(
        "請選擇檔案類型：", 
        ("🏥 原始系統匯出檔 (標題在第4列)", "📄 標準/分析結果檔 (標題在第1列)"), 
        horizontal=True
    )
    default_hr = 4 if "第4列" in fs else 1
    
    upl = st.file_uploader("上傳完診明細 (可多檔)", type=['xlsx','xls','csv'], accept_multiple_files=True, key="t2")
    hr_idx = st.number_input("資料標題在第幾列？", min_value=1, value=default_hr) - 1

    if upl:
        # 立即顯示預覽，方便除錯
        st.subheader("📋 檔案預覽 (檢查是否讀取成功)")
        try:
            f1 = upl[0]; f1.seek(0)
            if f1.name.lower().endswith('.csv'): 
                try: df_s = pd.read_csv(f1, header=hr_idx, encoding='cp950', nrows=5)
                except: 
                    f1.seek(0)
                    df_s = pd.read_csv(f1, header=hr_idx, encoding='utf-8', nrows=5)
            else: 
                df_s = pd.read_excel(f1, header=hr_idx, nrows=5)
            
            df_s.columns = df_s.columns.astype(str).str.strip()
            st.dataframe(df_s.head(3))
            
            cols = df_s.columns.tolist()
            c1, c2, c3 = st.columns(3)
            # 自動抓取欄位，若抓不到則預設為 0
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
                        # 讀標題 (找診所名)
                        if f.name.lower().endswith('.csv'): 
                            try: h = pd.read_csv(f, header=None, nrows=1, encoding='cp950')
                            except: 
                                f.seek(0); h = pd.read_csv(f, header=None, nrows=1, encoding='utf-8')
                        else: h = pd.read_excel(f, header=None, nrows=1)
                        c_name = str(h.iloc[0,0]).strip()[:4]

                        # 讀內容
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
                            res.append(p)
                        else:
                            error_log.append(f"{f.name}: 缺少欄位")
                    except Exception as e: error_log.append(f"{f.name}: {e}")
                    bar.progress((i+1)/len(upl))
                
                if res:
                    final = pd.concat(res, ignore_index=True)
                    # 排序
                    base = ['診所名稱', d_c]
                    shifts = [c for c in final.columns if c not in base]
                    def sk(n): return 0 if "早" in n else 1 if "午" in n else 2 if "晚" in n else 99
                    shifts.sort(key=sk)
                    final = final[base + shifts].fillna("")
                    
                    # 計算邏輯
                    mod = final.copy()
                    for c in shifts:
                        mod[c] = mod.apply(lambda r: calculate_time_rule(r[c], "早" if "早" in c else "午" if "午" in c else "晚", r['診所名稱']) or r[c], axis=1)
                    
                    st.success(f"完成！共合併 {len(res)} 個檔案。")
                    if error_log: st.warning(f"部分失敗: {error_log}")
                    
                    st.dataframe(mod.head())
                    c1, c2 = st.columns(2)
                    with c1:
                        o = io.BytesIO()
                        with pd.ExcelWriter(o, engine='openpyxl') as w: final.to_excel(w, index=False)
                        st.download_button("📥 原始結果 (Excel)", o.getvalue(), '原始完診總表.xlsx')
                    with c2:
                        o = io.BytesIO()
                        with pd.ExcelWriter(o, engine='openpyxl') as w: mod.to_excel(w, index=False)
                        st.download_button("📥 修正結果 (Excel)", o.getvalue(), '修正完診總表.xlsx', type="primary")
                else: 
                    st.error("無資料產生，請檢查欄位。")
                    if error_log: st.write(error_log)

        except Exception as e: 
            st.error(f"檔案讀取失敗: {e}")


