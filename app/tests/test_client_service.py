from sqlalchemy.orm import Session

import pytest

from app.services.client_service import ValidationError, create_client, get_client, list_clients, update_client


def test_create_client_requires_name(db_session: Session) -> None:
    with pytest.raises(ValidationError):
        create_client(db_session, name="   ")


def test_create_and_get_client(db_session: Session) -> None:
    client = create_client(
        db_session, name="Acme Developers", contact_email="ops@acme.test", contact_phone="+971-000"
    )
    db_session.commit()

    fetched = get_client(db_session, client.id)
    assert fetched is not None
    assert fetched.name == "Acme Developers"
    assert fetched.contact_email == "ops@acme.test"


def test_update_client(db_session: Session) -> None:
    client = create_client(db_session, name="Acme Developers")
    db_session.commit()

    update_client(db_session, client, name="Acme Developers LLC", contact_name="Jane Doe")
    db_session.commit()

    assert client.name == "Acme Developers LLC"
    assert client.contact_name == "Jane Doe"


def test_update_client_requires_name(db_session: Session) -> None:
    client = create_client(db_session, name="Acme Developers")
    db_session.commit()

    with pytest.raises(ValidationError):
        update_client(db_session, client, name="")


def test_list_clients_search(db_session: Session) -> None:
    create_client(db_session, name="Acme Developers")
    create_client(db_session, name="Beta Holdings")
    db_session.commit()

    results = list_clients(db_session, search="acme")
    assert [c.name for c in results] == ["Acme Developers"]


def test_list_clients_excludes_soft_deleted(db_session: Session) -> None:
    client = create_client(db_session, name="Acme Developers")
    db_session.commit()
    client.is_deleted = True
    db_session.commit()

    assert list_clients(db_session) == []
    assert get_client(db_session, client.id) is None
