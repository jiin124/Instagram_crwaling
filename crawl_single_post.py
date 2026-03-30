"""
Instagram Single Post Crawler (No Article Dependency & UL Reply Version)
====================================
단일 인스타그램 게시물의 상세 데이터(본문, 해시태그, 좋아요, 댓글 및 대댓글 상세)를 수집합니다.
"""

import argparse
import json
import logging
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright, Page, BrowserContext

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

USER_DATA_DIR = Path(".instagram_session")

def sleep_random(min_s: float = 1.5, max_s: float = 3.0) -> None:
    time.sleep(random.uniform(min_s, max_s))

def parse_count(text: str | None) -> int:
    if not text: return 0
    text = re.sub(r"[^\dKMBkmb]", "", text.strip().replace(",", "").replace(".", ""))
    if not text: return 0
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    for suffix, multiplier in multipliers.items():
        if text.upper().endswith(suffix):
            try: return int(float(text[:-1]) * multiplier)
            except ValueError: return 0
    try: return int(text)
    except ValueError: return 0

def login_if_needed(page: Page, username: str, password: str) -> None:
    page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
    sleep_random(2, 4)
    if page.locator('input[name="username"]').count() > 0:
        log.info("로그인을 시도합니다...")
        page.fill('input[name="username"]', username)
        sleep_random(0.5, 1.0)
        page.fill('input[name="password"]', password)
        page.click('button[type="submit"]')
        page.wait_for_url(lambda url: "accounts/login" not in url, timeout=15000)
        log.info("로그인 완료.")
        sleep_random(2, 4)

def scrape_single_post(page: Page, post_url: str) -> dict[str, Any]:
    log.info(f"게시물 접속 중: {post_url}")
    page.goto(post_url, wait_until="domcontentloaded", timeout=45000)
    
    post_data = {
        "url": post_url,
        "author": "",
        "post_text": "",
        "hashtags": [],
        "post_likes": 0,
        "post_date": "",
        "comments": []
    }

    # 1. article 태그를 버리고, 댓글 텍스트(span[dir="auto"])가 뜰 때까지만 기다리기
    try:
        page.wait_for_selector('span[dir="auto"], span[style*="line-height"]', state="visible", timeout=15000)
        log.info("화면 텍스트 요소 렌더링 완료.")
        sleep_random(3, 5) 
    except:
        log.warning("렌더링 대기 초과. (계속 진행합니다)")

    # 2. 작성자 / 날짜 / 전체 좋아요 추출
    try:
        time_el = page.locator("time[datetime]").first
        if time_el.count() > 0:
            post_data["post_date"] = time_el.get_attribute("datetime") or ""
            
        author_el = page.locator('header a[role="link"], h2 a[role="link"]').first
        if author_el.count() > 0:
            post_data["author"] = author_el.inner_text().strip()

        meta_desc = page.locator('meta[property="og:description"]').get_attribute("content")
        if meta_desc:
            like_match = re.search(r'([\d.,KMBkmb]+)\s*(?:likes?|좋아요)', meta_desc, re.IGNORECASE)
            if like_match: post_data["post_likes"] = parse_count(like_match.group(1))
    except: pass

    # 3. 숨겨진 댓글 모두 펼치기
    log.info("숨겨진 댓글을 탐색합니다...")
    for _ in range(15):
        try:
            btns = page.locator('svg[aria-label="Load more comments"], svg[aria-label="댓글 더 보기"]').all()
            if not btns: break
            clicked = False
            for btn in btns:
                if btn.is_visible():
                    btn.click()
                    sleep_random(1.5, 2.5)
                    clicked = True
            if not clicked: break
        except: break

    # 4. '답글 보기' 모두 클릭 (대댓글 렌더링)
    log.info("대댓글(답글)을 모두 펼칩니다...")
    for _ in range(10):
        try:
            replies_btns = page.locator('span:has-text("답글"), span:has-text("replies")').all()
            clicked = False
            for btn in replies_btns:
                text = btn.inner_text().strip()
                if ("보기" in text or "replies" in text.lower()) and btn.is_visible():
                    btn.click()
                    sleep_random(1.0, 2.0)
                    clicked = True
            if not clicked: break
        except: break

    # 5. 자바스크립트 엔진 (<ul> 태그 유무로 대댓글 구분)
    log.info("화면 데이터를 추출합니다...")
    js_extract_script = """
    () => {
        let result = { post_text: "", comments: [] };
        
        // --- 본문 추출 ---
        // 본문은 보통 style="line-height: 18px;" 만 있고 --x- 는 없습니다.
        let mainTextSpans = document.querySelectorAll('span[style*="line-height: 18px"]');
        for (let span of mainTextSpans) {
            let styleAttr = span.getAttribute('style') || "";
            if (styleAttr.includes('--x-')) continue; // 댓글 텍스트 제외
            
            let text = span.innerText.trim();
            if (text.length > 5) {
                result.post_text = text;
                break;
            }
        }
        
        // 본문을 못 찾았다면 h1에서 보험으로 찾기
        if (!result.post_text) {
            let h1 = document.querySelector('h1[dir="auto"]');
            if (h1) result.post_text = h1.innerText.trim();
        }

        // --- 댓글 및 대댓글 추출 ---
        // 인스타그램 댓글은 모두 --x-lineHeight: 18px 속성을 가집니다.
        let commentNodes = document.querySelectorAll('span[dir="auto"][style*="--x-lineHeight: 18px"]');
        let currentMainComment = null;

        commentNodes.forEach(node => {
            let text = node.innerText.trim();
            // 빈 텍스트이거나, 방금 찾은 본문과 완벽히 동일하면 패스
            if (!text || text === result.post_text) return; 

            let parent = node.parentElement;
            let author = "";
            let timeStr = "";
            let likes = 0;

            // DOM 트리를 위로 타고 올라가며 정보 수집 (최대 8단계)
            for (let i = 0; i < 8; i++) {
                if (!parent) break;
                
                // 1. 작성자 찾기
                if (!author) {
                    let aTags = parent.querySelectorAll('a[role="link"], h2 a, h3 a');
                    for (let a of aTags) {
                        let aText = a.innerText.trim();
                        // 해시태그/멘션 제외, 이미지 없는 순수 텍스트
                        if (aText && !aText.startsWith('#') && !aText.startsWith('@') && !a.querySelector('img')) {
                            author = aText;
                            break;
                        }
                    }
                }
                
                // 2. 시간 찾기
                if (!timeStr) {
                    let timeEl = parent.querySelector('time[datetime]');
                    if (timeEl) timeStr = timeEl.getAttribute('datetime');
                }

                // 3. 좋아요 찾기
                if (!likes) {
                    let textEls = parent.querySelectorAll('span, div');
                    for (let el of textEls) {
                        let t = el.innerText || "";
                        if ((t.includes('좋아요') || t.includes('likes')) && !t.includes('답글')) {
                            let m = t.match(/([\\d.,KMBkmb]+)\\s*(?:개|likes?)/i);
                            if (m) {
                                likes = parseInt(m[1].replace(/,/g, ''));
                                break;
                            }
                        }
                    }
                }
                parent = parent.parentElement;
            }

            // 텍스트 내용 자체가 작성자 아이디면 패스 (UI 중복 요소)
            if (text === author) return; 

            let item = {
                user: author || "알수없음",
                text: text,
                time: timeStr || "",
                likes: likes || 0
            };

            // 현재 요소가 ul 태그 안에 들어있으면 대댓글
            let isReply = node.closest('ul') !== null;

            if (isReply) {
                if (currentMainComment) {
                    currentMainComment.replies.push(item);
                } else {
                    result.comments.push({ ...item, replies: [], is_orphaned: true });
                }
            } else {
                item.replies = [];
                currentMainComment = item;
                result.comments.push(currentMainComment);
            }
        });

        return result;
    }
    """
    
    try:
        raw_data = page.evaluate(js_extract_script)
        if raw_data:
            post_data["post_text"] = raw_data.get("post_text", "")
            
            # 해시태그 추출
            if post_data["post_text"]:
                post_data["hashtags"] = list(set(re.findall(r"#([a-zA-Z0-9가-힣_]+)", post_data["post_text"])))
                
            # 아이디가 본문 맨 앞에 묻어있으면 제거
            if post_data["author"] and post_data["post_text"].startswith(post_data["author"]):
                post_data["post_text"] = post_data["post_text"][len(post_data["author"]):].strip()
                
            post_data["comments"] = raw_data.get("comments", [])
    except Exception as e:
        log.error(f"JS 데이터 추출 에러: {e}")

    # 에러 원인 분석을 위해 최종 스크린샷 무조건 저장
    page.screenshot(path="debug_final.png")
    return post_data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", type=str, required=True, help="크롤링할 게시물 URL")
    parser.add_argument("--output", type=str, default="single_post1.json")
    args = parser.parse_args()

    insta_id = os.environ.get("INSTAGRAM_ID")
    insta_pw = os.environ.get("INSTAGRAM_PASSWORD")

    with sync_playwright() as p:
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        browser = p.chromium.launch(headless=False)
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            locale="ko-KR"
        )
        page = context.new_page()

        if insta_id and insta_pw:
            login_if_needed(page, insta_id, insta_pw)

        data = scrape_single_post(page, args.url)

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        log.info(f"수집 완료. {args.output} 파일에 저장되었습니다.")
        log.info(f"--- 수집 요약 ---")
        log.info(f"작성자: {data['author']}")
        log.info(f"본문: {data['post_text'][:30]}...")
        log.info(f"해시태그: {data['hashtags']}")
        log.info(f"총 댓글 수 (메인 댓글 기준): {len(data['comments'])}")

        context.close()

if __name__ == "__main__":
    main()
