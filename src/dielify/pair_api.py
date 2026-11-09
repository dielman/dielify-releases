"""/api/pair/*: a TV signs in with a QR code that a parent's phone (or the PC app) approves.
See pairing.py for the flow and why the QR code alone grants nothing."""
from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from . import auth, pairing
from .custom_api import Session, _client, session

router = APIRouter(prefix="/api/pair", tags=["pairing"])
LINK = "dielify://pair/"


class PairStartIn(BaseModel):
    device_name: str = Field("TV", max_length=60, description="Shown to the person approving, e.g. 'Shed TV'")


class PairStart(BaseModel):
    secret: str = Field(description="Only the TV keeps this; it collects its key with it")
    code: str = Field(description="Short code shown on the TV, e.g. KDW7-RT3P")
    link: str = Field(description="What the QR code holds: dielify://pair/<code>")
    expires_in: int


class PollIn(BaseModel):
    secret: str = Field(max_length=200)


class PairStatus(BaseModel):
    status: Literal["waiting", "approved", "refused", "expired"]
    token: str | None = Field(None, description="The TV's device key, given once when approved")
    device_id: int | None = None
    username: str | None = None
    profile: str | None = None


class PairPerson(BaseModel):
    name: str
    role: str
    can_sign_in: bool = Field(description="False when the person has no phone login yet")


class PairInfo(BaseModel):
    code: str
    device_name: str
    address: str
    expires_in: int
    people: list[PairPerson]
    suggested: str | None = Field(None, description="The person to pick first (whoever is approving)")


class ApproveIn(BaseModel):
    person: str = Field(max_length=64)


class Approved(BaseModel):
    device_name: str
    person: str


def _fail(e: pairing.PairError):
    raise HTTPException(e.code, str(e)) from e


@router.post("/start", response_model=PairStart)
def pair_start(body: PairStartIn, request: Request) -> PairStart:
    """The TV asks to be paired (no sign-in needed). Show `link` as a QR code and `code` as text."""
    try:
        secret, p = pairing.start(body.device_name, _client(request))
    except pairing.PairError as e:
        _fail(e)
    return PairStart(secret=secret, code=p.code, link=LINK + p.code, expires_in=pairing.PAIR_TTL_S)


@router.post("/poll", response_model=PairStatus)
def pair_poll(body: PollIn) -> PairStatus:
    """The TV checking (every 2 s or so). When approved the key comes back once."""
    p = pairing.poll(body.secret)
    if p is None:
        return PairStatus(status="expired")
    if p.status == "approved" and p.token:
        return PairStatus(status="approved", token=p.token, device_id=p.device_id, username=p.username,
                          profile=p.profile)
    return PairStatus(status="refused" if p.status == "refused" else "waiting")


def _approver(s: Session) -> None:
    if not s.desktop and s.lib.role != "parent":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ask a parent to sign the TV in")


def _household(s: Session) -> list[dict]:
    from .library import people
    return [p for p in people() if p["store"] == s.lib.store]


def _login_for(person: str) -> auth.ServerUser | None:
    """The phone login the TV's key belongs to: the one named after the person, else their first."""
    logins = sorted((u for u in auth.list_users() if u.profile.lower() == person.lower()), key=lambda u: u.name)
    return next((u for u in logins if u.name.lower() == person.lower()), logins[0] if logins else None)


@router.get("/{code}", response_model=PairInfo)
def pair_info(code: str, s: Session = Depends(session)) -> PairInfo:
    """What the phone shows before Allow: the TV's name and address, and who it could be for."""
    _approver(s)
    try:
        p = pairing.find(code)
    except pairing.PairError as e:
        _fail(e)
    people = [PairPerson(name=x["profile"], role=x["role"], can_sign_in=_login_for(x["profile"]) is not None)
              for x in _household(s)]
    return PairInfo(code=p.code, device_name=p.device_name, address=p.address,
                    expires_in=max(0, int(p.expires_at - time.time())), people=people, suggested=s.lib.profile)


@router.post("/{code}/approve", response_model=Approved)
def pair_approve(code: str, body: ApproveIn, s: Session = Depends(session)) -> Approved:
    """Sign the TV in as `person` (someone in your household)."""
    _approver(s)
    match = next((x["profile"] for x in _household(s) if x["profile"].lower() == body.person.lower()), None)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{body.person} isn't in your household")
    login = _login_for(match)
    if login is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"{match} has no phone login yet. Add one on the PC: Settings > People & phones.")

    def make_token(p: pairing.Pairing):
        device_id, token = auth.create_token(login, p.device_name)
        return device_id, token, login.name, login.profile

    try:
        p = pairing.approve(code, make_token)
    except pairing.PairError as e:
        _fail(e)
    return Approved(device_name=p.device_name, person=match)


@router.post("/{code}/refuse", status_code=204)
def pair_refuse(code: str, s: Session = Depends(session)) -> Response:
    _approver(s)
    pairing.refuse(code)
    return Response(status_code=204)
