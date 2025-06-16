import streamlit as st
from datetime import date, timedelta
import os
import uuid
from PIL import Image, ImageDraw, ImageFont
from pdf2image import convert_from_path, convert_from_bytes
from io import BytesIO
import textwrap
from streamlit_drawable_canvas import st_canvas
import pandas as pd
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.header import Header
from email.utils import formataddr
import re
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials

PDF_TEMPLATE_PATH = "consent.pdf"
TRANSFER_FORM_PATH = "transfer.pdf"
FONT_PATH = "malgun.ttf"
CONSENT_SAMPLE_PATH = "consent_sample.pdf"
TRANSFER_SAMPLE_PATH = "transfer_sample.pdf"
XLSX_FILE_PATH = "school_data.xlsx"

MAIL_FROM = os.getenv("MAIL_FROM")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT"))

# ────────────────────────────────────────────────────────
def init_gspread_client():
    """
    st.secrets["GSHEET"]["SERVICE_ACCOUNT_KEY"] 에 담긴 JSON 문자열을 파싱하여
    OAuth2 인증을 수행하고, gspread 클라이언트를 반환합니다.
    """
    service_account_info = json.loads(st.secrets["GSHEET"]["SERVICE_ACCOUNT_KEY"])
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scopes)
    client = gspread.authorize(credentials)
    return client

_gspread_client = None
def get_gspread_client():
    """
    전역 변수 _gspread_client에 한 번만 init 후 반환하도록 합니다.
    """
    global _gspread_client
    if _gspread_client is None:
        _gspread_client = init_gspread_client()
    return _gspread_client

def get_worksheet():
    """
    get_gspread_client()를 통해 인증된 client를 얻고,
    st.secrets["GSHEET"]["SPREADSHEET_ID"] + st.secrets["GSHEET"]["SHEET_NAME"]를 이용해
    실제 Worksheet 객체를 리턴합니다.
    """
    client = get_gspread_client()
    spreadsheet_id = st.secrets["GSHEET"]["SPREADSHEET_ID"]
    sheet_name = st.secrets["GSHEET"].get("SHEET_NAME", "Sheet1")
    sh = client.open_by_key(spreadsheet_id)
    try:
        worksheet = sh.worksheet(sheet_name)
    except Exception:
        worksheet = sh.get_worksheet(0)
    return worksheet
# ────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────
def log_submission_to_sheets(school: str, grade: str, student_name: str, transfer_date: date):
    """
    제출 완료 시 호출합니다.
    [타임스탬프(한국 시간), 학교명, 학생 성명, 전학 예정 학년, 전학 예정일] 순서로 시트에 한 줄을 추가합니다.
    """
    try:
        ws = get_worksheet()
        # 기존 grade, student_name 처리 유지
        if not grade:
            grade = st.session_state.get("next_grade_input", "")
        if not student_name:
            student_name = st.session_state.get("student_name", "")

        # transfer_date 인자가 없으면 session_state에서 가져오기
        if not transfer_date:
            transfer_date = st.session_state.get("transfer_date_input", None)

        # (2) 대한민국(Asia/Seoul) 로컬 시간으로 타임스탬프 생성
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")

        # 전학 예정일을 문자열로 변환 (ISO)
        transfer_date_str = transfer_date.strftime("%Y-%m-%d") if transfer_date else ""
        ws.append_row([now, school, student_name, grade, transfer_date_str])
    except Exception as e:
        st.error(f"구글 시트 로깅 중 오류 발생: {e}")
# ────────────────────────────────────────────────────────

try:
    favicon_image = Image.open("my_favicon.png")
    st.set_page_config(
        page_title="전입학예정확인서",
        page_icon=favicon_image,
        layout="centered"
    )
except FileNotFoundError:
    st.warning("파비콘 이미지 파일을 찾을 수 없습니다. 기본 아이콘이 사용됩니다.")
    st.set_page_config(page_title="전입학예정확인서", layout="centered")

def grade_to_english(grade):
    number = re.search(r'\d+', grade)
    if number:
        return f"{number.group()}gr"
    return grade

def convert_pdf_to_images(pdf_path, dpi=150):
    try:
        images = convert_from_path(pdf_path, dpi=dpi)
        return images
    except Exception as e:
        st.error(f"PDF를 이미지로 변환 중 오류 발생: {e}")
        return None

st.markdown("""
    <style>
    .title {
        font-size: 2.5rem;
        font-weight: bold;
        text-align: center;
        padding-bottom: 0.2rem;
        margin-bottom: 0rem;
        white-space: nowrap;
    }
    .pdf-viewer {
        width: 100%;
        height: 500px;
        border: 1px solid #d1d5db;
        margin-bottom: 2rem;
    }
    .instruction-message {
        background-color: #f0fdf4;
        color: #15803d;
        padding: 0.75rem;
        margin-bottom: 1rem;
        border-radius: 0.375rem;
        border: 1px solid #bbf7d0;
        font-size: 0.875rem;
        text-align: center;
    }
    @media (max-width: 480px) {
        .title {
                font-size: 2.2rem;
        }
    }
    </style>
    <div class="title">전입학예정확인서</div>
""", unsafe_allow_html=True)

st.markdown('<div class="instruction-message">🍀 진  행 순  서 🍀<br> ①지역 및 학교 → ②개인정보 수집·이용 동의서 → ③전입학예정확인서 → ④미리보기 및 제출</div>', unsafe_allow_html=True)

# Streamlit Session State 초기화
if 'stage' not in st.session_state:
    st.session_state.stage = 1
    st.session_state.agree_to_collection = "none"
    st.session_state.schools_by_region = {}
    st.session_state.selected_region = ""
    st.session_state.selected_school = ""
    st.session_state.student_name = ""
    st.session_state.move_date = None
    st.session_state.student_birth_date = None
    st.session_state.pdf_bytes = None
    st.session_state.filename = None
    st.session_state.next_grade_input = ""
    st.session_state.transfer_date_input = None


def validate_inputs(student_name, parent_name, student_school, student_birth_date,
                    parent_phone, address, transfer_date, next_grade, move_date, relationship):
    if not all([student_name, parent_name, student_school, student_birth_date,
                parent_phone, address, transfer_date, next_grade, move_date, relationship]):
        return False, "모든 작성칸을 빈칸 없이 예시에 따라 작성하세요."

    valid_grades = {"1학년", "2학년", "3학년", "4학년", "5학년", "6학년"}
    if next_grade not in valid_grades:
        return False, "전학 예정 학년을 올바르게 선택하세요."

    return True, ""

def send_pdf_email(pdf_data, filename, recipient_email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, recipient_email):
        st.error(f"유효하지 않은 이메일 주소입니다: {recipient_email}")
        return False

    parts = filename.split('_')
    if len(parts) >= 3:
        grade = parts[2].replace('.pdf', '')
        english_grade = grade_to_english(grade)
        email_filename = f"Confirmation of Prospective School Transfer_{english_grade}.pdf"
    else:
        email_filename = "Confirmation of Prospective School Transfer.pdf"

    msg = MIMEMultipart()
    msg['From'] = formataddr((str(Header("전입학예정확인서 시스템", 'utf-8')), MAIL_FROM))
    msg['To'] = recipient_email
    msg['Subject'] = f"전입학예정확인서({filename})"

    body = f"안녕하세요.\n\n{filename}가 제출되었습니다.\nPDF 파일에 이상이 없는지 확인해 주세요.\n보다 편리한 관리를 위해 파일명 변경을 권장드립니다.\n아울러, 철저한 개인정보 관리 부탁드립니다.\n\n감사합니다."
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    part = MIMEBase('application', 'pdf')
    part.set_payload(pdf_data)
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', f'attachment; filename="{email_filename}"', filename=('utf-8', '', email_filename))
    part.add_header('Content-Type', f'application/pdf; name="{email_filename}"')
    msg.attach(part)

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(MAIL_FROM, MAIL_PASSWORD)
        server.sendmail(MAIL_FROM, recipient_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        st.error(f"이메일 발송 실패: {e}")
        st.error("이메일 설정을 확인하고 다시 시도해주세요.")
        return False

def clear_session_state():
    keys_to_keep = []
    for key in list(st.session_state.keys()):
        if key not in keys_to_keep:
            del st.session_state[key]

def format_phone_number(phone_input):
    digits = ''.join(filter(str.isdigit, phone_input))
    if len(digits) != 11 or not digits.startswith('010'):
        return None, "휴대전화 번호는 010으로 시작하며 숫자로만 작성하세요."
    # 010-XXXX-XXXX 형식으로 변환
    formatted = f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    return formatted, None

# 1단계: 지역 및 학교 선택
if st.session_state.stage == 1:
    st.subheader("1단계: 지역 및 학교")
    st.markdown('<div class="instruction-message">전입 예정 지역 및 전학 예정 학교를 선택하세요.</div>', unsafe_allow_html=True)

    try:
        df = pd.read_excel(XLSX_FILE_PATH)
        if not all(col in df.columns for col in ['지역', '학교', '이메일']):
            st.error("XLSX 파일에 '지역', '학교', '이메일' 컬럼이 있어야 합니다. 파일 내용을 확인하고 다시 시도해주세요.")
            st.stop()
        st.session_state.schools_by_region = df.groupby('지역')['학교'].apply(list).to_dict()
        regions = list(st.session_state.schools_by_region.keys())
    except Exception as e:
        st.error(f"XLSX 파일을 읽는 중 오류가 발생했습니다: {e}. 파일 경로 및 형식을 확인해주세요. 경로: {XLSX_FILE_PATH}")
        st.stop()

    st.session_state.selected_region = st.selectbox("전입 예정 지역을 선택하세요.", regions)

    available_schools = st.session_state.schools_by_region.get(st.session_state.selected_region, [])
    if not available_schools:
        st.warning("선택한 지역에 학교 정보가 없습니다. 다른 지역을 선택해주세요.")
        st.session_state.selected_school = ""
    else:
        st.session_state.selected_school = st.selectbox("전학 예정 학교를 선택하세요.", available_schools)

    if st.button("✒️다음 단계로"):
        if st.session_state.selected_region and st.session_state.selected_school:
            st.session_state.stage = 2
            st.rerun()
        else:
            st.warning("지역과 학교를 모두 선택하세요.")

# 2단계: 개인정보 수집·이용 동의서
elif st.session_state.stage == 2:
    st.subheader("2단계: 개인정보 수집·이용 동의서")
    st.markdown('<div class="instruction-message">개인정보 수집·이용 동의서를 확인 후 진행하세요.</div>', unsafe_allow_html=True)

    consent_images = convert_pdf_to_images(CONSENT_SAMPLE_PATH, dpi=150)
    if consent_images:
        with st.expander("📄 개인정보 수집·이용 동의서", expanded=True):
            for i, image in enumerate(consent_images):
                st.image(image, use_container_width=True)
    else:
        st.error("동의서 샘플 PDF를 불러올 수 없습니다. 파일 경로를 확인해주세요.")

    consent_choice = st.radio(
        "☞ 위와 같이 개인정보 수집·이용에 동의하십니까?",
        options=["동의합니다.", "동의하지 않습니다."],
        index=None,
        key="consent_radio"
    )
    if consent_choice == "동의합니다.":
        if st.button("✒️다음 단계로"):
            st.session_state.stage = 3
            st.rerun()
    elif consent_choice == "동의하지 않습니다.":
        st.warning("개인정보 수집·이용에 동의 시에만 다음 단계로 진행할 수 있습니다.")

# 3단계: 전입학예정확인서
elif st.session_state.stage == 3:
    st.subheader("3단계: 전입학예정확인서")
    st.markdown('<div class="instruction-message">모든 작성칸을 올바르게 작성하세요.</div>', unsafe_allow_html=True)

    transfer_images = convert_pdf_to_images(TRANSFER_SAMPLE_PATH, dpi=150)
    if transfer_images:
        with st.expander("📄 전입학예정확인서 예시", expanded=True):
            for i, image in enumerate(transfer_images):
                st.image(image, use_container_width=True)
    else:
        st.error("전입학예정확인서 샘플 PDF를 불러올 수 없습니다. 파일 경로를 확인해주세요.")

    # ────────────────────────────────────────────────────────
    # 3행×2열 레이아웃: 왼쪽(학생), 오른쪽(법정대리인)
    col1, col2 = st.columns(2)
    with col1:
        # (학생) 성명
        student_name = st.text_input(
            "(학생) 성명",
            placeholder="예) 한잎새",
            key="student_name_input"
        )
        if student_name and not re.match(r'^[가-힣]+$', student_name):
            st.error("한글로만 작성하세요.")
            st.session_state.student_name = ""
        else:
            st.session_state.student_name = student_name

        # (학생) 생년월일
        today = date.today()
        min_date = today - timedelta(days=30*365)
        max_date = today + timedelta(days=30*365)
        st.session_state.student_birth_date = st.date_input(
            "(학생) 생년월일",
            value=None,
            min_value=min_date,
            max_value=max_date,
            key="student_birth_date_input"
        )

        # (학생) 현 소속 학교 및 학년
        student_school = st.text_input(
            "(학생) 현 소속 학교 및 학년",
            placeholder="예) 00초등학교, 00중학교, 00고등학교 1학년",
            key="student_school_input"
        )
        if student_school:
            if "학교" not in student_school:
                st.error("'학교'와 '학년' 단어를 반드시 포함하여 작성하세요.")
                student_school = ""
            elif not re.search(r"\d+학년", student_school):
                st.error("'학교'와 '학년' 단어를 반드시 포함하여 작성하세요.")
                student_school = ""
            elif not re.match(r'^[가-힣0-9\s]+$', student_school) or re.match(r'^\d+$', student_school):
                st.error("한글과 숫자로만 작성하세요.")
                student_school = ""
    with col2:
        # (법정대리인) 성명
        parent_name = st.text_input(
            "(법정대리인) 성명",
            placeholder="예) 한나무",
            key="parent_name_input"
        )
        if parent_name and not re.match(r'^[가-힣]+$', parent_name):
            st.error("한글로만 작성하세요.")
            parent_name = ""

        # (법정대리인) 학생과의 관계
        relationship = st.text_input(
            "(법정대리인) 학생과의 관계",
            placeholder="예) 부, 모, 조부, 조모 등",
            key="relationship_input"
        )
        if relationship and not re.match(r'^[가-힣\s]+$', relationship):
            st.error("한글로만 작성하세요.")
            relationship = ""

        # (법정대리인) 휴대전화 번호
        parent_phone_input = st.text_input(
            "(법정대리인) 휴대전화 번호",
            placeholder="예) 01056785678",
            key="parent_phone_input"
        )
        if parent_phone_input:
            formatted_parent_phone, error = format_phone_number(parent_phone_input)
            if error:
                st.error(error)
                parent_phone = ""
            else:
                parent_phone = formatted_parent_phone
        else:
            parent_phone = ""

    # ────────────────────────────────────────────────────────
    # 순차 배열: 전입 예정일, 전입 예정 주소, 전학 예정일, 전학 예정 학교, 전학 예정 학년
    st.session_state.move_date = st.date_input(
        "전입 예정일",
        value=None,
        key="move_date_input"      # 키 이름 통일
    )

    address = st.text_input(
        "전입 예정 주소",
        placeholder="예) 행복택지 A-1블록 사랑아파트",
        key="address_input"
    )
    if address and not re.match(r'^[가-힣a-zA-Z0-9\s\-]+$', address):
        st.error("한글, 알파벳, 숫자, 기호로만 작성하세요.")
        address = ""

    # (전학) 전학 예정일
    transfer_date = st.date_input(
        "전학 예정일",
        value=None,
        key="transfer_date_input"   # 키를 새로 지정
    )
    st.session_state.transfer_date = transfer_date

    # (전학) 전학 예정 학교
    school_name = st.text_input(
        "전학 예정 학교",
        value=st.session_state.selected_school,
        disabled=True
    )

    # (전학) 전학 예정 학년
    next_grade_raw = st.text_input(
        "전학 예정 학년",
        placeholder="예) 3학년 → 3 / 숫자만 입력",
        key="next_grade_num_input"
    )
    if next_grade_raw:
        if re.fullmatch(r"[1-6]", next_grade_raw):
            next_grade = f"{next_grade_raw}학년"
        else:
            st.error("1~6 사이의 숫자만 입력하세요.")
            next_grade = ""
    else:
        next_grade = ""

    col1, col2 = st.columns(2)
    with col1:
        st.write("학생 서명")
        canvas_student = st_canvas(
            fill_color="rgba(255, 255, 255, 0)",
            stroke_width=5,
            background_color="rgba(255, 255, 255, 0)",
            height=150,
            width=300,
            drawing_mode="freedraw",
            key="student_sign_canvas"
        )
    with col2:
        st.write("법정대리인 서명")
        canvas_parent = st_canvas(
            fill_color="rgba(255, 255, 255, 0)",
            stroke_width=5,
            background_color="rgba(255, 255, 255, 0)",
            height=150,
            width=300,
            drawing_mode="freedraw",
            key="parent_sign_canvas"
        )

    if st.button("✒️다음 단계로"):
        valid, error = validate_inputs(
            st.session_state.student_name,
            parent_name,
            student_school,
            st.session_state.student_birth_date,
            parent_phone,
            address,
            transfer_date,    
            next_grade,
            st.session_state.move_date,
            relationship
        )
        if not valid:
            st.error(error)
            st.stop()

        st.session_state.next_grade_input = next_grade
        
        try:
            def calculate_signature_coverage(image_data):
                alpha_channel = image_data[:, :, 3]
                drawn_pixels = (alpha_channel > 0).sum()
                total_pixels = image_data.shape[0] * image_data.shape[1]
                return drawn_pixels / total_pixels

            student_coverage = calculate_signature_coverage(canvas_student.image_data)
            parent_coverage = calculate_signature_coverage(canvas_parent.image_data)

            if student_coverage < 0.05 or parent_coverage < 0.05:
                st.warning("학생과 법정대리인 모두 올바르게 서명하세요.")
                st.stop()

            student_sign_buffer = BytesIO()
            parent_sign_buffer = BytesIO()
            Image.fromarray(canvas_student.image_data.astype('uint8'), mode='RGBA').save(student_sign_buffer, format='PNG', optimize=True)
            Image.fromarray(canvas_parent.image_data.astype('uint8'), mode='RGBA').save(parent_sign_buffer, format='PNG', optimize=True)

            pages1 = convert_from_path(PDF_TEMPLATE_PATH, dpi=200)
            page1 = pages1[0].convert('RGBA')
            pages2 = convert_from_path(TRANSFER_FORM_PATH, dpi=200)
            page2 = pages2[0].convert('RGBA')
            draw1 = ImageDraw.Draw(page1)
            draw2 = ImageDraw.Draw(page2)

            consent_positions = {
                "{{date.today}}": [(1100, 1550)],
                "{{student_name}}": [(825, 1695)],
                "{{student_sign_path}}": [(1060, 1665)],
                "{{parent_name}}": [(825, 1835)],
                "{{parent_sign_path}}": [(1060, 1810)],
                "{{school_name}}": [(925, 1988)],
            }
            transfer_positions = {
                "{{student_name}}": [(462, 420), (825, 1755)],
                "{{parent_name}}": [(1110, 420), (825, 1888)],
                "{{student_school}}": [(462, 625)],
                "{{relationship}}": [(1110, 520)],
                "{{student_birth_date}}": [(462, 520)],
                "{{parent_phone}}": [(1110, 620)],
                "{{move_date}}": [(462, 825)],
                "{{address}}": [(1110, 810), (490, 1170)],
                "{{transfer_date}}": [(462, 930)],
                "{{school_name}}": [(462, 1035), (310, 1235), (925, 2056)],
                "{{next_grade}}": [(1110, 1035), (840, 1235)],
                "{{date.today}}": [(1100, 1620)],
                "{{student_sign_path}}": [(1060, 1730)],
                "{{parent_sign_path}}": [(1060, 1870)],
            }

            def get_font(key, idx):
                if key == "{{address}}" and idx == 0:
                    return ImageFont.truetype(FONT_PATH, 32)
                if key == "{{address}}" and idx == 1:
                    return ImageFont.truetype(FONT_PATH, 40)
                if key == "{{student_school}}" and idx == 0:
                    return ImageFont.truetype(FONT_PATH, 32)
                return ImageFont.truetype(FONT_PATH, 42)

            consent_map = {
                "{{student_name}}": st.session_state.student_name,
                "{{parent_name}}": parent_name,
                "{{date.today}}": date.today().strftime("%Y년 %m월 %d일"),
                "{{school_name}}": school_name,
            }
            transfer_map = {
                **consent_map,
                "{{student_school}}": student_school,
                "{{relationship}}": relationship,
                "{{student_birth_date}}": st.session_state.student_birth_date.strftime("%Y년 %m월 %d일"),
                "{{parent_phone}}": parent_phone,
                "{{move_date}}": st.session_state.move_date.strftime("%Y년 %m월 %d일"),
                "{{address}}": address,
                "{{transfer_date}}": transfer_date.strftime("%Y년 %m월 %d일"),
                "{{next_grade}}": next_grade,
            }

            def draw_texts(draw, positions, data_map, is_transfer=False):
                for key, coords in positions.items():
                    for idx, (x, y) in enumerate(coords):
                        text = data_map.get(key, "")
                        font = get_font(key, idx)
                        if not is_transfer:
                            if key in ["{{student_name}}", "{{parent_name}}", "{{student_sign_path}}", "{{parent_sign_path}}"]:
                                x -= 15
                        else:
                            if key == "{{address}}":
                                if idx == 0:
                                    x -= 7
                                    wrapped_lines = textwrap.wrap(text, width=11)
                                    current_y = y
                                    for line in wrapped_lines:
                                        draw.text((x, current_y), line, font=font, fill='black')
                                        current_y += font.getbbox(line)[3] - font.getbbox(line)[1]
                                    continue
                                elif idx == 1:
                                    x -= 50
                            if key == "{{next_grade}}" and idx == 1:
                                x += 50
                        draw.text((x, y), text, font=font, fill='black')

            draw_texts(draw1, consent_positions, consent_map, is_transfer=False)
            student_sign_buffer.seek(0)
            parent_sign_buffer.seek(0)
            sign1 = Image.open(student_sign_buffer).resize((312, 104)).convert('RGBA')
            sign2 = Image.open(parent_sign_buffer).resize((312, 104)).convert('RGBA')
            for x, y in consent_positions.get("{{student_sign_path}}", []):
                page1.paste(sign1, (x - 15, y), sign1)
            for x, y in consent_positions.get("{{parent_sign_path}}", []):
                page1.paste(sign2, (x - 15, y), sign2)

            draw_texts(draw2, transfer_positions, transfer_map, is_transfer=True)
            student_sign_buffer.seek(0)
            parent_sign_buffer.seek(0)
            sign1 = Image.open(student_sign_buffer).resize((312, 104)).convert('RGBA')
            sign2 = Image.open(parent_sign_buffer).resize((312, 104)).convert('RGBA')
            for x, y in transfer_positions.get("{{student_sign_path}}", []):
                page2.paste(sign1, (x, y), sign1)
            for x, y in transfer_positions.get("{{parent_sign_path}}", []):
                page2.paste(sign2, (x, y), sign2)

            buffer = BytesIO()
            page1 = page1.convert('RGB')
            page2 = page2.convert('RGB')
            page1.save(buffer, format='PDF', quality=70)
            page2.save(buffer, format='PDF', append=True, save_all=True, quality=70)
            pdf_bytes = buffer.getvalue()
            filename = f"전입학예정확인서_{school_name}_{next_grade}.pdf"

            st.session_state.pdf_bytes = pdf_bytes
            st.session_state.filename = filename
            st.session_state.stage = 4
            st.rerun()

        except Exception as e:
            st.error(f"PDF 생성 중 오류 발생: {e}")
        finally:
            try:
                student_sign_buffer.close()
                parent_sign_buffer.close()
            except Exception as e:
                st.warning(f"메모리 버퍼 정리 중 오류 발생: {e}")

# 4단계: 미리보기 및 제출
elif st.session_state.stage == 4:
    st.subheader("4단계: 미리보기 및 제출")
    st.markdown('<div class="instruction-message">미리보기를 통해 최종 확인 후 제출하세요.</div>', unsafe_allow_html=True)

    if st.session_state.pdf_bytes and st.session_state.filename:
        try:
            images = convert_from_bytes(st.session_state.pdf_bytes, dpi=150)
            with st.expander("📄 전입학예정확인서 미리보기", expanded=True):
                for i, image in enumerate(images):
                    st.image(image, use_container_width=True)

            st.download_button(
                label="💾 전입학예정확인서 내려받기",
                data=st.session_state.pdf_bytes,
                file_name=st.session_state.filename,
                mime='application/pdf'
            )

            if st.button("📮 전입학예정확인서 제출하기"):
                with st.spinner("제출 중입니다. 잠시만 기다려 주세요."):
                    try:
                        df = pd.read_excel(XLSX_FILE_PATH)
                        email_series = df[df['학교'] == st.session_state.selected_school]['이메일']
                        if email_series.empty:
                            st.error(f"학교 '{st.session_state.selected_school}'에 해당하는 이메일이 없습니다.")
                            st.error("오류가 발생했습니다. 다시 처음부터 진행해주세요.")
                            clear_session_state()
                            st.stop()
                        selected_school_email = email_series.values[0]
                        if send_pdf_email(st.session_state.pdf_bytes, st.session_state.filename, selected_school_email):
                            st.success("정상적으로 제출되었습니다. 협조해 주셔서 감사합니다.")
                            log_submission_to_sheets(
                                st.session_state.selected_school,
                                st.session_state.next_grade_input,
                                st.session_state.student_name,
                                st.session_state.get("transfer_date", None)
                            )
                            clear_session_state()
                        else:
                            st.error("오류가 발생했습니다. 다시 처음부터 진행해주세요.")
                            clear_session_state()
                    except Exception as e:
                        st.error(f"이메일 발송 중 오류 발생: {e}")
                        st.error("오류가 발생했습니다. 다시 처음부터 진행해주세요.")
                        clear_session_state()
        except Exception as e:
            st.error(f"PDF 미리보기 이미지 생성 중 오류 발생: {e}")
            st.error("PDF 파일을 다운로드하여 확인해 주세요.")
            st.download_button(
                label="💾 전입학예정확인서 내려받기",
                data=st.session_state.pdf_bytes,
                file_name=st.session_state.filename,
                mime='application/pdf'
            )
            clear_session_state()
    else:
        st.error("PDF가 생성되지 않았습니다. 3단계로 돌아가 PDF를 생성해 주세요.")
        clear_session_state()
