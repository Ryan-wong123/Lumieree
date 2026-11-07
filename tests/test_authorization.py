from lumieree.extensions import db
from lumieree.models import User


def test_staff_cannot_open_admin_pages(login_as):
    b = login_as("staff")
    for path in ("/admin/dashboard", "/admin/export/visits.csv", "/admin/users", "/admin/users/create"):
        assert b.get(path).status_code == 403, path


def test_admin_can_open_dashboard_but_not_user_management(login_as):
    b = login_as("a")
    assert b.get("/admin/dashboard").status_code == 200
    assert b.get("/admin/users").status_code == 403
    assert b.post("/admin/users/1/delete").status_code == 403


def test_super_admin_manages_users(app, users, login_as):
    b = login_as("root")
    assert b.get("/admin/users").status_code == 200
    resp = b.post(
        "/admin/users/create",
        {"username": "newbie", "password": "a long enough password", "role": "staff", "email": "n@example.com"},
    )
    assert resp.status_code == 302
    created = db.session.execute(db.select(User).where(User.username == "newbie")).scalar_one()
    assert created.must_change_password and created.role == "staff"


def test_super_admin_cannot_be_created_from_the_web(login_as):
    b = login_as("root")
    resp = b.post(
        "/admin/users/create", {"username": "evil", "password": "a long enough password", "role": "super_admin"}
    )
    assert resp.status_code == 400


def test_cannot_demote_or_delete_last_super_admin(app, users, login_as):
    b = login_as("root")
    me = users["root"].id
    resp = b.post(f"/admin/users/{me}/delete")
    assert (
        "cannot delete your own"
        in resp.get_data(
            as_text=True,
        )
        or resp.status_code == 302
    )
    assert db.session.get(User, me) is not None
    resp = b.post(f"/admin/users/{me}/edit", {"role": "staff", "active": "on"}, follow_redirects=True)
    assert "cannot change your own role" in resp.get_data(as_text=True)


def test_deleting_a_user_removes_their_data(app, users, login_as):
    from lumieree.models import Patient

    db.session.add(Patient(owner_id=users["b"].id, name="Someone"))
    db.session.commit()
    b = login_as("root")
    b.post(f"/admin/users/{users['b'].id}/delete")
    assert db.session.execute(db.select(Patient)).first() is None
