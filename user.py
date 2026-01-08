import streamlit as st
import pandas as pd
from google.oauth2 import service_account
import gspread
import os
from textwrap import dedent

FIXED_SHEET_URL = "https://docs.google.com/spreadsheets/d/18iVfULr8tjVB8FvZ1yfMuZhua2EDxRuwfut9k201_tI/edit?gid=19537121#gid=19537121"
TARGET_GROWTH = 10000000 

# [핵심] 툴바 모드를 'minimal'로 설정 (코드 레벨에서 제어)
st.set_page_config(page_title="서클 현황", layout="wide", initial_sidebar_state="collapsed", menu_items=None)

# 🚨 [Nuclear Option] 상단바, 푸터, 햄버거 메뉴 강제 제거 CSS
st.markdown("""
<style>
    /* 1. 상단 헤더 전체 숨기기 (Created by 포함) */
    header {
        visibility: hidden !important;
        height: 0px !important;
        padding: 0px !important;
    }
    
    /* 2. 햄버거 메뉴, 설정 버튼 등 숨기기 */
    #MainMenu {visibility: hidden !important;}
    div[data-testid="stToolbar"] {display: none !important;}
    div[data-testid="stDecoration"] {display: none !important;}
    div[data-testid="stStatusWidget"] {display: none !important;}
    
    /* 3. 하단 푸터 숨기기 */
    footer {visibility: hidden !important; display: none !important;}
    
    /* 4. 앱 컨텐츠를 위로 끌어올리기 (헤더가 사라진 빈공간 채우기) */
    .block-container {
        padding-top: 0rem !important;
        padding-bottom: 0rem !important;
    }
    
    /* 디자인: 배경 및 카드 */
    .stApp { background-color: #121212; color: #E0E0E0; }
    .user-card { background-color: #1E1E1E; border: 1px solid #333; border-radius: 16px; padding: 24px; margin: 20px 0; box-shadow: 0 4px 12px rgba(0,0,0,0.5); --prog-width: 0%; --prog-color: #555; }
    .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
    .user-name { font-size: 24px; font-weight: 700; color: #FFFFFF; }
    .status-badge { padding: 6px 12px; border-radius: 20px; font-size: 13px; font-weight: 600; color: #fff; background-color: var(--prog-color); }
    .text-dark { color: #000 !important; }
    .progress-track { background-color: #333; height: 12px; border-radius: 6px; overflow: hidden; margin-bottom: 8px; }
    .progress-fill { height: 100%; transition: width 0.6s ease; width: var(--prog-width); background-color: var(--prog-color); }
    .progress-text { text-align: right; font-size: 12px; color: #888; margin-bottom: 20px; }
    .stat-row { display: flex; justify-content: space-between; border-top: 1px solid #333; padding-top: 16px; }
    .stat-item { display: flex; flex-direction: column; }
    .stat-label { font-size: 12px; color: #AAA; margin-bottom: 4px; }
    .stat-value { font-size: 18px; font-weight: 700; color: #FFF; }
    .stat-right { text-align: right; }
    .update-info { margin-top: 15px; text-align: right; font-size: 11px; color: #666; font-style: italic; }
    div.stButton > button { width: 100%; background-color: #2C2C2C; color: white; border: 1px solid #444; padding: 12px; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

if 'page' not in st.session_state: st.session_state.page = 'home'

@st.cache_data(ttl=600)
def load_data():
    try:
        if "gcp_service_account" in st.secrets:
            creds = service_account.Credentials.from_service_account_info(st.secrets["gcp_service_account"])
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = creds.with_scopes(scope)
        elif os.path.exists("secret.json"):
            creds = service_account.Credentials.from_service_account_file("secret.json")
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = creds.with_scopes(scope)
        else: return pd.DataFrame(), "인증 실패", {}

        gc = gspread.authorize(creds)
        sh = gc.open_by_url(FIXED_SHEET_URL)
        
        ws = sh.worksheet("1.메인_요약")
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        if not df.empty:
            df['닉네임'] = df['닉네임'].astype(str)
            for c in ['현재 팬 수', '이번달 팬수']:
                if c in df.columns:
                    df[c] = df[c].astype(str).str.replace(',', '').apply(pd.to_numeric, errors='coerce').fillna(0)

        global_date = "-"
        user_date_map = {}
        
        try:
            ws_daily = sh.worksheet("2.일간_전체")
            all_values = ws_daily.get_all_values()
            
            if len(all_values) > 1:
                headers = all_values[0]
                data_rows = all_values[1:]
                
                for col_i in range(len(headers) - 1, -1, -1):
                    if headers[col_i].strip() == "닉네임": continue
                    has_data = False
                    for row in data_rows:
                        if len(row) > col_i and str(row[col_i]).strip() != "":
                            has_data = True
                            break
                    if has_data:
                        global_date = headers[col_i]
                        break
                
                for row in data_rows:
                    nickname = str(row[0]).strip()
                    my_last_date = "-"
                    for col_i in range(len(headers) - 1, 0, -1):
                        if col_i < len(row) and str(row[col_i]).strip() != "":
                            my_last_date = headers[col_i]
                            break
                    user_date_map[nickname] = my_last_date
        except Exception:
            global_date = "-"
        
        return df, global_date, user_date_map

    except: return pd.DataFrame(), "로드 실패", {}

df, global_update_date, user_date_map = load_data()

def show_home():
    st.title("내 기록 조회")
    if df.empty:
        st.info("데이터가 준비되지 않았습니다.")
        return
    
    search_query = st.text_input("닉네임 검색", placeholder="닉네임 입력...")
    target_user = None
    if search_query:
        mask = df['닉네임'].str.contains(search_query, case=False)
        if mask.any(): target_user = df[mask].iloc[0]
        else: st.warning("검색 결과가 없습니다.")
    
    if target_user is not None:
        user_nick = target_user['닉네임']
        this_month_val = float(target_user['이번달 팬수'])
        current = float(target_user['현재 팬 수'])
        
        pct = (this_month_val / TARGET_GROWTH) * 100
        is_done = pct >= 100
        fill_width = min(pct, 100)
        
        bar_color = "#00E676" if is_done else "#FF5252"
        badge_txt = "할당량 달성" if is_done else f"{100-pct:.1f}% 남음"
        text_cls = "text-dark" if is_done else ""
        
        my_date = user_date_map.get(user_nick, global_update_date)

        html_code = dedent(f"""
<div class="user-card" style="--prog-width: {fill_width}%; --prog-color: {bar_color};">
<div class="card-header">
<div class="user-name">{user_nick}</div>
<div class="status-badge {text_cls}">{badge_txt}</div>
</div>
<div class="progress-track"><div class="progress-fill"></div></div>
<div class="progress-text">할당량: {pct:.1f}%</div>
<div class="stat-row">
<div class="stat-item"><span class="stat-label">이번달 팬수</span><span class="stat-value">+{int(this_month_val):,}</span></div>
<div class="stat-item stat-right"><span class="stat-label">현재 총 팬 수</span><span class="stat-value">{int(current):,}</span></div>
</div>
<div class="update-info">집계 기준: {my_date}</div>
</div>
""")
        st.markdown(html_code, unsafe_allow_html=True)

def show_list():
    st.title("전체 랭킹")
    if df.empty: return
    
    st.caption(f"전체 집계 기준: {global_update_date}")
    
    tab1, tab2 = st.tabs(["이번달 팬수 순", "총 팬 수 순"])
    with tab1: st.dataframe(df.sort_values('이번달 팬수', ascending=False)[['닉네임', '이번달 팬수']], use_container_width=True, hide_index=True)
    with tab2: st.dataframe(df.sort_values('현재 팬 수', ascending=False)[['닉네임', '현재 팬 수']], use_container_width=True, hide_index=True)

if st.session_state.page == 'home': show_home()
elif st.session_state.page == 'list': show_list()
st.write("---")
c1, c2 = st.columns(2)
if c1.button("홈 (검색)"): st.session_state.page = 'home'; st.rerun()
if c2.button("랭킹 보기"): st.session_state.page = 'list'; st.rerun()
