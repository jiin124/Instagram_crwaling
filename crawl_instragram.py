"""
Instagram Full Crawler (Profile + Posts + Comments + Replies)
====================================
팔로잉 계정의 프로필, 게시물, 댓글, 대댓글 정보를 모두 수집합니다.

사용법:
    python crawl_instagram.py --max-posts 3 --output data.json

환경변수:
    INSTAGRAM_ID       - Instagram 아이디
    INSTAGRAM_PASSWORD - Instagram 비밀번호
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)

# ─────────────────────────────────────────────────────────────
# 로깅 설정
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

INSTAGRAM_BASE_URL = "https://www.instagram.com"
USER_DATA_DIR = Path(".instagram_session")

DELAY_MIN = 2.0
DELAY_MAX = 5.0
SCROLL_DELAY_MIN = 2.0
SCROLL_DELAY_MAX = 4.0

def sleep_random(min_s: float = DELAY_MIN, max_s: float = DELAY_MAX) -> None:
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

# ─────────────────────────────────────────────────────────────
# 브라우저 컨텍스트 & 로그인
# ─────────────────────────────────────────────────────────────
def create_browser_context(playwright: Playwright, headless: bool = True) -> tuple[Browser, BrowserContext]:
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    browser = playwright.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(USER_DATA_DIR),
        headless=headless,
        viewport={"width": 1280, "height": 900},
        locale="ko-KR",
        timezone_id="Asia/Seoul",
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    return browser, context

def login(page: Page, username: str, password: str) -> bool:
    log.info("Instagram 홈페이지 접속 중…")
    page.goto(INSTAGRAM_BASE_URL, wait_until="domcontentloaded")
    sleep_random(2, 4)

    if page.url.startswith(INSTAGRAM_BASE_URL) and "accounts/login" not in page.url:
        if page.locator(f'a[href="/{username}/"]').count() > 0 or page.locator('svg[aria-label="Home"], svg[aria-label="홈"]').count() > 0:
            log.info("이미 로그인된 세션이 있습니다. 재로그인 건너뜀.")
            return True

    page.goto(f"{INSTAGRAM_BASE_URL}/accounts/login/", wait_until="domcontentloaded")
    sleep_random(1, 3)

    try:
        page.fill('input[name="username"]', username)
        sleep_random(0.5, 1.5)
        page.fill('input[name="password"]', password)
        sleep_random(0.5, 1.5)
        page.click('button[type="submit"]')
        page.wait_for_url(lambda url: "accounts/login" not in url and "challenge" not in url, timeout=15_000)
        sleep_random(2, 4)
        log.info("로그인 성공.")
        return True
    except Exception as exc:
        log.error("로그인 실패: %s", exc)
        return False

# ─────────────────────────────────────────────────────────────
# 팔로잉 목록
# ─────────────────────────────────────────────────────────────
def get_following_list(page: Page, username: str) -> list[str]:
    log.info("팔로잉 목록 수집 시작…")
    page.goto(f"{INSTAGRAM_BASE_URL}/{username}/", wait_until="domcontentloaded", timeout=30_000)
    sleep_random()

    following_link = page.locator(f'a[href="/{username}/following/"], a:has-text("following"), a:has-text("팔로잉")').first
    if following_link.count() == 0:
        log.error("팔로잉 링크를 찾을 수 없습니다.")
        return []

    following_link.click()
    sleep_random(2, 4)

    usernames: list[str] = []
    try:
        modal = page.locator('div[role="dialog"]')
        modal.wait_for(timeout=10_000)
        scroll_container = modal.locator("div").filter(has=page.locator('a[role="link"]')).last

        prev_count = -1
        no_change_streak = 0
        while no_change_streak < 5:
            for link in modal.locator('a[href^="/"][href$="/"]').all():
                uname = (link.get_attribute("href") or "").strip("/")
                if uname and uname not in usernames and "/" not in uname and not uname.startswith("explore"):
                    usernames.append(uname)

            log.info("팔로잉 수집 중: %d명", len(usernames))
            if len(usernames) == prev_count: no_change_streak += 1
            else: no_change_streak, prev_count = 0, len(usernames)

            scroll_container.evaluate("el => el.scrollTop += el.clientHeight")
            sleep_random(SCROLL_DELAY_MIN, SCROLL_DELAY_MAX)
    except Exception as exc:
        log.warning("팔로잉 목록 수집 중 오류: %s", exc)

    log.info("팔로잉 총 %d명 수집 완료.", len(usernames))
    return usernames

# ─────────────────────────────────────────────────────────────
# 프로필 정보 (기존 스크립트의 견고한 방식 유지)
# ─────────────────────────────────────────────────────────────
def scrape_profile(page: Page, username: str) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "username": username,
        "display_name": "",
        "bio": "",
        "followers": 0,
        "following": 0,
        "posts_count": 0,
        "profile_url": f"{INSTAGRAM_BASE_URL}/{username}/",
        "is_private": False,
        "is_accessible": True,
    }

    try:
        page.goto(f"{INSTAGRAM_BASE_URL}/{username}/", wait_until="domcontentloaded", timeout=30_000)
        sleep_random(2, 4)
    except Exception:
        profile["is_accessible"] = False
        return profile

    if "Page Not Found" in page.title() or page.locator('h2:has-text("Sorry")').count() > 0:
        profile["is_accessible"] = False
        return profile

    if page.locator('h2:has-text("This Account is Private"), span:has-text("이 계정은 비공개"), span:has-text("비공개 계정")').count() > 0:
        profile["is_private"] = True
        profile["is_accessible"] = False

    try:
        meta_desc = page.locator('meta[property="og:description"]').get_attribute("content")
        if meta_desc:
            match_en = re.search(r'([\d.,KMBkmb]+)\s*Followers?,\s*([\d.,KMBkmb]+)\s*Following,\s*([\d.,KMBkmb]+)\s*Posts?', meta_desc, re.IGNORECASE)
            match_ko = re.search(r'팔로워\s*([\d.,KMBkmb]+)명?,\s*팔로잉\s*([\d.,KMBkmb]+)명?,\s*게시물\s*([\d.,KMBkmb]+)개?', meta_desc)
            if match_en:
                profile["followers"], profile["following"], profile["posts_count"] = parse_count(match_en.group(1)), parse_count(match_en.group(2)), parse_count(match_en.group(3))
            elif match_ko:
                profile["followers"], profile["following"], profile["posts_count"] = parse_count(match_ko.group(1)), parse_count(match_ko.group(2)), parse_count(match_ko.group(3))
    except: pass

    log.info("@%s | 팔로워: %d | 게시물: %d | 비공개: %s", username, profile["followers"], profile["posts_count"], profile["is_private"])
    return profile

# ─────────────────────────────────────────────────────────────
# 게시물 및 댓글/대댓글 상세 수집 (성공한 로직 적용 ⭐️)
# ─────────────────────────────────────────────────────────────
def scrape_posts(page: Page, username: str, max_posts: int = 0) -> list[dict[str, Any]]:
    log.info("@%s 게시물 URL 수집 시작…", username)
    post_urls: list[str] = []
    unlimited = (max_posts == 0)

    # 1. 스크롤하여 URL 목록만 먼저 확보
    try:
        page.goto(f"{INSTAGRAM_BASE_URL}/{username}/", wait_until="domcontentloaded")
        sleep_random(2, 4)

        prev_count = 0
        no_change = 0
        while (unlimited or len(post_urls) < max_posts) and no_change < 4:
            for link in page.locator('a[href*="/p/"], a[href*="/reel/"]').all():
                href = link.get_attribute("href") or ""
                url = f"{INSTAGRAM_BASE_URL}{href.split('?')[0]}"
                if url not in post_urls: post_urls.append(url)

            if not unlimited and len(post_urls) >= max_posts: break
            if len(post_urls) == prev_count: no_change += 1
            else: no_change, prev_count = 0, len(post_urls)
            
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            sleep_random(SCROLL_DELAY_MIN, SCROLL_DELAY_MAX)
    except Exception as exc:
        log.error("@%s 게시물 목록 수집 오류: %s", username, exc)

    if not unlimited:
        post_urls = post_urls[:max_posts]
    posts = []

    # 2. 수집된 URL을 하나씩 돌면서 성공했던 상세 추출 로직 실행
    for idx, url in enumerate(post_urls, 1):
        log.info("  [%d/%d] 게시물 상세 수집: %s", idx, len(post_urls), url)
        post_data = _scrape_single_post(page, url)
        posts.append(post_data)
        sleep_random(2, 4)

    return posts

def _scrape_single_post(page: Page, post_url: str) -> dict[str, Any]:
    post_data = {
        "url": post_url,
        "author": "",
        "post_text": "",
        "hashtags": [],
        "post_likes": 0,
        "post_date": "",
        "comments": []
    }

    try:
        page.goto(post_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_selector('span[dir="auto"], span[style*="line-height"]', state="visible", timeout=15000)
        sleep_random(3, 5) 
    except:
        pass # 

    # 메타데이터 (날짜, 작성자, 게시물 좋아요)
    try:
        time_el = page.locator("time[datetime]").first
        if time_el.count() > 0: post_data["post_date"] = time_el.get_attribute("datetime") or ""
            
        author_el = page.locator('header a[role="link"], h2 a[role="link"]').first
        if author_el.count() > 0: post_data["author"] = author_el.inner_text().strip()

        meta_desc = page.locator('meta[property="og:description"]').get_attribute("content")
        if meta_desc:
            like_match = re.search(r'([\d.,KMBkmb]+)\s*(?:likes?|좋아요)', meta_desc, re.IGNORECASE)
            if like_match: post_data["post_likes"] = parse_count(like_match.group(1))
    except: pass

    # 댓글 더 보기 전개
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

    # 답글 보기 전개
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

    # 자바스크립트 추출 엔진 (18px 및 <ul> 태그 기반)
    js_extract_script = """
    () => {
        let result = { post_text: "", comments: [] };
        
        // 본문
        let mainTextSpans = document.querySelectorAll('span[style*="line-height: 18px"]');
        for (let span of mainTextSpans) {
            let styleAttr = span.getAttribute('style') || "";
            if (styleAttr.includes('--x-')) continue; 
            let text = span.innerText.trim();
            if (text.length > 5) { result.post_text = text; break; }
        }
        if (!result.post_text) {
            let h1 = document.querySelector('h1[dir="auto"]');
            if (h1) result.post_text = h1.innerText.trim();
        }

        // 댓글 및 답글
        let commentNodes = document.querySelectorAll('span[dir="auto"][style*="--x-lineHeight: 18px"]');
        let currentMainComment = null;

        commentNodes.forEach(node => {
            let text = node.innerText.trim();
            if (!text || text === result.post_text) return; 

            let parent = node.parentElement;
            let author = "";
            let timeStr = "";
            let likes = 0;

            for (let i = 0; i < 8; i++) {
                if (!parent) break;
                if (!author) {
                    let aTags = parent.querySelectorAll('a[role="link"], h2 a, h3 a');
                    for (let a of aTags) {
                        let aText = a.innerText.trim();
                        if (aText && !aText.startsWith('#') && !aText.startsWith('@') && !a.querySelector('img')) {
                            author = aText; break;
                        }
                    }
                }
                if (!timeStr) {
                    let timeEl = parent.querySelector('time[datetime]');
                    if (timeEl) timeStr = timeEl.getAttribute('datetime');
                }
                if (!likes) {
                    let textEls = parent.querySelectorAll('span, div');
                    for (let el of textEls) {
                        let t = el.innerText || "";
                        if ((t.includes('좋아요') || t.includes('likes')) && !t.includes('답글')) {
                            let m = t.match(/([\\d.,KMBkmb]+)\\s*(?:개|likes?)/i);
                            if (m) { likes = parseInt(m[1].replace(/,/g, '')); break; }
                        }
                    }
                }
                parent = parent.parentElement;
            }

            if (text === author) return; 

            let item = {
                user: author || "알수없음",
                text: text,
                time: timeStr || "",
                likes: likes || 0
            };

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
            if post_data["post_text"]:
                post_data["hashtags"] = list(set(re.findall(r"#([a-zA-Z0-9가-힣_]+)", post_data["post_text"])))
            if post_data["author"] and post_data["post_text"].startswith(post_data["author"]):
                post_data["post_text"] = post_data["post_text"][len(post_data["author"]):].strip()
            post_data["comments"] = raw_data.get("comments", [])
    except Exception as e:
        log.error("JS 추출 에러: %s", e)

    return post_data

# ─────────────────────────────────────────────────────────────
# 메인 & 저장
# ─────────────────────────────────────────────────────────────
def save_results(data: dict[str, Any], output_path: str) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("결과 저장 완료: %s", path)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Instagram 팔로잉 계정 상세 크롤러")
    parser.add_argument("--max-posts", type=int, default=0, help="각 계정에서 수집할 최대 게시물 수 (0 = 무제한)")
    parser.add_argument("--output", type=str, default="data.json", help="결과 JSON 파일 경로")
    parser.add_argument("--headless", action="store_true", default=False, help="헤드리스 모드로 실행")
    parser.add_argument("--username-only", type=str, default=None, help="특정 팔로잉 username만 수집 (테스트용)")
    return parser.parse_args()

def main() -> None:
    args = parse_args()
    instagram_id = os.environ.get("INSTAGRAM_ID")
    instagram_password = os.environ.get("INSTAGRAM_PASSWORD")

    if not instagram_id or not instagram_password:
        log.error("환경변수 INSTAGRAM_ID와 INSTAGRAM_PASSWORD를 설정해야 합니다.")
        sys.exit(1)

    result: dict[str, Any] = {
        "crawled_at": datetime.now().isoformat(),
        "my_account": instagram_id,
        "following_accounts": [],
    }

    with sync_playwright() as playwright:
        _, context = create_browser_context(playwright, headless=args.headless)
        page = context.new_page()

        if not login(page, instagram_id, instagram_password):
            context.close()
            sys.exit(1)

        following = [args.username_only] if args.username_only else get_following_list(page, instagram_id)

        if not following:
            log.warning("팔로잉 목록이 비어 있습니다.")

        for idx, uname in enumerate(following, 1):
            log.info("─" * 50)
            log.info("[%d/%d] @%s 처리 중…", idx, len(following), uname)

            profile = scrape_profile(page, uname)
            account_data = {"account": profile, "posts": []}

            if profile["is_accessible"] and not profile["is_private"]:
                account_data["posts"] = scrape_posts(page, uname, max_posts=args.max_posts)
            else:
                log.info("@%s: 비공개 또는 접근 불가 — 게시물 건너뜀.", uname)

            result["following_accounts"].append(account_data)
            save_results(result, args.output)
            sleep_random()

        context.close()

    log.info("=" * 50)
    log.info("크롤링 완료. 총 계정: %d", len(result["following_accounts"]))

if __name__ == "__main__":
    main()
    
