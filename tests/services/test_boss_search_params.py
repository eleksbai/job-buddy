import pytest

from job_buddy.boss import normalize_search_query


def test_normalize_search_query_accepts_valid_enums():
    result = normalize_search_query(
        {"keywords": ["Python", "FastAPI"], "city": "上海", "page": "2"},
        city_codes={"上海": "101020100"},
        salary_codes={"20-30K": "406"},
        experience_codes={"3-5年": "104"},
        education_codes={"本科": "203"},
        industry_codes={"互联网": "100020"},
        scale_codes={"100-499人": "304"},
        stage_codes={"A轮": "802"},
        job_type_codes={"全职": "1901"},
    )

    assert result["query"] == "Python FastAPI"
    assert result["city"] == "上海"
    assert result["page"] == 2


def test_normalize_search_query_rejects_invalid_enum():
    with pytest.raises(ValueError, match="非法参数 city"):
        normalize_search_query(
            {"keywords": ["Python"], "city": "Shanghai"},
            city_codes={"上海": "101020100"},
            salary_codes={},
            experience_codes={},
            education_codes={},
            industry_codes={},
            scale_codes={},
            stage_codes={},
            job_type_codes={},
        )
