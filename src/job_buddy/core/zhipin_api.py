from __future__ import annotations

from typing import Any

BASE_URL = "https://www.zhipin.com"
WEB_GEEK_JOB_URL = f"{BASE_URL}/web/geek/job"
WEB_GEEK_CHAT_URL = f"{BASE_URL}/web/geek/chat"
SEARCH_URL = f"{BASE_URL}/wapi/zpgeek/search/joblist.json"
DETAIL_URL = f"{BASE_URL}/wapi/zpgeek/job/detail.json"
GREET_URL = f"{BASE_URL}/wapi/zpgeek/friend/add.json"
FRIEND_LIST_URL = f"{BASE_URL}/wapi/zprelation/friend/getGeekFriendList.json"
CHAT_HISTORY_URL = f"{BASE_URL}/wapi/zpchat/geek/historyMsg"


def build_job_url(job_id: str | None, security_id: str | None = None) -> str | None:
    if not job_id:
        return None
    url = f"{BASE_URL}/job_detail/{job_id}.html"
    if security_id:
        return f"{url}?securityId={security_id}"
    return url


def build_job_detail_url(security_id: str | None) -> str | None:
    if not security_id:
        return None
    return f"{DETAIL_URL}?securityId={security_id}"

CITY_CODES = {
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280100",
    "深圳": "101280600",
    "杭州": "101210100",
    "成都": "101270100",
    "南京": "101190100",
    "武汉": "101200100",
    "西安": "101110100",
    "苏州": "101190400",
    "长沙": "101250100",
    "郑州": "101180100",
    "重庆": "101040100",
    "天津": "101030100",
    "合肥": "101220100",
    "厦门": "101230200",
    "济南": "101120100",
    "青岛": "101120200",
    "大连": "101070200",
    "宁波": "101210400",
    "福州": "101230100",
    "东莞": "101281600",
    "珠海": "101280700",
    "佛山": "101280800",
    "昆明": "101290100",
    "贵阳": "101260100",
    "太原": "101100100",
    "南昌": "101240100",
    "南宁": "101300100",
    "石家庄": "101090100",
    "哈尔滨": "101050100",
    "长春": "101060100",
    "沈阳": "101070100",
    "海口": "101310100",
    "兰州": "101160100",
    "乌鲁木齐": "101130100",
    "无锡": "101190200",
    "常州": "101191100",
    "温州": "101210700",
    "惠州": "101280300",
}

SALARY_CODES = {
    "3K以下": "401",
    "3-5K": "402",
    "5-10K": "403",
    "10-15K": "404",
    "10-20K": "405",
    "20-50K": "406",
    "50K以上": "407",
}

EXPERIENCE_CODES = {
    "应届": "108",
    "1年以内": "101",
    "1-3年": "103",
    "3-5年": "104",
    "5-10年": "105",
    "10年以上": "106",
}

EDUCATION_CODES = {
    "大专": "202",
    "本科": "203",
    "硕士": "204",
    "博士": "205",
}

SCALE_CODES = {
    "0-20人": "301",
    "20-99人": "302",
    "100-499人": "303",
    "500-999人": "304",
    "1000-9999人": "305",
    "10000人以上": "306",
}

INDUSTRY_CODES = {
    "不限": "0",
    "互联网": "100020",
    "电子商务": "100021",
    "游戏": "100024",
    "软件/信息服务": "100032",
    "人工智能": "100901",
    "大数据": "100902",
    "云计算": "100903",
    "区块链": "100904",
    "物联网": "100905",
    "金融": "100101",
    "银行": "100102",
    "保险": "100103",
    "证券/基金": "100104",
    "教育培训": "100200",
    "医疗健康": "100300",
    "房地产": "100400",
    "汽车": "100500",
    "物流/运输": "100600",
    "广告/传媒": "100700",
    "消费品": "100800",
    "制造业": "101000",
    "能源/环保": "101100",
    "政府/非营利": "101200",
    "农业": "101300",
}

STAGE_CODES = {
    "不限": "0",
    "未融资": "801",
    "天使轮": "802",
    "A轮": "803",
    "B轮": "804",
    "C轮": "805",
    "D轮及以上": "806",
    "已上市": "807",
    "不需要融资": "808",
}

JOB_TYPE_CODES = {
    "全职": "1901",
    "兼职": "1903",
    "实习": "1903",
}


def normalize_job(raw: dict[str, Any]) -> dict[str, Any]:
    job_id = str(raw.get("encryptJobId") or "")
    security_id = str(raw.get("securityId") or "") or None
    return {
        "job_id": job_id,
        "security_id": security_id,
        "title": str(raw.get("jobName") or ""),
        "company": str(raw.get("brandName") or ""),
        "city": raw.get("cityName"),
        "salary": raw.get("salaryDesc"),
        "experience": raw.get("jobExperience"),
        "job_url": raw.get("jobUrl") or build_job_url(job_id, security_id),
        "raw_payload": raw,
    }


def normalize_job_detail(raw: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(raw)
    zp_data = payload.get("zpData") if isinstance(payload.get("zpData"), dict) else {}
    job_info = dict(zp_data.get("jobInfo") or {})
    brand_info = dict(zp_data.get("brandComInfo") or {})
    boss_info = dict(zp_data.get("bossInfo") or {})
    fallback = dict(fallback or {})

    job_id = str(job_info.get("encryptId") or fallback.get("job_id") or "")
    security_id = str(job_info.get("securityId") or fallback.get("security_id") or "") or None
    job_url = build_job_url(job_id, security_id) or fallback.get("job_url")

    job = {
        "job_id": job_id,
        "security_id": security_id,
        "title": str(job_info.get("jobName") or fallback.get("title") or ""),
        "salary": str(job_info.get("salaryDesc") or fallback.get("salary") or "") or None,
        "experience": str(job_info.get("experienceName") or job_info.get("jobExperience") or fallback.get("experience") or "") or None,
        "degree": str(job_info.get("degreeName") or job_info.get("jobDegree") or "") or None,
        "city": str(job_info.get("locationName") or fallback.get("city") or "") or None,
        "address": str(job_info.get("address") or "") or None,
        "skills": list(job_info.get("showSkills") or job_info.get("skills") or []),
        "description": str(job_info.get("postDescription") or job_info.get("description") or "") or None,
        "status": str(job_info.get("jobStatusDesc") or "") or None,
        "job_url": job_url,
    }
    company = {
        "name": str(brand_info.get("brandName") or fallback.get("company") or ""),
        "stage": str(brand_info.get("stageName") or brand_info.get("brandStageName") or "") or None,
        "scale": str(brand_info.get("scaleName") or brand_info.get("brandScaleName") or "") or None,
        "industry": str(brand_info.get("industryName") or brand_info.get("brandIndustry") or "") or None,
        "intro": str(brand_info.get("introduce") or brand_info.get("companyDesc") or "") or None,
    }
    boss = {
        "name": str(boss_info.get("name") or boss_info.get("bossName") or "") or None,
        "title": str(boss_info.get("title") or boss_info.get("bossTitle") or "") or None,
    }

    detail_text_parts = []
    for label, value in [
        ("职位名称", job.get("title")),
        ("薪资", job.get("salary")),
        ("经验", job.get("experience")),
        ("学历", job.get("degree")),
        ("城市", job.get("city")),
        ("地址", job.get("address")),
        ("职位状态", job.get("status")),
        ("技能", "、".join(job["skills"]) if job["skills"] else None),
        ("公司", company.get("name")),
        ("公司阶段", company.get("stage")),
        ("公司规模", company.get("scale")),
        ("行业", company.get("industry")),
        ("BOSS", boss.get("name")),
        ("BOSS 职位", boss.get("title")),
        ("职位描述", job.get("description")),
        ("公司介绍", company.get("intro")),
    ]:
        if value:
            detail_text_parts.append(f"{label}：{value}")

    return {
        "job_id": job_id,
        "security_id": security_id,
        "job_url": job_url,
        "detail_payload": {
            "job": job,
            "company": company,
            "boss": boss,
            "raw_payload": payload,
        },
        "detail_text": "\n".join(detail_text_parts),
        "detail_raw_payload": payload,
    }
