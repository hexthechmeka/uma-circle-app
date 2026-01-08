import streamlit as st
import pandas as pd
from google.cloud import vision
from google.oauth2 import service_account
import cv2
import numpy as np
import os
import re
from thefuzz import process
import gspread
from datetime import datetime, timedelta, timezone
import json

# --- 설정 ---
FIXED_SHEET_URL = "https://docs.google.com/spreadsheets/d/18iVfULr8tjVB8FvZ1yfMuZhua2EDxRuwfut9k201_tI/edit?gid=19537121#gid=19537121"

st.set_page_config(page_title="서클 관리자 (Admin)", layout="wide", page_icon="🛠️")
st.title("🛠️ 우마무스메 서클 관리자 (Admin Only)")

# --- [핵심] 인증 처리 함수 (클라우드/로컬 자동 감지) ---
def get_credentials():
    # 1. Streamlit Cloud 비밀 금고에 있는지 확인
    if "gcp_service_account" in st.secrets:
        return service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"]
        )
    # 2. 로컬 파일(secret.json)이 있는지 확인 (테스트용)
    elif os.path.exists("secret.json"):
        return service_account.Credentials.from_service_account_file("secret.json")
    else:
        return None

# --- 나머지 함수들 ---
def get_gc_client(creds):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    scoped_creds = creds.with_scopes(scope)
    return gspread.authorize(scoped_creds)

def fetch_members(sheet_url, creds):
    try:
        gc = get_gc_client(creds)
        sh = gc.open_by_url(sheet_url)
        try: ws = sh.worksheet("2.일간_전체")
        except: return []
        col_values = ws.col_values(1)
        return [str(name).strip() for name in col_values if str(name).strip() and name != '닉네임']
    except: return []

def add_member(sheet_url, creds, nickname):
    gc = get_gc_client(creds)
    sh = gc.open_by_url(sheet_url)
    try: ws = sh.worksheet("2.일간_전체")
    except: ws = sh.add_worksheet("2.일간_전체", 100, 20)
    existing = [str(x).strip() for x in ws.col_values(1)]
    if nickname.strip() in existing: return False
    ws.append_row([nickname.strip()])
    return True

def delete_members(sheet_url, creds, nicknames_to_delete):
    gc = get_gc_client(creds)
    sh = gc.open_by_url(sheet_url)
    ws = sh.worksheet("2.일간_전체")
    all_values = [str(x).strip() for x in ws.col_values(1)]
    rows_to_delete = []
    for i, val in enumerate(all_values):
        if val in nicknames_to_delete: rows_to_delete.append(i + 1)
    for row_idx in sorted(rows_to_delete, reverse=True): ws.delete_rows(row_idx)
    return True

def rename_member(sheet_url, creds, old_name, new_name):
    gc = get_gc_client(creds)
    sh = gc.open_by_url(sheet_url)
    ws = sh.worksheet("2.일간_전체")
    all_values = [str(x).strip() for x in ws.col_values(1)]
    if new_name.strip() in all_values: return False, "이미 존재하는 닉네임"
    try:
        row_idx = all_values.index(old_name.strip()) + 1
        ws.update_cell(row_idx, 1, new_name.strip())
        return True, "변경 성공"
    except ValueError: return False, "대상 없음"

def clean_nickname_simple(text):
    garbage_words = ['총','최종','획득','로그인','팬','수','팬수','RANK','Rank','pt','PT','서브','리더','멤버']
    for word in garbage_words: text = text.replace(word, '')
    text = re.sub(r'\[\s+', '[', text)
    text = re.sub(r'\s+\]', ']', text)
    text = re.sub(r'[\(\)\{\}iIl\|1C<>①②③★\-\:0-9\.,]+', '', text) 
    return text.strip()

def match_nickname(ocr_text, db_list):
    if not db_list or not ocr_text: return ocr_text
    clean_ocr = re.sub(r'\[.*?\]', '', ocr_text).strip()
    if not clean_ocr: return ocr_text
    best_match, score = process.extractOne(clean_ocr, db_list)
    if score >= 50: return best_match
    return ocr_text

def run_ocr_original(image_bytes, creds, member_db):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    crop_img = img[int(h*0.4):, :] 
    _, encoded_crop = cv2.imencode('.jpg', crop_img)
    crop_bytes = encoded_crop.tobytes()

    if img.shape[0] < 2000: img = cv2.resize(img, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    _, encoded_img = cv2.imencode('.jpg', img)
    content = encoded_img.tobytes()
    
    client = vision.ImageAnnotatorClient(credentials=creds)
    image = vision.Image(content=content)
    try:
        response = client.text_detection(image=image)
        texts = response.text_annotations
    except: return [], crop_bytes

    data_list = []
    if len(texts) > 1:
        all_texts = texts[1:]
        img_width = img.shape[1]
        fan_anchors = []
        for t in all_texts:
            raw = t.description.replace(',', '').strip()
            match = re.search(r'(\d{4,})', raw)
            if match:
                val = int(match.group(1))
                if val > 10000000000: val = int(str(val)[1:])
                box = t.bounding_poly.vertices
                fan_anchors.append({'val': val, 'lx': box[0].x, 'ty': box[0].y, 'by': box[2].y})
        u_anchors = []
        for a in fan_anchors:
            if not any(abs(a['ty'] - u['ty']) < 30 for u in u_anchors): u_anchors.append(a)
        
        for anc in u_anchors:
            frags = []
            for t in all_texts:
                box = t.bounding_poly.vertices
                cx, cy = (box[0].x + box[1].x)/2, (box[0].y + box[2].y)/2
                if not (anc['ty']-100 < cy < anc['by']+100): continue
                if cx >= anc['lx'] or cx < img_width*0.02: continue
                if re.search(r'^\d+$', t.description.replace(',','')): continue
                frags.append((box[0].x, t.description.strip()))
            if frags:
                frags.sort(key=lambda x: x[0])
                full = " ".join([f[1] for f in frags])
                cleaned = clean_nickname_simple(full)
                if cleaned:
                    corrected = match_nickname(cleaned, member_db)
                    data_list.append({'닉네임': corrected, '팬 수': anc['val']})
    return data_list, crop_bytes

def commit_to_sheet(sheet_url, creds, confirmed_df):
    gc = get_gc_client(creds)
    sh = gc.open_by_url(sheet_url)
    sheet_names = ["1.메인_요약", "2.일간_전체", "3.주간_기록", "4.월간_누적"]
    existing_titles = [ws.title for ws in sh.worksheets()]
    worksheets = {}
    for name in sheet_names:
        if name not in existing_titles: sh.add_worksheet(name, 100, 20)
        worksheets[name] = sh.worksheet(name)
    ws_daily = worksheets["2.일간_전체"]
    daily_data = ws_daily.get_all_values()
    KST = timezone(timedelta(hours=9))
    today_str = datetime.now(KST).strftime("%Y-%m-%d")
    log_messages = [] 
    
    if not daily_data:
        df_daily = confirmed_df.copy()
        df_daily.columns = ['닉네임', today_str]
        for _, row in confirmed_df.iterrows():
            log_messages.append(f"🆕 **{row['닉네임']}**: 신규 생성 -> {row['팬 수']:,}")
    else:
        header = daily_data[0]
        if '닉네임' not in header: header[0] = '닉네임'
        df_daily = pd.DataFrame(daily_data[1:], columns=header)
        if today_str not in df_daily.columns: df_daily[today_str] = ""
        df_daily['닉네임'] = df_daily['닉네임'].astype(str).str.strip()
        df_daily.set_index('닉네임', inplace=True)
        official_members = df_daily.index.tolist()

        for _, row in confirmed_df.iterrows():
            user_input_nick = str(row['닉네임']).strip()
            new_val = row['팬 수']
            target_nick = user_input_nick
            if user_input_nick in official_members: target_nick = user_input_nick
            else:
                match, score = process.extractOne(user_input_nick, official_members)
                if match and score >= 80: target_nick = match
            
            if target_nick in df_daily.index:
                old_val = df_daily.at[target_nick, today_str]
                try: old_val_int = int(str(old_val).replace(',',''))
                except: old_val_int = None
                df_daily.at[target_nick, today_str] = new_val
                if old_val_int != new_val:
                    prev_str = f"{old_val_int:,}" if old_val_int is not None else "(없음)"
                    log_messages.append(f"✅ **{target_nick}**: {today_str} {prev_str} ➝ **{new_val:,}**")
            else:
                new_row = pd.Series({today_str: new_val})
                df_to_add = pd.DataFrame([new_row], index=[target_nick])
                df_daily = pd.concat([df_daily, df_to_add])
                log_messages.append(f"🆕 **{target_nick}**: {today_str} (신규) ➝ **{new_val:,}**")
        df_daily.reset_index(inplace=True)
        df_daily = df_daily.fillna("")
    
    ws_daily.clear()
    ws_daily.update([df_daily.columns.values.tolist()] + df_daily.values.tolist())
    
    # 주간/월간 업데이트 (간략화)
    ws_weekly = worksheets["3.주간_기록"]
    cols = df_daily.columns.tolist()
    target_days = ['01', '08', '15', '22', '29']
    weekly_cols = ['닉네임']
    for col in cols:
        if col != '닉네임' and col.split('-')[2] in target_days: weekly_cols.append(col)
    valid_weekly = [c for c in weekly_cols if c in df_daily.columns]
    df_weekly = df_daily[valid_weekly].copy()
    ws_weekly.clear()
    ws_weekly.update([df_weekly.columns.values.tolist()] + df_weekly.values.tolist())

    ws_monthly = worksheets["4.월간_누적"]
    month_map = {}
    for col in cols:
        if col != '닉네임':
            m_prefix = col[:7]
            if m_prefix not in month_map or col > month_map[m_prefix]: month_map[m_prefix] = col
    monthly_cols = ['닉네임'] + sorted(list(month_map.values()))
    valid_monthly = [c for c in monthly_cols if c in df_daily.columns]
    df_monthly = df_daily[valid_monthly].copy()
    ws_monthly.clear()
    ws_monthly.update([df_monthly.columns.values.tolist()] + df_monthly.values.tolist())
    return log_messages

# --- Main UI ---
if 'member_db' not in st.session_state: st.session_state.member_db = []
if 'staging_data' not in st.session_state: st.session_state.staging_data = None
if 'uploaded_images' not in st.session_state: st.session_state.uploaded_images = []

creds = get_credentials()

with st.sidebar:
    st.header("⚙️ 관리자 설정")
    if not creds:
        st.error("❌ 인증키(Secrets) 설정이 필요합니다.")
        st.info("Streamlit Dashboard > Settings > Secrets 에 'gcp_service_account'를 추가하세요.")
    else:
        st.success("✅ 서버 인증 완료")
        
        st.markdown("---")
        st.header("👤 서클원 관리")
        if st.button("🔄 명단 새로고침") or not st.session_state.member_db:
            st.session_state.member_db = fetch_members(FIXED_SHEET_URL, creds)
        
        new_mem = st.text_input("닉네임 추가")
        if new_mem and st.button("추가 실행"):
            if add_member(FIXED_SHEET_URL, creds, new_mem):
                st.success(f"{new_mem} 추가됨")
                st.session_state.member_db.append(new_mem)
                st.rerun()

        if st.session_state.member_db:
            st.markdown("---")
            target_mem = st.selectbox("변경할 닉네임", st.session_state.member_db)
            changed_name = st.text_input("새 닉네임")
            if st.button("✏️ 변경 실행"):
                success, msg = rename_member(FIXED_SHEET_URL, creds, target_mem, changed_name)
                if success:
                    st.success("변경 완료")
                    st.rerun()
                else: st.error(msg)
            
            st.markdown("---")
            del_mem = st.multiselect("삭제할 닉네임", st.session_state.member_db)
            if del_mem and st.button("❌ 삭제 실행"):
                delete_members(FIXED_SHEET_URL, creds, del_mem)
                st.success("삭제 완료")
                st.rerun()

if creds:
    if st.session_state.staging_data is None:
        st.subheader("📸 데이터 업데이트 (OCR)")
        files = st.file_uploader("이미지 파일", accept_multiple_files=True)
        if files and st.button("🔍 분석 시작"):
            st.session_state.uploaded_images = []
            temp_data = []
            bar = st.progress(0)
            for i, f in enumerate(files):
                data_list, crop_img = run_ocr_original(f.getvalue(), creds, st.session_state.member_db)
                temp_data.extend(data_list)
                st.session_state.uploaded_images.append(crop_img)
                bar.progress((i+1)/len(files))
            if temp_data:
                st.session_state.staging_data = pd.DataFrame(temp_data).sort_values('팬 수', ascending=False).drop_duplicates('닉네임')
                st.rerun()
            else: st.error("인식 실패")
    else:
        col_img, col_table = st.columns([4, 6])
        with col_img:
            for idx, img_bytes in enumerate(st.session_state.uploaded_images):
                st.image(img_bytes, caption=f"이미지 {idx+1}")
        with col_table:
            edited_df = st.data_editor(st.session_state.staging_data, num_rows="dynamic", use_container_width=True)
            if st.button("✅ 시트 반영"):
                logs = commit_to_sheet(FIXED_SHEET_URL, creds, edited_df)
                st.success("완료!")
                for log in logs: st.markdown(log)
                st.session_state.staging_data = None
                st.session_state.uploaded_images = []
            if st.button("🗑️ 취소"):
                st.session_state.staging_data = None
                st.session_state.uploaded_images = []
                st.rerun()