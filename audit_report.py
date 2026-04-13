import os
import requests
import smtplib
import sys
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.utils import formataddr, formatdate
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

def is_similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

# [신규 추가] 금융감독원 보도자료 크롤링 함수
def get_fss_announcements():
    url = "https://www.fss.or.kr/fss/bbs/B0000188/list.do?menuNo=200218"
    base_url = "https://www.fss.or.kr"
    
    # 한국 시간 기준 어제 날짜 구하기 (YYYY-MM-DD)
    kst = timezone(timedelta(hours=9))
    yesterday = (datetime.now(kst) - timedelta(days=1)).strftime('%Y-%m-%d')
    
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 게시판 테이블의 행(tr)들을 가져옴
        rows = soup.select('table tbody tr')
        
        fss_html = ""
        found_count = 0
        
        for row in rows:
            # 날짜 확인 (보통 5번째 td에 위치)
            date_text = row.select_one('td.date').text.strip() if row.select_one('td.date') else ""
            
            # 전일자 데이터만 추출
            if date_text == yesterday:
                title_elem = row.select_one('td.title a')
                dept_text = row.select_one('td.dept').text.strip() if row.select_one('td.dept') else "담당부서 확인불가"
                
                title = title_elem.text.strip()
                link = base_url + title_elem['href']
                
                fss_html += f"""
                <li style='margin-bottom: 12px;'>
                    <a href='{link}' style='text-decoration: none; color: #d35400; font-weight: bold; font-size: 11pt;'>• {title}</a><br>
                    <span style='font-size: 9pt; color: #7f8c8d;'>[담당: {dept_text} | 등록일: {date_text}]</span>
                </li>"""
                found_count += 1
        
        if found_count > 0:
            return f"""
            <div style='margin-bottom: 25px; padding: 15px; background-color: #fff5e6; border-radius: 8px; border: 1px solid #ffe0b2;'>
                <h3 style='margin-top: 0; color: #e67e22; font-size: 13pt;'> 🏛️ 금융감독원 보도자료 (전일자) </h3>
                <ul style='list-style-type: none; padding-left: 0; margin-bottom: 0;'>
                    {fss_html}
                </ul>
            </div>"""
        else:
            return "" # 전일자 자료 없으면 섹션 자체를 표시 안함
            
    except Exception as e:
        print(f"금감원 크롤링 에러: {e}")
        return ""

# 네이버 뉴스 검색 API 함수 (기존 유지)
def get_naver_news_html(keyword, seen_titles, client_id, client_secret):
    url = f"https://openapi.naver.com/v1/search/news.json?query={keyword}&display=10&sort=date"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret
    }

    try:
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        data = res.json()

        html_segment = f"""
        <div style='margin-bottom: 25px; padding: 15px; background-color: #fdfdfd; border-radius: 8px;'>
            <h3 style='margin-top: 0; color: #2c3e50; font-size: 13pt;'> ◾ {keyword} </h3>
            <ul style='list-style-type: none; padding-left: 0; margin-bottom: 0;'>
        """      
        
        exclude_terms = ['배구', '스포츠', 'V리그', '연예', '방송', '드라마', '영화', '가수', '아이돌', '슬리피']
        count = 0
        kst = timezone(timedelta(hours=9))
        one_day_ago = datetime.now(kst) - timedelta(days=1)

        for item in data['items']:
            title = item['title'].replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&amp;", "&")
            desc = item['description'].replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&amp;", "&")
            link = item['link']
            pub_date = datetime.strptime(item['pubDate'], '%a, %d %b %Y %H:%M:%S +0900').replace(tzinfo=kst)

            if pub_date < one_day_ago: continue
            if any(term in (title + " " + desc) for term in exclude_terms): continue
            
            is_duplicate = False
            for seen_title in seen_titles:
                if is_similar(title[:20], seen_title[:20]) > 0.6:
                    is_duplicate = True
                    break
            if is_duplicate: continue
                
            seen_titles.append(title)
            html_segment += f"<li style='margin-bottom: 10px; text-align: left;'><a href='{link}' style='text-decoration: none; color: #1a0dab; font-size: 11pt;'>• {title}</a></li>"
            
            count += 1
            if count >= 3: break
            
        html_segment += "</ul></div>"
        return html_segment if count > 0 else ""
    except Exception as e:
        print(f"[{keyword}] 에러 발생: {e}")
        return ""

def send_audit_report(html_content, fss_content, image_path):
    send_email_addr = "hcsaudit.news@gmail.com"
    app_pw = os.getenv('EMAIL_PW')
    display_name = "현대캐피탈 감사실"
    target_emails = os.getenv('TARGET_EMAILS')
    additional_text = "※ 인터넷 공간, 외부메일조회 시스템에서 뉴스별 링크 접근이 가능합니다."

    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    date_str = now_kst.strftime('%Y-%m-%d')
    time_str = now_kst.strftime('%H:%M')

    msg = MIMEMultipart('related')
    msg['Subject'] = f"[{date_str}] Audit Daily News ☀️"
    msg['From'] = formataddr((display_name, send_email_addr))
    msg['To'] = target_emails
    msg['Date'] = formatdate(localtime=True)

    # 금감원 섹션이 있을 경우 뉴스 섹션 위에 배치
    full_html = f"""
    <html>
      <body style="font-family: 'Malgun Gothic', sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0;">
        <div style="max-width: 650px; margin: 0 auto; border: 1px solid #eee; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.05);">
          <div style="text-align: center; background-color: #000;">
            <img src="cid:header_logo" style="width: 100%; display: block; max-width: 650px;">
          </div>
          <div style="padding: 25px;">
            <table width="100%" border="0" cellpadding="0" cellspacing="0" style="margin-bottom: 20px;">
              <tr>
                <td align="right" style="text-align: right;">
                  <p style="font-size: 9pt; color: #888; margin: 0; text-align: right;">발송 시각: {date_str} {time_str} (KST)</p>
                  <p style="font-size: 11pt; color: #000; font-weight: bold; margin: 5px 0 0 0; text-align: right;">{additional_text}</p>
                </td>
              </tr>
            </table>

            <div style="text-align: left;">
                <h2 style="color: #2c3e50; margin-bottom: 25px; border-bottom: 1px solid #eee; padding-bottom: 10px;">📋 주요 브리핑 </h2>
                {fss_content}
                {html_content}
            </div>

            <div style="background-color: #f4f7f9; padding: 20px; font-size: 9pt; color: #7f8c8d; text-align: center; border-radius: 8px; margin-top: 30px;">
                <strong style="color: #e74c3c;">⭐</strong> 본 리포트는 현대캐피탈 감사 업무 지원을 위해 자동 생성되었습니다.
            </div>
          </div>
        </div>
      </body>
    </html>
    """
    msg.attach(MIMEText(full_html, 'html'))

    if os.path.exists(image_path):
        with open(image_path, 'rb') as f:
            img_data = f.read()
            msg_img = MIMEImage(img_data)
            msg_img.add_header('Content-ID', '<header_logo>')
            msg_img.add_header('Content-Disposition', 'inline', filename=os.path.basename(image_path))
            msg.attach(msg_img)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(send_email_addr, app_pw)
        server.send_message(msg)

if __name__ == "__main__":
    NAVER_ID = os.getenv('NAVER_ID')
    NAVER_SECRET = os.getenv('NAVER_SECRET')

    base_path = os.path.dirname(os.path.abspath(__file__))
    image_file = os.path.join(base_path, "hcs.png") 

    # 1. 금감원 보도자료 가져오기
    fss_body = get_fss_announcements()

    # 2. 뉴스 수집
    audit_keywords = ["현대캐피탈", "내부통제", "횡령", "캐피탈 대출사고", "리스/할부", "여신금융 금감원 검사", "금융권 내부통제 사고"]
    titles_tracker = []
    final_html_body = ""
    for kw in audit_keywords:
        final_html_body += get_naver_news_html(kw, titles_tracker, NAVER_ID, NAVER_SECRET)

    # 3. 메일 발송 (금감원 자료나 뉴스가 있을 때만)
    if final_html_body or fss_body:
        send_audit_report(final_html_body, fss_body, image_file)
        print("데일리 리포트 발송 완료!")
