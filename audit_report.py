import os
import requests
import smtplib
import re
import holidays
import anthropic
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
    
def get_naver_news_data(keyword, seen_texts, client_id, client_secret, days_to_fetch):
    url = f"https://openapi.naver.com/v1/search/news.json?query={keyword}&display=20&sort=date"
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}

    
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
        search_limit = datetime.now(kst) - timedelta(days=days_to_fetch)
    
        for item in data.get('items', []):
            title = item['title'].replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&amp;", "&")
            desc = item['description'].replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&amp;", "&")
            
            try:
                pub_date = datetime.strptime(item['pubDate'], '%a, %d %b %Y %H:%M:%S +0900').replace(tzinfo=kst)
            except:
                continue
            if pub_date < search_limit: 
                continue
            
            full_text = title + " " + desc
            if any(term in full_text for term in exclude_terms): continue
            
            current_content = (title)[:200]
            if any(is_similar(current_content, s) > 0.3 for s in seen_texts):
                continue
            
            seen_texts.append(current_content)
            # ✅ score는 0으로 초기화, 나중에 메인 루프에서 제목 기준으로 합산
            news_items.append({
                "title": title,
                "desc": desc,   # ✅ 본문 추가
                "link": item['link'],
                "score": 0
            })
            
        return news_items
    except Exception as e:
        print(f"네이버 API 호출 오류 ({keyword}): {e}")
        return []
def filter_news_by_ai(news_items, category_desc):
    """Claude AI가 뉴스 관련성을 판단해서 필터링"""
    if not news_items:
        return []

    client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

    # 제목 목록을 번호와 함께 텍스트로 구성
    news_list_text = "\n".join([
        f"{i+1}. {news['title']} / {news.get('desc', '')[:100]}"
        for i, news in enumerate(news_items)
    ])

    prompt = f"""아래는 네이버 뉴스 검색 결과입니다.
당신은 '{category_desc}' 업무 담당자입니다.
각 뉴스가 해당 업무와 관련이 있는지 판단해주세요.

관련 있음 기준:
- 현대캐피탈의 감사, 내부통제, 소비자보호, 민원, 불완전판매, 금융사고, 제재, 검사 관련
- 금융권 전반의 소비자보호, 내부통제, 컴플라이언스 이슈
- 금융당국의 소비자보호, 내부통제 관련 규제/제도 변화

관련 없음 기준:
- 단순 금리/상품 홍보, 스포츠, 연예, 일반 사회 뉴스
- 현대캐피탈과 무관한 타업종 뉴스

뉴스 목록:
{news_list_text}

응답 형식: 관련 있는 뉴스 번호만 쉼표로 구분해서 답하세요. 예) 1,3,5
관련 있는 뉴스가 없으면 "없음" 이라고만 답하세요."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        result_text = response.content[0].text.strip()

        if result_text == "없음":
            return []

        # 반환된 번호로 해당 뉴스 추출
        selected_indices = [int(n.strip()) - 1 for n in result_text.split(',') if n.strip().isdigit()]
        return [news_items[i] for i in selected_indices if 0 <= i < len(news_items)]

    except Exception as e:
        print(f"AI 필터링 오류: {e}")
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
            "금융감독원": 5, "금감원":5, "금융감독원 검사": 5, "금감원 검사": 5, "금융위원회" : 5, 
            "금융감독원 제재": 4, "금감원 제재": 4, 
            "금융위" : 3, "금감원 규제" : 3, "금융당국" : 3, 
            "개인정보위" : 2,  "개보위" : 2, "규제완화" : 2, "규제강화" : 2, "건전성" : 2, "금융위원장" : 2, "금감원장" : 2, "금감원 긴급" : 2,
            "금감원 횡령" : 1
        },
        "🏢 자사 및 업계 동향": {
            "현대캐피탈": 5, 
            "캐피탈사 사고": 4, 
            "캐피탈사 사기": 3,  "캐피탈업계" : 3, 
            "금융권" : 2, "여전업권" : 2, "여전업계" : 2, 
            "리스/할부": 1,  "여신금융협회" : 1
        },
        "⚠️ 내부통제 및 리스크": {
            "금융권 내부통제": 5, 
            "금융사고": 3, "보안사고": 3, "유출사고": 3, 
            "과징금": 2, "과태료": 2, "의무위반": 2, 
            "개인정보보호": 1
        }
    }

    # 전체 키워드 통틀어 중복을 체크하기 위한 리스트
    global_seen_texts = []
    final_html_body = ""
    
    for category_name, keywords_dict in audit_categories.items():
        category_all_news = []
        for kw, score in keywords_dict.items():
            category_all_news.extend(get_naver_news_data(kw, global_seen_texts, NAVER_ID, NAVER_SECRET, days_to_fetch))
        
        # ✅ 수집 후, 각 기사 제목 안에 포함된 키워드의 score 합산
        for news in category_all_news:
            total_score = 0
            matched_keywords = []
            # 제목 + 본문 200자 합쳐서 체크 범위 설정
            check_text = (news['title'] + " " + news.get('desc', ''))[:200]
            seen_kw_scores = {}  # 중복 키워드 방지: 같은 키워드는 최초 1회만 계산
            for kw, kw_score in keywords_dict.items():
                if kw in check_text and kw not in seen_kw_scores:
                    seen_kw_scores[kw] = kw_score
                    total_score += kw_score
                    matched_keywords.append(f"{kw}({kw_score})")
            news['score'] = total_score
            news['matched_keywords'] = matched_keywords

        if category_all_news:
            # score 0 제외 후 높은 순 정렬, 최대 20개
            category_all_news.sort(key=lambda x: x['score'], reverse=True)
            top_5_news = [news for news in category_all_news if news['score'] > 0][:20]

            
            combined_items = ""
            for news in top_5_news:
                matched_str = ", ".join(news.get('matched_keywords', []))
                combined_items += f"""
                <li style='margin-bottom: 12px;'>
                    <span style='font-size: 10pt; color: #888; margin-right: 6px;'>score : {news['score']}</span>
                    <span style='font-size: 9pt; color: #e07000; margin-right: 6px;'>[{matched_str}]</span>
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
# ✅ 기존 카테고리 루프 (유지)
    for category_name, keywords_dict in audit_categories.items():
        # ... 기존 코드 그대로 ...

    # ✅ 새 카테고리: AI 필터링 기반 현대캐피탈 감사/소비자보호 뉴스
    ai_category_keywords = {
        "현대캐피탈": 5,
        "소비자보호": 3,
        "민원": 2,
        "불완전판매": 3,
        "내부통제": 3,
        "컴플라이언스": 2,
        "금융사고": 2,
    }

    ai_raw_news = []
    ai_seen_texts = []  # AI 카테고리 전용 중복 체크 (global과 별도)
    for kw in ai_category_keywords.keys():
        ai_raw_news.extend(get_naver_news_data(kw, global_seen_texts, NAVER_ID, NAVER_SECRET, days_to_fetch))

    # AI가 관련성 판단
    ai_filtered_news = filter_news_by_ai(ai_raw_news, "현대캐피탈 감사 및 통제부서, 소비자보호")

    if ai_filtered_news:
        ai_combined_items = ""
        for news in ai_filtered_news[:20]:
            ai_combined_items += f"""
            <li style='margin-bottom: 12px;'>
                <span style='font-size: 9pt; color: #27ae60; margin-right: 6px;'>[AI 선별]</span>
                <a href='{news['link']}' style='text-decoration: none; color: #1a0dab; font-size: 11pt;'>• {news['title']}</a>
            </li>"""

        final_html_body += f"""
        <div style="margin-top: 30px; margin-bottom: 20px; padding: 15px; background-color: #f0fff4; border-radius: 8px;">
            <h2 style="color: #27ae60; font-size: 14pt; border-bottom: 2px solid #27ae60; padding-bottom: 5px; margin-top: 0;">
                🤖 현대캐피탈 감사·소비자보호 (AI 선별)
            </h2>
            <ul style="list-style-type: none; padding-left: 0; margin-top: 15px;">
                {ai_combined_items}
            </ul>
        </div>
        """

    if final_html_body:
        send_audit_report(final_html_body, image_file)
    else:
        print("수집된 뉴스가 없습니다.")
    if final_html_body:
        send_audit_report(final_html_body, image_file)
    else:
        print("수집된 뉴스가 없습니다.")
