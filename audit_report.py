import os
import requests
import smtplib
import holidays
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.utils import formataddr
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher


def get_fetch_days():
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).date()
    
    kr_holidays = holidays.KR()
    labor_day = datetime(today.year, 5, 1).date()
    
    def check_is_holiday(dt):
        return dt.weekday() >= 5 or dt in kr_holidays or dt == labor_day

    if check_is_holiday(today):
        return None

    fetch_days = 1
    check_date = today - timedelta(days=1)
    while check_is_holiday(check_date):
        fetch_days += 1
        check_date -= timedelta(days=1)
            
    return fetch_days


def is_similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


def get_naver_news_data(keyword, seen_texts, client_id, client_secret, days_to_fetch):
    url = f"https://openapi.naver.com/v1/search/news.json?query={keyword}&display=20&sort=date"
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}

    exclude_terms = [
        '배구', '스포츠', 'V리그', '배구단', '감독', '블랑', '챔프전', '우승', '경기', '득점', '승리', '리그', 'MVP', '한선수', '선수', '허수봉', '남자부',
        '시상식', '한국배구연맹', '연예', '방송', '드라마', '영화', '출연', '배우', '가수', '아이돌', '하정우', '공연', '티켓', '예매', '슬리피',
        '데뷔', '컴백', '시청률', '예능', '넷플릭스', '유튜브', '구독자', '영상', '채널', '게임', '콘서트', '팬미팅', '음원', '차트', '화보', '결혼', '이혼', '열애', '뮤지컬',
        '부고', '별세'
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
            except Exception:
                continue
            if pub_date < search_limit:
                continue
            
            full_text = title + " " + desc
            if any(term in full_text for term in exclude_terms):
                continue
            
            current_content = title[:200]
            if any(is_similar(current_content, s) > 0.3 for s in seen_texts):
                continue
            
            seen_texts.append(current_content)
            news_items.append({
                "title": title,
                "desc": desc,
                "link": item['link'],
                "score": 0
            })
            
        return news_items
    except Exception as e:
        print(f"네이버 API 호출 오류 ({keyword}): {e}")
        return []


def save_news_json(news_by_category, date_str):
    # 월별 폴더 생성 (예: docs/data/2026-06/)
    year_month = date_str[:7]  # "2026-06-23" -> "2026-06"
    month_dir = f'docs/data/{year_month}'
    os.makedirs(month_dir, exist_ok=True)

    # 월별 폴더에 JSON 저장
    file_path = f'{month_dir}/{date_str}.json'
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(news_by_category, f, ensure_ascii=False, indent=2)

    # index.json 업데이트
    index_path = 'docs/data/index.json'
    if os.path.exists(index_path):
        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                index = json.loads(content) if content else []
        except (json.JSONDecodeError, ValueError):
            print(f"⚠️  index.json 파싱 오류, 빈 배열로 초기화합니다.")
            index = []
    else:
        index = []

    if date_str not in index:
        index.append(date_str)
        index.sort(reverse=True)

    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False)

    print(f"✅ JSON 저장 완료: {file_path}")


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
    msg['To'] = formataddr(("현대캐피탈 감사실", send_email_addr))

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
            server.sendmail(send_email_addr, recipient_list, msg.as_string())
            print(f"✅ 리포트 발송 성공!")
    except Exception as e:
        print(f"❌ 발송 실패: {e}")


if __name__ == "__main__":
    days_to_fetch = get_fetch_days()
    
    kst = timezone(timedelta(hours=9))
    date_str = datetime.now(kst).strftime('%Y-%m-%d')

    if days_to_fetch is None:
        print("🚩 오늘은 한국 공휴일 또는 주말입니다. 배치를 종료합니다.")
        exit()

    print(f"🔍 최근 {days_to_fetch}일치 데이터를 수집합니다.")
    
    NAVER_ID = os.getenv('NAVER_ID')
    NAVER_SECRET = os.getenv('NAVER_SECRET')
    
    base_path = os.path.dirname(os.path.abspath(__file__))
    image_file = os.path.join(base_path, "hcs.png")

    audit_categories = {
        "🏛️ 금감원 및 감독기구": {
            "금융감독원": 5, "금감원": 5, "금융감독원 검사": 5, "금감원 검사": 5, "금융위원회": 5,
            "금융감독원 제재": 4, "금감원 제재": 4,
            "금융위": 3, "금감원 규제": 3, "금융당국": 3,
            "개인정보위": 2, "개보위": 2, "규제완화": 2, "규제강화": 2, "건전성": 2, "금융위원장": 2, "금감원장": 2, "금감원 긴급": 2,
            "금감원 횡령": 1
        },
        "🏢 자사 및 업계 동향": {
            "현대캐피탈": 5,
            "캐피탈사 사고": 4,
            "캐피탈사 사기": 3, "캐피탈업계": 3, "여신전문금융": 3, "여전업계": 3, "여전업권": 3, "여신금융": 3,
            "금융권": 2,
            "리스/할부": 1
        },
        "⚠️ 내부통제 및 리스크": {
            "금융권 내부통제": 5,
            "금융사고": 3, "보안사고": 3, "유출사고": 3,
            "과징금": 2, "과태료": 2, "의무위반": 2,
            "개인정보보호": 1, "신용정보보호": 1
        }
    }

    global_seen_texts = []
    final_html_body = ""
    news_by_category = {}

    all_keywords = set()
    for kd in audit_categories.values():
        all_keywords.update(kd.keys())

    conditional_keywords = {"과징금", "과태료", "규제완화", "규제강화", "의무위반", "보안사고"}

    for category_name, keywords_dict in audit_categories.items():
        category_all_news = []
        for kw, score in keywords_dict.items():
            category_all_news.extend(get_naver_news_data(kw, global_seen_texts, NAVER_ID, NAVER_SECRET, days_to_fetch))

        for news in category_all_news:
            total_score = 0
            matched_keywords = []
            check_text = (news['title'] + " " + news.get('desc', ''))[:200]
            seen_kw_scores = {}
            found_keywords = {kw for kw in all_keywords if kw in check_text}

            for kw, kw_score in keywords_dict.items():
                if kw not in check_text or kw in seen_kw_scores:
                    continue
                if kw in conditional_keywords:
                    if not (found_keywords - conditional_keywords):
                        continue
                seen_kw_scores[kw] = kw_score
                total_score += kw_score
                matched_keywords.append(f"{kw}({kw_score})")

            news['score'] = total_score
            news['matched_keywords'] = matched_keywords

        if category_all_news:
            category_all_news.sort(key=lambda x: x['score'], reverse=True)
            top_news = [news for news in category_all_news if news['score'] > 0][:20]

            if top_news:
                news_by_category[category_name] = top_news

                combined_items = ""
                for news in top_news:
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

    if final_html_body:
        send_audit_report(final_html_body, image_file)
        save_news_json(news_by_category, date_str)
    else:
        print("수집된 뉴스가 없습니다.")
    
