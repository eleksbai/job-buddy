from bson import ObjectId

from job_buddy.models import TargetProfile


def test_document_model_round_trip():
    source = {
        "_id": ObjectId(),
        "name": "Python Backend",
        "keywords": ["Python", "FastAPI"],
        "city": "Shanghai",
    }

    model = TargetProfile.from_mongo(source)

    assert model.id is not None
    assert model.to_mongo()["name"] == "Python Backend"
