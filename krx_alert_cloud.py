# -*- coding: utf-8 -*-
"""
코스피·코스닥 시총대비 순매수율 TOP10 → 텔레그램 전송 (클라우드용)
- 거래일(오늘이 실제 장이 열린 날)에만 전송합니다.
- 모든 비밀정보(KRX 로그인, 텔레그램)는 환경변수(비밀 금고)에서 읽습니다.
  필요한 환경변수: KRX_ID, KRX_PW, TELEGRAM_TOKEN, CHAT_ID
  (FORCE=1 이면 거래일이 아니어도 강제로 전송 — 테스트용)
"""
import os
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo   # 한국 시간 계산 (클라우드 서버는 UTC를 쓰므로 필수)

최소_시가총액_억 = 400
상위_개수 = 10
최소_시가총액 = 최소_시가총액_억 * 100_000_000

KRX_ID = os.environ["KRX_ID"]
KRX_PW = os.environ["KRX_PW"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
FORCE = os.environ.get("FORCE") == "1"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
LOGIN_PAGE = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
LOGIN_JSP  = "https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc"
LOGIN_URL  = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
DATA_URL   = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
DATA_HDR = {"Referer": "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd",
            "X-Requested-With": "XMLHttpRequest"}

시장목록 = [("STK", "코스피"), ("KSQ", "코스닥")]
투자자목록 = [("3100", "사모펀드"), ("9000", "외국인")]


def 숫자로(값):
    try:
        return float(str(값).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def 로그인(s):
    s.headers.update({"User-Agent": UA})
    s.get(LOGIN_PAGE, timeout=20)
    s.get(LOGIN_JSP, headers={"Referer": LOGIN_PAGE}, timeout=20)
    payload = {"mbrNm": "", "telNo": "", "di": "", "certType": "",
               "mbrId": KRX_ID, "pw": KRX_PW}
    j = s.post(LOGIN_URL, data=payload, headers={"Referer": LOGIN_PAGE}, timeout=20).json()
    if j.get("_error_code") == "CD011":
        payload["skipDup"] = "Y"
        j = s.post(LOGIN_URL, data=payload, headers={"Referer": LOGIN_PAGE}, timeout=20).json()
    if j.get("_error_code") != "CD001":
        raise SystemExit(f"❌ KRX 로그인 실패: {j.get('_error_message')}")


def 시가총액_가져오기(s, 날짜, mktId):
    d = {"bld": "dbms/MDC/STAT/standard/MDCSTAT01501", "mktId": mktId,
         "trdDd": 날짜, "share": "1", "money": "1", "csvxls_isNo": "false"}
    rows = s.post(DATA_URL, data=d, headers=DATA_HDR, timeout=20).json().get("OutBlock_1", [])
    결과 = {}
    for r in rows:
        시총 = 숫자로(r.get("MKTCAP"))
        if 시총 and 시총 > 0:
            결과[r.get("ISU_SRT_CD")] = 시총
    return 결과


def 순매수_가져오기(s, 날짜, mktId, invstTpCd):
    d = {"bld": "dbms/MDC/STAT/standard/MDCSTAT02401", "strtDd": 날짜, "endDd": 날짜,
         "mktId": mktId, "invstTpCd": invstTpCd, "csvxls_isNo": "false"}
    rows = s.post(DATA_URL, data=d, headers=DATA_HDR, timeout=20).json().get("output", [])
    결과 = []
    for r in rows:
        순매수 = 숫자로(r.get("NETBID_TRDVAL"))
        if 순매수 is not None:
            결과.append((r.get("ISU_SRT_CD"), r.get("ISU_NM"), 순매수))
    return 결과


def 최근_거래일_찾기(s, 시작):
    for i in range(0, 15):
        날짜 = (시작 - timedelta(days=i)).strftime("%Y%m%d")
        if 순매수_가져오기(s, 날짜, "STK", "3100"):
            return 날짜
    raise SystemExit("❌ 최근 15일 안에 거래일 데이터를 찾지 못했어요.")


def TOP_계산(시총맵, 순매수리스트):
    out = []
    for 코드, 이름, 순매수 in 순매수리스트:
        시총 = 시총맵.get(코드)
        if 시총 is None or 시총 < 최소_시가총액:
            continue
        out.append((이름, 순매수 / 시총 * 100))
    out.sort(key=lambda x: x[1], reverse=True)
    return out[:상위_개수]


def 날짜예쁘게(d):
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def 메시지만들기(결과, 기준일):
    줄 = [f"📊 시총대비 순매수율 TOP{상위_개수}",
          f"기준일 {날짜예쁘게(기준일)} · 최소시총 {최소_시가총액_억}억↑", ""]
    for mktId, 시장명 in 시장목록:
        for invId, 투자자명 in 투자자목록:
            줄.append(f"▣ {시장명} · {투자자명}")
            for 순위, (이름, 율) in enumerate(결과[(mktId, invId)], 1):
                줄.append(f"{순위:2d}. {이름} {율:.2f}%")
            줄.append("")
    return "\n".join(줄)


def 텔레그램_전송(메시지):
    r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                     params={"chat_id": CHAT_ID, "text": 메시지}, timeout=20)
    return r.json().get("ok", False)


# 마지막으로 전송한 거래일을 기록하는 파일 (같은 날 중복 전송을 막는 용도)
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_sent.txt")


def 마지막_전송일_읽기():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def 마지막_전송일_쓰기(날짜):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(날짜)


def main():
    지금_한국 = datetime.now(ZoneInfo("Asia/Seoul"))

    s = requests.Session()
    로그인(s)
    기준일 = 최근_거래일_찾기(s, 지금_한국.replace(tzinfo=None))

    # 아직 전송하지 않은 '새로운 거래일' 데이터가 있을 때만 전송한다.
    # (실행이 자정을 넘겨 늦어져도, 주말·공휴일이어도 올바르게 동작)
    마지막_전송일 = 마지막_전송일_읽기()
    if 기준일 == 마지막_전송일 and not FORCE:
        print(f"⏭️ 최근 거래일({날짜예쁘게(기준일)}) 데이터는 이미 전송함 → 건너뜀")
        return

    시총맵 = {mktId: 시가총액_가져오기(s, 기준일, mktId) for mktId, _ in 시장목록}
    결과 = {}
    for mktId, _ in 시장목록:
        for invId, _ in 투자자목록:
            결과[(mktId, invId)] = TOP_계산(시총맵[mktId], 순매수_가져오기(s, 기준일, mktId, invId))

    성공 = 텔레그램_전송(메시지만들기(결과, 기준일))
    print("📤 텔레그램 전송:", "성공" if 성공 else "실패", f"(기준일 {기준일})")

    # 실제 전송에 성공했을 때만 '마지막 전송일'을 갱신 (테스트 강제전송은 갱신 안 함)
    if 성공 and not FORCE:
        마지막_전송일_쓰기(기준일)


if __name__ == "__main__":
    main()
