from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette import status

from app.database import get_db
from app.schemas.customer import (
    CustomerOrderCreate,
    CustomerOrderLineCreate,
    CustomerOrderLineUpdate,
    CustomerSessionStateRead,
)
from app.services.customer_order_service import (
    add_customer_order_line,
    create_customer_order,
    delete_customer_order_line,
    get_customer_session_state,
    submit_customer_order,
    update_customer_order_line,
)
from app.services.customer_session_service import resolve_table_qr
from app.templates import templates


router = APIRouter(tags=["Customer Ordering"])


@router.get("/menu/table/{access_token}")
def customer_qr_entry(
    access_token: str,
    db: Session = Depends(get_db),
):
    customer_session = resolve_table_qr(db, access_token)
    return RedirectResponse(
        f"/menu/session/{customer_session.session_token}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/menu/session/{session_token}")
def customer_menu(
    session_token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    state = get_customer_session_state(db, session_token)
    return templates.TemplateResponse(
        request=request,
        name="customer/session_menu.html",
        context={
            "customer_session_token": session_token,
            "customer_state": state.model_dump(mode="json"),
        },
    )


@router.get(
    "/api/customer/sessions/{session_token}",
    response_model=CustomerSessionStateRead,
)
def customer_session_state(
    session_token: str,
    db: Session = Depends(get_db),
):
    return get_customer_session_state(db, session_token)


@router.post(
    "/api/customer/sessions/{session_token}/orders",
    response_model=CustomerSessionStateRead,
    status_code=status.HTTP_201_CREATED,
)
def customer_order_create(
    session_token: str,
    payload: CustomerOrderCreate,
    db: Session = Depends(get_db),
):
    return create_customer_order(db, session_token, payload)


@router.post(
    "/api/customer/sessions/{session_token}/order/lines",
    response_model=CustomerSessionStateRead,
)
def customer_order_line_create(
    session_token: str,
    payload: CustomerOrderLineCreate,
    db: Session = Depends(get_db),
):
    return add_customer_order_line(db, session_token, payload)


@router.patch(
    "/api/customer/sessions/{session_token}/order/lines/{line_id}",
    response_model=CustomerSessionStateRead,
)
def customer_order_line_update(
    session_token: str,
    line_id: int,
    payload: CustomerOrderLineUpdate,
    db: Session = Depends(get_db),
):
    return update_customer_order_line(
        db,
        session_token,
        line_id,
        payload,
    )


@router.delete(
    "/api/customer/sessions/{session_token}/order/lines/{line_id}",
    response_model=CustomerSessionStateRead,
)
def customer_order_line_delete(
    session_token: str,
    line_id: int,
    db: Session = Depends(get_db),
):
    return delete_customer_order_line(
        db,
        session_token,
        line_id,
    )


@router.post(
    "/api/customer/sessions/{session_token}/order/submit",
    response_model=CustomerSessionStateRead,
)
def customer_order_submit(
    session_token: str,
    db: Session = Depends(get_db),
):
    return submit_customer_order(db, session_token)
