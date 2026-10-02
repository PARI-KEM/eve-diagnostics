def test_only_admin_can_create(client, user):
    assert client.post("/centres/", json={"name": "X", "location": "Y"}, headers=user).status_code == 403
    assert client.post("/tests/", json={"name": "X"}, headers=user).status_code == 403


def test_list_get_and_filter(client, catalog):
    centre_id, _ = catalog
    r = client.get("/centres/")
    assert r.status_code == 200 and r.json()["total"] == 1
    c = r.json()["items"][0]
    assert c["tests"][0]["test_name"] == "Lipid Profile" and c["tests"][0]["price"] == "500.00"
    assert client.get(f"/centres/{centre_id}").json()["name"] == "EVE Saket"
    assert client.get("/centres/", params={"location": "delhi"}).json()["total"] == 1
    assert client.get("/centres/", params={"location": "mumbai"}).json()["total"] == 0
    assert client.get("/centres/", params={"test": "lipid"}).json()["total"] == 1
    assert client.get("/centres/", params={"test": "mri"}).json()["total"] == 0


def test_pagination_bounds(client, catalog):
    assert client.get("/centres/", params={"limit": 0}).status_code == 422
    assert client.get("/centres/", params={"limit": 1000}).status_code == 422
    assert client.get("/centres/", params={"offset": 5}).json()["items"] == []


def test_missing_centre_404(client):
    assert client.get("/centres/999").status_code == 404


def test_duplicates_and_bad_price(client, admin, catalog):
    centre_id, test_id = catalog
    assert client.post(f"/centres/{centre_id}/tests", json={"test_id": test_id, "price": "1"}, headers=admin).status_code == 409
    assert client.post(f"/centres/{centre_id}/tests", json={"test_id": test_id, "price": "-5"}, headers=admin).status_code == 422
    assert client.post(f"/centres/{centre_id}/tests", json={"test_id": 999, "price": "5"}, headers=admin).status_code == 404
    assert client.post("/centres/", json={"name": "EVE Saket", "location": "Delhi"}, headers=admin).status_code == 409


def test_price_update_does_not_change_existing_booking(client, admin, booking, user, catalog):
    centre_id, test_id = catalog
    client.put(f"/centres/{centre_id}/tests/{test_id}", json={"price": "999.00"}, headers=admin)
    assert client.get(f"/bookings/{booking['id']}", headers=user).json()["amount"] == "500.00"
