import json

import pytest

from data.demo.dataset import CREATED_AT
from data.demo.errors import DatasetError
from data.demo.load import import_documents, mongo_shell, run_command

pytestmark = pytest.mark.live


def active_counts():
    reply = mongo_shell('const d = db.getSiblingDB("market"); print(JSON.stringify('
                        '[d.sellers.countDocuments({}), d.products.countDocuments({}), d.offers.countDocuments({})]));',
                        run_command)
    return json.loads(reply.strip().splitlines()[-1])


def test_real_validator_rejection_keeps_active_collections_intact():
    before = active_counts()
    common = {"created_at": {"$date": CREATED_AT}, "provenance_kind": "synthetic"}
    documents = {
        "sellers": [common | {"_id": "SELLER_SYN_REJECTION_TEST", "name": "Test"}],
        "products": [common | {"_id": "PRD_REJECTION_TEST", "title": "Test", "category": "books",
                               "seller_id": "SELLER_SYN_REJECTION_TEST", "attributes": {"isbn": "invalid"}}],
        "offers": [],
    }
    with pytest.raises(DatasetError, match=r"products : 1 rejet"):
        import_documents(documents)
    assert active_counts() == before
