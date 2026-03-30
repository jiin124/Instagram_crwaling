# Instagram Deep Scraper 🕸️

Playwright를 기반으로 구축된 강력한 인스타그램 크롤러입니다. 특정 사용자가 팔로잉하는 계정 목록을 추출하고, 각 계정의 프로필, 게시물, 해시태그, 댓글 및 대댓글(답글)까지 깊이 있게 수집합니다. 

## ✨ 주요 기능 (Key Features)

* **Deep Comment & Reply Extraction**: 
  인스타그램의 난독화된 클래스명 대신, 글자 크기(`line-height: 18px / 16px`)와 `<ul>` 태그 계층 구조 등 변하지 않는 물리적 속성을 기반으로 메인 댓글과 대댓글을 완벽하게 분리하여 추출합니다.
* **True Accessibility Check**: 
  단순히 API 응답(`is_private: true`)에 의존하여 수집을 차단하지 않습니다. 실제 DOM 상의 자물쇠 아이콘 유무를 판단하여, **내가 팔로우 중인 비공개 계정**의 데이터도 온전히 수집합니다.
* **Anti-Bot Evasion**: 
  사람의 행동 패턴을 모사한 랜덤 딜레이(`sleep_random`)와 무한 스크롤 로직을 적용하여 인스타그램의 Rate Limit 및 봇 탐지를 우회합니다.
* **Clutter-Free Data**: 
  메뉴 바 텍스트("홈", "릴스"), 시간 표시("12시간"), "답글 달기" 등 불필요한 UI 텍스트를 필터링하여 순도 높은 텍스트 데이터만 JSON으로 반환합니다.

## 🚀 설치 및 환경 설정 (Installation)

1. 저장소를 클론하고 필요한 패키지를 설치합니다.
```bash
git clone [https://github.com/your-username/your-repo-name.git](https://github.com/your-username/your-repo-name.git)
cd your-repo-name
pip install playwright
playwright install chromium
```

2. 인스타그램 로그인을 위한 환경 변수를 설정합니다.

- Windows 
```
Bash
set INSTAGRAM_ID=your_username
set INSTAGRAM_PASSWORD=your_password
```

- macOS / Linux
```
Bash
export INSTAGRAM_ID="your_username"
export INSTAGRAM_PASSWORD="your_password"
```

## 💻 사용 방법 (Usage)
터미널에서 아래 명령어를 실행하여 크롤링을 시작합니다.

Bash
```
# 기본 실행 (팔로잉 계정별 최대 50개 게시물 수집)
python crawl_instagram.py --max-posts 50 --output result.json

# 디버깅 또는 특정 계정만 테스트하고 싶을 때
python crawl_instagram.py --max-posts 5 --username-only target_id --output test.json

# 백그라운드(Headless) 모드로 실행 시
python crawl_instagram.py --max-posts 50 --headless
```

## 📁 데이터 구조 (Data Schema)
출력되는 JSON 데이터는 다층적인 상호작용 분석에 최적화되어 있습니다.
```
{
  "crawled_at": "2026-03-25T14:00:00.000",
  "my_account": "your_account",
  "following_accounts": [
    {
      "account": {
        "username": "target_user",
        "followers": 1200,
        "following": 300,
        "is_private": false
      },
      "posts": [
        {
          "url": "[https://www.instagram.com/p/](https://www.instagram.com/p/)...",
          "post_date": "2026-03-17T04:21:34.000Z",
          "post_text": "본문 내용입니다.",
          "hashtags": ["일상", "기록"],
          "post_likes": 1036,
          "comments": [
            {
              "user": "commenter_id",
              "text": "메인 댓글 내용",
              "time": "2026-03-18T16:00:00.000Z",
              "likes": 10,
              "replies": [
                {
                  "user": "reply_user_id",
                  "text": "대댓글 내용",
                  "time": "2026-03-18T16:10:00.000Z",
                  "likes": 2
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

## ⚠️ 주의 사항 (Disclaimer)
- 인스타그램의 DOM 구조는 수시로 변경될 수 있습니다.
- 본 코드는 연구 및 데이터 분석 학습 목적으로 작성되었으며, 무분별한 크롤링으로 인한 계정 차단(Block)에 대해서는 책임지지 않습니다.
