import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import re

# ==========================================
# 1. 頁面與全域設定
# ==========================================
st.set_page_config(page_title="診所行政智能排班", layout="wide", page_icon="🏥")

# CSS 優化視覺體驗
st.markdown("""
    <style>
    .stDataFrame {border: 1px solid #f0f2f6; border-radius: 8px;}
    .stSuccess {background-color: #d4edda; color: #155724;}
    .stWarning {background-color: #fff3cd; color: #856404;}
    </style>
""", unsafe_allow_html=True)

st.title("🏥 診所行政智能排班系統")
st.caption("🚀 流程：上傳排班表 ➝ 確認人員身分 (醫師/純早/一般) ➝ 上傳完診檔 ➝ 完成！")

# 側邊欄：重置與說明
with st.sidebar:
    st.header("🔧 工具箱")
    if st.button("🔄 重置所有狀態", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    st.info("""
    **身分定義說明：**
    - 👨‍⚕️ **醫師**：預設不執行回填。
    - 🌅 **純早班**：早班基準時間固定為 13:00。
    - 👤 **一般人員**：早班基準 12:00，非立丞午診固定 18:00。
    """)

# 初始化 Session State
if 'staff_roles_df' not in st.session_state: st.session_state.staff_roles_df = None
if 'working_df' not in st.session_state: st.session_state.working_df = None

# ==========================================
# 2. 核心邏輯函式
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

def calculate_time_rule(raw_time_str, shift_type, clinic_name, role):
    if not raw_time_str or str(raw_time_str).lower() == 'nan': return None
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

        # 根據身分決定邏輯
        is_pure_morning = (role == "🌅 純早班")

        if shift_type == "早":
            std = base_date.replace(hour=13, minute=0) if is_pure_morning else base_date.replace(hour=12, minute=0)
            if t > std: new_t = t + timedelta(minutes=5)
            elif t < std: new_t = std
        
        elif shift_type == "午":
            if not is_licheng: return "18:00"
            std = base_date.replace(hour=17, minute=0)
            if t > std: new_t = t + timedelta(minutes=5)
            elif t < std: new_t = std

        elif shift_type == "晚":
            std = base_date.replace(hour=21, minute=0) if is_licheng else base_date.replace(hour=21, minute=30)
            if t > std: new_t = t + timedelta(minutes=5)
            elif t < std: new_t = std
            
        return new_t.strftime("%H:%M")
    except: return None

# ==========================================
# 3. 主界面邏輯
# ==========================================

# --- 步驟 1: 上傳與人員辨識 ---
st.subheader("步驟 1：上傳排班表並確認人員身分")
uploaded_file = st.file_uploader("拖或是點擊上傳原始排班表 (Excel/CSV)", type=['xlsx', 'xls', 'csv'], label_visibility="collapsed")

if uploaded_file:
    try:
        # 讀取檔案邏輯 (保持強大的相容性)
        if st.session_state.working_df is None or uploaded_file.name != st.session_state.get('last_filename'):
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
            
            st.session_state.working_df = df_raw
            st.session_state.last_filename = uploaded_file.name

            # --- 自動偵測邏輯 (人性化的關鍵) ---
            df = st.session_state.working_df
            all_cols = df.columns.tolist()
            name_col = next((c for c in all_cols if "姓名" in c), all_cols[0])
            
            # 建立人員角色清單
            staff_data = []
            seen_names = set()
            
            for idx, row in df.iterrows():
                name = str(row[name_col]).strip()
                if not name or name == 'nan' or name in seen_names: continue
                seen_names.add(name)
                
                # 掃描整列內容來判斷身分
                row_str = " ".join([str(v) for v in row.values if not pd.isna(v)])
                
                # 預設判斷
                role = "👤 一般人員"
                is_active = True
                
                if "醫師" in row_str or "★" in name:
                    role = "👨‍⚕️ 醫師"
                    is_active = False # 醫師預設不打勾
                elif "純早" in row_str:
                    role = "🌅 純早班"
                
                staff_data.append({
                    "姓名": name,
                    "身分 (可修改)": role,
                    "是否執行更新": is_active
                })
            
            st.session_state.staff_roles_df = pd.DataFrame(staff_data)

    # --- 顯示「人員角色儀表板」 ---
    if st.session_state.staff_roles_df is not None:
        st.info("👇 系統已自動判斷身分，請直接在下方表格修改 (若判斷正確則無需更動)")
        
        col_editor, col_info = st.columns([2, 1])
        
        with col_editor:
            # 這是最強大的功能：st.data_editor 讓使用者直接在表格操作，不用下拉選單
            edited_roles = st.data_editor(
                st.session_state.staff_roles_df,
                column_config={
                    "身分 (可修改)": st.column_config.SelectboxColumn(
                        "身分設定",
                        help="請選擇該人員的屬性",
                        width="medium",
                        options=[
                            "👨‍⚕️ 醫師",
                            "🌅 純早班",
                            "👤 一般人員"
                        ],
                        required=True,
                    ),
                    "是否執行更新": st.column_config.CheckboxColumn(
                        "執行回填?",
                        help="取消勾選則不會更動此人的排班",
                        default=True,
                    )
                },
                disabled=["姓名"],
                hide_index=True,
                use_container_width=True,
                height=300
            )
            # 更新 Session State 中的角色表
            st.session_state.staff_roles_df = edited_roles

        with col_info:
            # 即時統計顯示
            n_doc = len(edited_roles[edited_roles["身分 (可修改)"] == "👨‍⚕️ 醫師"])
            n_mor = len(edited_roles[edited_roles["身分 (可修改)"] == "🌅 純早班"])
            n_nor = len(edited_roles[edited_roles["身分 (可修改)"] == "👤 一般人員"])
            n_run = len(edited_roles[edited_roles["是否執行更新"] == True])
            
            st.markdown(f"""
            #### 📊 偵測統計
            - 👨‍⚕️ **醫師**：{n_doc} 人
            - 🌅 **純早班**：{n_mor} 人
            - 👤 **一般人員**：{n_nor} 人
            ---
            - ✅ **預計更新人數**：{n_run} 人
            """)

    # --- 步驟 2: 上傳完診檔與執行 ---
    st.divider()
    st.subheader("步驟 2：上傳完診分析檔並執行")
    
    analysis_file = st.file_uploader("上傳完診結果檔 (Excel/CSV)", type=['xlsx', 'xls', 'csv'])

    if analysis_file and st.session_state.staff_roles_df is not None:
        try:
            # 讀取完診檔
            if analysis_file.name.lower().endswith('.csv'):
                df_ana = pd.read_csv(analysis_file, encoding='utf-8', dtype=str)
            else: df_ana = pd.read_excel(analysis_file, dtype=str)
            
            if '診所名稱' in df_ana.columns and '日期' in df_ana.columns:
                clinics = df_ana['診所名稱'].unique().tolist()
                
                c1, c2, c3 = st.columns([1,2,1])
                with c1: 
                    selected_clinic = st.selectbox("選擇診所", clinics)
                
                with c2:
                    st.write("") # Spacer
                    st.write("") 
                    run_btn = st.button("🚀 開始智能回填", type="primary", use_container_width=True)

                if run_btn:
                    # 準備資料
                    role_map = {row['姓名']: row['身分 (可修改)'] for _, row in st.session_state.staff_roles_df.iterrows()}
                    active_users = set(st.session_state.staff_roles_df[st.session_state.staff_roles_df['是否執行更新'] == True]['姓名'])
                    
                    df_target = df_ana[df_ana['診所名稱'] == selected_clinic]
                    
                    # 建立時間對照表 (日期 -> {早, 午, 晚})
                    # 找出完診檔對應欄位
                    ana_cols = df_ana.columns.tolist()
                    col_m = next((c for c in ana_cols if "早" in c), None)
                    col_a = next((c for c in ana_cols if "午" in c), None)
                    col_e = next((c for c in ana_cols if "晚" in c), None)
                    
                    time_map = {
                        smart_date_parser(r['日期']): {
                            '早': r.get(col_m), '午': r.get(col_a), '晚': r.get(col_e)
                        } for _, r in df_target.iterrows()
                    }

                    changes_list = []
                    df_work = st.session_state.working_df
                    date_cols = [c for c in df_work.columns if re.match(r'\d{4}-\d{2}-\d{2}', str(c))]
                    name_col = next((c for c in df_work.columns if "姓名" in c), df_work.columns[0])
                    is_licheng = "立丞" in str(selected_clinic)

                    # 開始比對與計算
                    progress_bar = st.progress(0)
                    total_rows = len(df_work)
                    
                    for idx, row in df_work.iterrows():
                        name = row[name_col]
                        
                        # 如果不在「執行更新」名單中，跳過
                        if name not in active_users: 
                            progress_bar.progress((idx + 1) / total_rows)
                            continue

                        user_role = role_map.get(name, "👤 一般人員")
                        
                        for col in date_cols:
                            if col in time_map:
                                cell_val = str(row[col]).strip()
                                if cell_val and cell_val.lower() != 'nan':
                                    # 解析排班 (支援 "早", "早班", "08:00-12:00" 等)
                                    shifts = re.split(r'[,\n\s]', cell_val)
                                    has_m, has_a, has_e = False, False, False
                                    
                                    for s in shifts:
                                        if not s: continue
                                        if "全" in s: has_m=True; has_a=True; has_e=True
                                        if "早" in s: has_m=True
                                        if "午" in s: has_a=True
                                        if "晚" in s: has_e=True
                                        # 數字判斷
                                        if not any(k in s for k in ["早","午","晚","全"]):
                                            try:
                                                th = int(s.split(':')[0]) if ':' in s else int(s.split('-')[0].split(':')[0])
                                                if th < 13: has_m=True
                                                elif 13<=th<18: has_a=True
                                                elif th>=18: has_e=True
                                            except: pass

                                    # 取得實際完診時間並計算
                                    vals = time_map[col]
                                    fm = calculate_time_rule(vals['早'], "早", selected_clinic, user_role) if has_m else None
                                    fa = calculate_time_rule(vals['午'], "午", selected_clinic, user_role) if has_a else None
                                    fe = calculate_time_rule(vals['晚'], "晚", selected_clinic, user_role) if has_e else None

                                    # 組合新字串
                                    parts = []
                                    if has_m and fm: parts.append(f"08:00-{fm}")
                                    
                                    if is_licheng:
                                        if has_a and fa: parts.append(f"15:00-{fa}")
                                        if has_e and fe: parts.append(f"18:30-{fe}")
                                    else:
                                        # 非立丞
                                        if has_m and has_a and not has_e:
                                            if fa: parts.append(f"15:00-{fa}")
                                        elif not has_m and has_a and has_e:
                                            # 午晚班：若有午班就補上
                                            if fa: parts.insert(0 if not parts else len(parts), f"15:00-{fa}")
                                        elif not has_m and has_a and not has_e:
                                            if fa: parts.append(f"15:00-{fa}")
                                        elif not has_m and not has_a and has_e:
                                            if fe: parts.append(f"18:30-{fe}")
                                    
                                    final_val = ",".join(parts)
                                    
                                    # 若有變動則記錄
                                    if final_val and final_val != cell_val:
                                        # 直接寫入 (因為已經是確認執行的)
                                        st.session_state.working_df.at[idx, col] = final_val
                                        changes_list.append({
                                            "姓名": name,
                                            "日期": col,
                                            "原內容": cell_val,
                                            "新內容": final_val
                                        })
                        
                        progress_bar.progress((idx + 1) / total_rows)

                    if changes_list:
                        st.success(f"🎉 成功更新 {len(changes_list)} 筆排班資料！")
                        with st.expander("查看更新明細"):
                            st.dataframe(pd.DataFrame(changes_list))
                        
                        # 下載區
                        st.subheader("📥 下載更新後的排班表")
                        c_d1, c_d2, c_d3 = st.columns(3)
                        final_df = st.session_state.working_df
                        
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
                    else:
                        st.warning("比對完成，但沒有發現需要更新的資料 (可能資料一致或時間未達標)。")

        except Exception as e:
            st.error(f"發生錯誤: {e}")
