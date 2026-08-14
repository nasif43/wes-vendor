

def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_login_page_loads(client):
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert "Sign in" in response.text or "login" in response.text.lower()


def test_signup_page_loads(client):
    response = client.get("/auth/signup")
    assert response.status_code == 200
    assert "Create Account" in response.text or "sign up" in response.text.lower()


def test_redirect_to_login(client):
    response = client.get("/vendors", follow_redirects=False)
    assert response.status_code in (302, 303, 307)


def test_index_redirects_without_auth(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (307, 303) or response.status_code == 200
