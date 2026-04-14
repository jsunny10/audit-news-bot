import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.utils import formataddr, formatdate
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

def is_similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

# [복구] 뉴스 수집 및 제외 키워드 필터링 로직
def get_naver_news_data(keyword, score, seen_titles, client_id, client_secret):
    url = f"https://openapi.naver.com/v1/search/news.json?query={keyword}&display=20&sort=date"
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    
    # 제외할 키워드 리스트
    exclude_terms = [
        '배구', '스포츠', 'V리그', '배구단', '감독', '블랑', '챔프전', '우승', '경기', '득점', '승리', '리그', 'MVP', '한선수', '선수',
            '시상식', '한국배구연맹',
            '연예', '방송', '드라마', '영화', '출연', '배우', '가수', '아이돌', '하정우', '공연', '티켓', '예매', '슬리피',
            '데뷔', '컴백', '시청률', '예능', '넷플릭스', '유튜브', '구독자', '영상', '채널', '게임',
            '콘서트', '팬미팅', '음원', '차트', '화보', '결혼', '이혼', '열애', '뮤지컬', '독점공개'
    ]
    
    news_items = []
    try:
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        data = res.json()
        
        kst = timezone(timedelta(hours=9))
        one_day_ago = datetime.now(kst) - timedelta(days=1)
        
        for item in data.get('items', []):
            title = item['title'].replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&amp;", "&")
            desc = item['description'].replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&amp;", "&")
            pub_date = datetime.strptime(item['pubDate'], '%a, %d %b %Y %H:%M:%S +0900').replace(tzinfo=kst)
            
            # 1. 날짜 필터링 (최근 24시간)
            if pub_date < one_day_ago: continue
            
            # 2. 제외 키워드 필터링 (제목 + 본문 요약 검색)
            full_text = title + " " + desc
            if any(term in full_text for term in exclude_terms): continue
            
            # 3. 중복 필터링
            if any(is_similar(title[:20], s[:20]) > 0.6 for s in seen_titles): continue
            
            seen_titles.append(title)
            news_items.append({
                "title": title,
                "link": item['link'],
                "score": score
            })
            
        return news_items
    except:
        return []

def send_audit_report(html_content, image_path):
    # 이메일 발송 설정 (기존과 동일)
    send_email_addr = "hcsaudit.news@gmail.com"
    app_pw = os.getenv('EMAIL_PW')
    target_emails = os.getenv('TARGET_EMAILS')
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    date_str = now_kst.strftime('%Y-%m-%d')
    
    msg = MIMEMultipart('related')
    msg['Subject'] = f"[{date_str}] Audit News Report ⭐"
    msg['From'] = formataddr(("현대캐피탈 감사실", send_email_addr))
    msg['To'] = target_emails
    additional_text = "※ 인터넷 공간, 외부메일조회 시스템에서 뉴스별 링크 접근이 가능합니다."

    full_html = f"""
    <html><body style="font-family: 'Malgun Gothic', sans-serif;">
        <div style="max-width: 650px; margin: 0 auto; border: 1px solid #eee; padding: 25px;">
            <div style="text-align: center; background-color: #000; padding: 10px;">
                <img src="cid:header_logo" style="max-width: 100%;">
            </div>
            <p style="text-align: right; font-size: 9pt; color: #888;">발송 시각: {now_kst.strftime('%H:%M')}</p>
            <p style="font-size: 11pt; color: #000; font-weight: bold; margin: 5px 0 0 0; text-align: right;">{additional_text}</p>
            {html_content}
        </div>
    </body></html>
    """
    msg.attach(MIMEText(full_html, 'html'))
    if os.path.exists(image_path):
        with open(image_path, 'rb') as f:
            msg_img = MIMEImage(f.read()); msg_img.add_header('Content-ID', '<header_logo>'); msg.attach(msg_img)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(send_email_addr, app_pw); server.send_message(msg)

if __name__ == "__main__":
    NAVER_ID = os.getenv('NAVER_ID')
    NAVER_SECRET = os.getenv('NAVER_SECRET')
    base_path = os.path.dirname(os.path.abspath(__file__))
    image_file = os.path.join(base_path, "hcs.png")

    audit_categories = {
        "🏛️ 금감원 및 감독기구": {
            "금융감독원": 3, "금융감독원 검사": 2, "금감원 검사": 2, "금융감독원 제재": 2, "금감원 제재": 2, "금감원 횡령" : 1
        },
        "🏢 자사 및 업계 동향": {
            "현대캐피탈": 3, "캐피탈사 사고": 2, "캐피탈사 사기": 2,  "리스/할부": 1
        },
        "⚠️ 내부통제 및 리스크": {
            "금융권 내부통제": 3, "금융사고": 2, "보안사고": 2
        }
    }

    titles_tracker = []
    final_html_body = ""

    for category_name, keywords_dict in audit_categories.items():
        category_all_news = []
        for kw, score in keywords_dict.items():
            category_all_news.extend(get_naver_news_data(kw, score, titles_tracker, NAVER_ID, NAVER_SECRET))
        
        if category_all_news:
            # 가중치 기준 정렬 후 상위 5개 추출
            category_all_news.sort(key=lambda x: x['score'], reverse=True)
            top_5_news = category_all_news[:5]
            
            combined_items = ""
            for news in top_5_news:
                # 별표(stars) 변수를 제거하여 텍스트만 깔끔하게 나오도록 수정
                combined_items += f"""
                <li style='margin-bottom: 12px;'>
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
        print("제외 키워드 및 가중치 적용 완료!")
