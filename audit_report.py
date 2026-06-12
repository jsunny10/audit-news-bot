import os
import requests
import smtplib
import re
import holidays
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.utils import formataddr
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

# --- 1. 휴일 체크 및 수집 범위(일수) 계산 함수 ---
def get_fetch_days():
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).date()
    
    kr_holidays = holidays.KR()
    labor_day = datetime(today.year, 5, 1).date() # 근로자의 날(은행 휴무)
    
    def check_is_holiday(dt):
        return dt.weekday() >= 5 or dt in kr_holidays or dt == labor_day

    # 오늘이 휴일이면 None 반환 (배치 중단용)
    if check_is_holiday(today):
        return None

    # 평일인 경우, 직전 평일 이후로 며칠이 지났는지 계산
    fetch_days = 1
    check_date = today - timedelta(days=1)
    while check_is_holiday(check_date):
        fetch_days += 1
        check_date -= timedelta(days=1)
            
    return fetch_days

def is_similar(a, b):
    # 제목/본문 유사도를 측정 (0.5 이상이면 중복으로 간주)
    return SequenceMatcher(None, a, b).ratio()

def get_naver_news_data(keyword, score, seen_texts, client_id, client_secret, days_to_fetch):
    url = f"https://openapi.naver.com/v1/search/news.json?query={keyword}&display=20&sort=date"
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    
    # 제외 키워드 리스트
    exclude_terms = [
        '배구', '스포츠', 'V리그', '배구단', '감독', '블랑', '챔프전', '우승', '경기', '득점', '승리', '리그', 'MVP', '한선수', '선수', '허수봉', '남자부',
        '시상식', '한국배구연맹', '연예', '방송', '드라마', '영화', '출연', '배우', '가수', '아이돌', '하정우', '공연', '티켓', '예매', '슬리피',
        '데뷔', '컴백', '시청률', '예능', '넷플릭스', '유튜브', '구독자', '영상', '채널', '게임', '콘서트', '팬미팅', '음원', '차트', '화보', '결혼', '이혼', '열애', '뮤지컬',
        '배구', '스포츠', 'V리그', '감독', '우승', '경기', '득점', '승리', '리그', '선수', '연예', '방송', '드라마', '영화', '배우', '가수', '아이돌', '데뷔', '컴백'
    ]
    
    news_items = []
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json()
        
        kst = timezone(timedelta(hours=9))
        # ✅ 메인에서 계산된 days_to_fetch를 사용하여 검색 제한 시간 설정
        search_limit = datetime.now(kst) - timedelta(days=days_to_fetch)
    
        # kst = timezone(timedelta(hours=9))
        # one_day_ago = datetime.now(kst) - timedelta(days=1)
        
        for item in data.get('items', []):
            title = item['title'].replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&amp;", "&")
            desc = item['description'].replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&amp;", "&")
            
            # 1. 날짜 파싱 및 필터링 (공백 주의)
            try:
                pub_date = datetime.strptime(item['pubDate'], '%a, %d %b %Y %H:%M:%S +0900').replace(tzinfo=kst)
            except:
                continue # 날짜 형식이 안 맞으면 건너뜀
            if pub_date < search_limit: 
                continue
            
            # if pub_date < one_day_ago: continue
            
            # 2. 제외 키워드 필터링
            full_text = title + " " + desc
            if any(term in full_text for term in exclude_terms): continue
            
            # 3. 중복/유사도 필터링 (앞 200자 기준)
            # current_content = (title + " " + desc)[:200]
            current_content = (title)[:200]
            if any(is_similar(current_content, s) > 0.3 for s in seen_texts):
                continue
            
            seen_texts.append(current_content)
            news_items.append({
                "title": title,
                "link": item['link'],
                "score": score
            })
            
        return news_items
    except Exception as e:
        print(f"네이버 API 호출 오류 ({keyword}): {e}")
        return []

def send_audit_report(html_content, image_path):
    send_email_addr = "hcsaudit.news@gmail.com"
    app_pw = os.getenv('EMAIL_PW')
    target_emails = os.getenv('TARGET_EMAILS')
    
    if not app_pw or not target_emails:
        print("메일 환경변수가 설정되지 않았습니다.")
        return

    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    date_str = now_kst.strftime('%Y-%m-%d')
    
    msg = MIMEMultipart('related')
    msg['Subject'] = f"[{date_str}] Audit News Report ⭐"
    msg['From'] = formataddr(("현대캐피탈 감사실", send_email_addr))
    # msg['To'] = target_emails
    # ✅ 수정 포인트 1: 수신자(To)에는 발신자 주소나 대표 명칭만 표시
    # 이렇게 하면 받는 사람 입장에서 '나에게만 온 것'처럼 보이거나 대표 주소만 보입니다.
    msg['To'] = formataddr(("현대캐피탈 감사실", send_email_addr))
    # msg['To'] = send_email_addr 

    # 실제 수신자 리스트 생성
    recipient_list = [addr.strip() for addr in target_emails.split(',')]

    full_html = f"""
    <html><body style="font-family: 'Malgun Gothic', sans-serif;">
        <div style="max-width: 650px; margin: 0 auto; border: 1px solid #eee; padding: 25px;">
            <div style="text-align: center; margin-bottom: 20px;">
                <img src="cid:header_logo" style="max-width: 100%; height: auto; border: none;">
            </div>
            <p style="text-align: right; font-size: 9pt; color: #888;">발송 시각: {now_kst.strftime('%H:%M')}</p>
            <p style="font-size: 11pt; color: #000; font-weight: bold; margin: 5px 0 0 0; text-align: right;">※ 인터넷 공간, 외부메일조회 시스템에서 뉴스별 링크 접근이 가능합니다.</p>
            {html_content}
        </div>
    </body></html>
    """
    msg.attach(MIMEText(full_html, 'html'))
    
    if os.path.exists(image_path):
        with open(image_path, 'rb') as f:
            msg_img = MIMEImage(f.read())
            msg_img.add_header('Content-ID', '<header_logo>')
            msg_img.add_header('Content-Disposition', 'inline', filename=os.path.basename(image_path))
            msg.attach(msg_img)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(send_email_addr, app_pw)
            
            # ✅ 수정 포인트 2: 실제 발송은 recipient_list(모든 수신자)에게 보냄
            # msg['To']에는 대표 주소만 적혀 있지만, 실제 배달은 모든 수신자에게 갑니다.
            server.sendmail(send_email_addr, recipient_list, msg.as_string())
            print(f"✅ 리포트 숨은참조 발송 성공!")
    except Exception as e:
        print(f"❌ 발송 실패: {e}")
        
 #   try:
 #       with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
 #           server.login(send_email_addr, app_pw)
 #           recipients = [addr.strip() for addr in target_emails.split(',')]
 #           server.sendmail(send_email_addr, recipients, msg.as_string())
 #           print(f"✅ 리포트 발송 성공!")
 #   except Exception as e:
 #       print(f"❌ 발송 실패: {e}")

if __name__ == "__main__":
    # ✅ 1. 휴일 체크 및 수집 기간 계산
    days_to_fetch = get_fetch_days()
    
    if days_to_fetch is None:
        print("🚩 오늘은 한국 공휴일 또는 주말입니다. 배치를 종료합니다.")
        exit() # 휴일에는 프로세스 즉시 종료

    print(f"🔍 최근 {days_to_fetch}일치 데이터를 수집합니다.")
    
    NAVER_ID = os.getenv('NAVER_ID')
    NAVER_SECRET = os.getenv('NAVER_SECRET')
    
    base_path = os.path.dirname(os.path.abspath(__file__))
    image_file = os.path.join(base_path, "hcs.png")

    audit_categories = {
        "🏛️ 금감원 및 감독기구": {
            "금융감독원": 5, "금융감독원 검사": 4, "금감원 검사": 4, "금융감독원 제재": 3, "금감원 제재": 3, "금감원 횡령" : 1,
            "금감원 규제" : 2, "개인정보위" : 2,  "개보위" : 2, "규제완화" : 2, "규제강화" : 2
        },
        "🏢 자사 및 업계 동향": {
            "현대캐피탈": 5, "캐피탈사 사고": 4, "캐피탈사 사기": 3,  "리스/할부": 1, "금융권" : 2
        },
        "⚠️ 내부통제 및 리스크": {
            "금융권 내부통제": 5, "금융사고": 3, "보안사고": 3, "유출사고": 3, "과징금": 2, "과태료": 2, "의무위반": 2, "개인정보보호": 1
        }
    }

    # 전체 키워드 통틀어 중복을 체크하기 위한 리스트
    global_seen_texts = []
    final_html_body = ""
    
    for category_name, keywords_dict in audit_categories.items():
        category_all_news = []
        for kw, score in keywords_dict.items():
            # global_seen_texts를 전달하여 키워드 간 중복도 방지
            category_all_news.extend(get_naver_news_data(kw, score, global_seen_texts, NAVER_ID, NAVER_SECRET, days_to_fetch))
        
        if category_all_news:
            # 점수 높은 순으로 정렬
            category_all_news.sort(key=lambda x: x['score'], reverse=True)
            # 상위 5개 추출
            top_5_news = category_all_news[:20]
            
            combined_items = ""
            for news in top_5_news:
                combined_items += f"""
                <li style='margin-bottom: 12px;'>
                    <span style='font-size: 10pt; color: #888; margin-right: 6px;'>score : {news['score']}</span>
                    <a href='{news['link']}' style='text-decoration: none; color: #1a0dab; font-size: 11pt;'>• {news['title']}</a>
                </li>"""

            final_html_body += f"""
            <div style="margin-top: 30px; margin-bottom: 20px; padding: 15px; background-color: #f9f9f9; border-radius: 8px;">
                <h2 style="color: #2c3e50; font-size: 14pt; border-bottom: 2px solid #2c3e50; padding-bottom: 5px; margin-top: 0;">{category_name}</h2>
                <ul style="list-style-type: none; padding-left: 0; margin-top: 15px;">
                    {combined_items}
                </ul>
            </div>
            """

    if final_html_body:
        send_audit_report(final_html_body, image_file)
    else:
        print("수집된 뉴스가 없습니다.")
