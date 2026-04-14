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

# [수정] 키워드 제목(H3)을 제거하고 리스트(li)만 반환하도록 변경
def get_naver_news_list_items(keyword, seen_titles, client_id, client_secret):
    url = f"https://openapi.naver.com/v1/search/news.json?query={keyword}&display=10&sort=date"
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    
    list_items_html = ""
    try:
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        data = res.json()
        
        kst = timezone(timedelta(hours=9))
        one_day_ago = datetime.now(kst) - timedelta(days=1)
        
        count = 0
        for item in data.get('items', []):
            title = item['title'].replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&amp;", "&")
            pub_date = datetime.strptime(item['pubDate'], '%a, %d %b %Y %H:%M:%S +0900').replace(tzinfo=kst)
            
            if pub_date < one_day_ago: continue
            
            # 중복 체크
            if any(is_similar(title[:20], s[:20]) > 0.6 for s in seen_titles): continue
            
            seen_titles.append(title)
            list_items_html += f"""
            <li style='margin-bottom: 12px; text-align: left;'>
                <a href='{item['link']}' style='text-decoration: none; color: #1a0dab; font-size: 11pt;'>• {title}</a>
            </li>"""
            count += 1
            if count >= 3: break # 키워드당 최대 3개
            
        return list_items_html
    except:
        return ""

def send_audit_report(html_content, image_path):
    send_email_addr = "hcsaudit.news@gmail.com"
    app_pw = os.getenv('EMAIL_PW')
    target_emails = os.getenv('TARGET_EMAILS')
    
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    date_str = now_kst.strftime('%Y-%m-%d')
    time_str = now_kst.strftime('%H:%M')
    
    msg = MIMEMultipart('related')
    msg['Subject'] = f"[{date_str}] Audit Daily News ☀️"
    msg['From'] = formataddr(("현대캐피탈 감사실", send_email_addr))
    msg['To'] = target_emails

    full_html = f"""
    <html>
      <body style="font-family: 'Malgun Gothic', sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0;">
        <div style="max-width: 650px; margin: 0 auto; border: 1px solid #eee; border-radius: 12px; overflow: hidden;">
          <div style="text-align: center; background-color: #000; padding: 10px;">
            <img src="cid:header_logo" style="max-width: 100%; display: block; margin: 0 auto;">
          </div>
          <div style="padding: 25px;">
            <table width="100%" border="0" cellpadding="0" cellspacing="0" style="margin-bottom: 20px;">
              <tr>
                <td align="right" style="text-align: right;">
                  <p style="font-size: 9pt; color: #888; margin: 0; text-align: right;">발송 시각: {date_str} {time_str}</p>
                </td>
              </tr>
            </table>
            {html_content}
          </div>
        </div>
      </body>
    </html>
    """
    msg.attach(MIMEText(full_html, 'html'))
    
    if os.path.exists(image_path):
        with open(image_path, 'rb') as f:
            msg_img = MIMEImage(f.read())
            msg_img.add_header('Content-ID', '<header_logo>')
            msg.attach(msg_img)
            
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(send_email_addr, app_pw)
        server.send_message(msg)

if __name__ == "__main__":
    NAVER_ID = os.getenv('NAVER_ID')
    NAVER_SECRET = os.getenv('NAVER_SECRET')
    base_path = os.path.dirname(os.path.abspath(__file__))
    image_file = os.path.join(base_path, "hcs.png")

    audit_categories = {
        "🏛️ 금감원 및 감독기구": ["금감원 제재", "금융감독원 검사", "여신금융 금감원 검사"],
        "🏢 자사 및 업계 동향": ["현대캐피탈", "캐피탈업계", "리스/할부"],
        "⚠️ 내부통제 및 리스크": ["내부통제", "횡령", "금융권 내부통제 사고"]
    }

    titles_tracker = []
    final_html_body = ""

    for category_name, keywords in audit_categories.items():
        combined_items = ""
        for kw in keywords:
            # 키워드별로 뉴스 리스트(li 태그들)만 가져와서 합침
            combined_items += get_naver_news_list_items(kw, titles_tracker, NAVER_ID, NAVER_SECRET)
        
        if combined_items:
            # 카테고리 제목 하나 아래에 모든 뉴스 리스트를 배치
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
        print("카테고리 통합형 리포트 발송 완료!")
