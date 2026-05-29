from bson import ObjectId

from job_buddy.models import JobLead


def test_document_model_round_trip():
    source = {
        "_id": ObjectId(),
        "source_job_id": "job-1",
        "title": "Python Backend",
        "company": "Demo Tech",
    }

    model = JobLead.from_mongo(source)

    assert model.id is not None
    assert model.to_mongo()["title"] == "Python Backend"
