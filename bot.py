import os
import json
import time
import secrets
import hashlib
import base64
import urllib.parse
from datetime import datetime, timezone

import requests
import jwt
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles


# ============================================================
# APPLICATION CONFIGURATION
# ============================================================

APP_NAME = "Ayush AI"

PUBLIC_BOT_URL = "https://t.me/ayush2026bot"

ODIA_GROUP_URL = "https://t.me/+lpNB4X_cNtljOGRl"

INTERNATIONAL_GROUP_URL = "https://t.me/+coEwfRzFRmgxYTM1"


# ============================================================
# SERVER-SYNCHRONIZED HOURLY WALLPAPERS
# ============================================================
#
# IMPORTANT:
# The server decides which wallpaper is active.
#
# Therefore:
#
#   User A  ─┐
#   User B  ─┼──> same server hour ──> same wallpaper
#   User C  ─┘
#
# The wallpaper changes once every hour.
#
# The browser periodically asks /api/wallpaper so an
# already-open page also changes automatically.
# ============================================================

WALLPAPERS = [
    {
        "name": "Mountain Landscape",
        "url": (
            "https://images.unsplash.com/"
            "photo-1500534623283-312aade485b7"
            "?auto=format&fit=crop&w=2400&q=90"
        ),
    },
    {
        "name": "Forest Morning",
        "url": (
            "https://images.unsplash.com/"
            "photo-1470770841072-f978cf4d019e"
            "?auto=format&fit=crop&w=2400&q=90"
        ),
    },
    {
        "name": "Forest Light",
        "url": (
            "https://images.unsplash.com/"
            "photo-1441974231531-c6227db76b6e"
            "?auto=format&fit=crop&w=2400&q=90"
        ),
    },
    {
        "name": "Ocean Horizon",
        "url": (
            "https://images.unsplash.com/"
            "photo-1507525428034-b723cf961d3e"
            "?auto=format&fit=crop&w=2400&q=90"
        ),
    },
    {
        "name": "Mountain Valley",
        "url": (
            "https://images.unsplash.com/"
            "photo-1469474968028-56623f02e42e"
            "?auto=format&fit=crop&w=2400&q=90"
        ),
    },
    {
        "name": "Green Hills",
        "url": (
            "https://images.unsplash.com/"
            "photo-1472214103451-9374bd1c798e"
            "?auto=format&fit=crop&w=2400&q=90"
        ),
    },
    {
        "name": "Nature Landscape",
        "url": (
            "https://images.unsplash.com/"
            "photo-1511497584788-876760111969"
            "?auto=format&fit=crop&w=2400&q=90"
        ),
    },
    {
        "name": "Snow Mountains",
        "url": (
            "https://images.unsplash.com/"
            "photo-1519681393784-d120267933ba"
            "?auto=format&fit=crop&w=2400&q=90"
        ),
    },
    {
        "name": "Open Landscape",
        "url": (
            "https://images.unsplash.com/"
            "photo-1500530855697-b586d89ba3ee"
            "?auto=format&fit=crop&w=2400&q=90"
        ),
    },
]


def current_wallpaper():
    """
    Return the wallpaper selected by the server for the
    current UTC hour.

    Every visitor receives the same wallpaper during
    the same hour.
    """

    if not WALLPAPERS:
        return {
            "index": 0,
            "name": "Default",
            "url": "",
            "hour": int(time.time() // 3600),
        }

    hour_number = int(time.time() // 3600)

    index = hour_number % len(WALLPAPERS)

    selected = WALLPAPERS[index]

    return {
        "index": index,
        "name": selected["name"],
        "url": selected["url"],
        "hour": hour_number,
    }


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

OWNER_ID = int(
    os.getenv("OWNER_ID", "0") or 0
)

GIST_ID = os.getenv("GIST_ID", "")

GIST_TOKEN = os.getenv("GIST_TOKEN", "")

GIST_FILENAME = os.getenv(
    "GIST_FILENAME",
    "ayush_stats.json"
)

ACCESS_FILENAME = os.getenv(
    "ACCESS_FILENAME",
    "ayush_access.json"
)


# ============================================================
# TELEGRAM OIDC CONFIGURATION
# ============================================================

TELEGRAM_CLIENT_ID = os.getenv(
    "TELEGRAM_CLIENT_ID",
    ""
)

TELEGRAM_CLIENT_SECRET = os.getenv(
    "TELEGRAM_CLIENT_SECRET",
    ""
)

PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL",
    ""
).rstrip("/")


SESSION_SECRET = (
    os.getenv("SESSION_SECRET")
    or secrets.token_urlsafe(48)
)


COOKIE_SECURE = (
    os.getenv(
        "COOKIE_SECURE",
        "true"
    ).lower()
    == "true"
)


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title=APP_NAME
)


app.add_middleware(
    SessionMiddleware,

    secret_key=SESSION_SECRET,

    max_age=60 * 60 * 8,

    same_site="lax",

    https_only=COOKIE_SECURE,
)


# ============================================================
# STATIC FILES AND TEMPLATES
# ============================================================

app.mount(
    "/static",
    StaticFiles(
        directory="static"
    ),
    name="static",
)


templates = Jinja2Templates(
    directory="templates"
)


# ============================================================
# TELEGRAM OIDC ENDPOINTS
# ============================================================

TELEGRAM_ISSUER = (
    "https://oauth.telegram.org"
)

TELEGRAM_AUTH_URL = (
    f"{TELEGRAM_ISSUER}/auth"
)

TELEGRAM_TOKEN_URL = (
    f"{TELEGRAM_ISSUER}/token"
)

TELEGRAM_JWKS_URL = (
    f"{TELEGRAM_ISSUER}/.well-known/jwks.json"
)


# ============================================================
# TIME
# ============================================================

def now_utc():
    return datetime.now(timezone.utc)


# ============================================================
# OIDC CALLBACK URL
# ============================================================

def callback_url(request: Request):

    if PUBLIC_BASE_URL:

        return (
            f"{PUBLIC_BASE_URL}"
            "/auth/callback"
        )

    return (
        str(request.base_url).rstrip("/")
        + "/auth/callback"
    )


# ============================================================
# CONFIGURATION VALIDATION
# ============================================================

def require_config():

    missing = []

    values = {

        "TELEGRAM_CLIENT_ID":
            TELEGRAM_CLIENT_ID,

        "TELEGRAM_CLIENT_SECRET":
            TELEGRAM_CLIENT_SECRET,

        "PUBLIC_BASE_URL":
            PUBLIC_BASE_URL,

        "OWNER_ID":
            str(OWNER_ID or ""),

        "GIST_ID":
            GIST_ID,

        "GIST_TOKEN":
            GIST_TOKEN,

        "BOT_TOKEN":
            BOT_TOKEN,
    }


    for key, value in values.items():

        if not value:

            missing.append(key)


    if missing:

        raise RuntimeError(
            "Missing dashboard configuration: "
            + ", ".join(missing)
        )


# ============================================================
# PKCE
# ============================================================

def pkce_pair():

    verifier = secrets.token_urlsafe(64)

    digest = hashlib.sha256(
        verifier.encode()
    ).digest()

    challenge = (
        base64.urlsafe_b64encode(
            digest
        )
        .rstrip(b"=")
        .decode()
    )

    return verifier, challenge


# ============================================================
# GIST HEADERS
# ============================================================

def gist_headers():

    return {

        "Authorization":
            f"Bearer {GIST_TOKEN}",

        "Accept":
            "application/vnd.github+json",
    }


# ============================================================
# GET GIST
# ============================================================

def get_gist():

    response = requests.get(

        f"https://api.github.com/gists/"
        f"{GIST_ID}",

        headers=gist_headers(),

        timeout=10,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# READ FILE FROM GIST
# ============================================================

def read_gist_file(
    filename,
    default
):

    try:

        gist = get_gist()

        item = (
            gist
            .get("files", {})
            .get(filename)
        )


        if not item:

            return default


        content = (
            item
            .get("content", "")
            or "{}"
        )


        return json.loads(content)


    except Exception:

        return default


# ============================================================
# PATCH GIST FILES
# ============================================================

def patch_gist_files(files):

    payload = {

        "files": {

            name: {
                "content":
                    json.dumps(
                        value,
                        indent=2
                    )
            }

            for name, value
            in files.items()
        }
    }


    response = requests.patch(

        f"https://api.github.com/gists/"
        f"{GIST_ID}",

        headers={
            **gist_headers(),

            "Content-Type":
                "application/json",
        },

        json=payload,

        timeout=10,
    )


    response.raise_for_status()

    return response.json()


# ============================================================
# ACCESS MANAGEMENT
# ============================================================

def load_access():

    default = {

        "owner_id":
            OWNER_ID,

        "sudo_ids":
            [],

        "audit":
            [],
    }


    data = read_gist_file(
        ACCESS_FILENAME,
        default
    )


    if not isinstance(
        data,
        dict
    ):

        data = default


    data.setdefault(
        "owner_id",
        OWNER_ID
    )


    data.setdefault(
        "sudo_ids",
        []
    )


    data.setdefault(
        "audit",
        []
    )


    cleaned = []


    for value in data["sudo_ids"]:

        try:

            number = int(value)


            if number != OWNER_ID:

                cleaned.append(number)


        except (
            TypeError,
            ValueError
        ):

            pass


    data["sudo_ids"] = sorted(
        set(cleaned)
    )


    return data


# ============================================================
# SAVE ACCESS
# ============================================================

def save_access(data):

    patch_gist_files(
        {
            ACCESS_FILENAME:
                data
        }
    )


# ============================================================
# AUTHORIZATION CHECK
# ============================================================

def is_allowed(user_id):

    access = load_access()

    sudo_ids = set(
        access["sudo_ids"]
    )


    return (

        int(user_id) == OWNER_ID

        or

        int(user_id) in sudo_ids
    )


# ============================================================
# CURRENT SESSION USER
# ============================================================

def current_user(request: Request):

    return request.session.get(
        "telegram_user"
    )


# ============================================================
# ADMIN AUTHORIZATION
# ============================================================

def admin_required(
    request: Request
):

    user = current_user(request)


    if not user:

        raise HTTPException(
            status_code=403,
            detail="Invalid credentials"
        )


    if not is_allowed(
        int(user["id"])
    ):

        request.session.clear()

        raise HTTPException(
            status_code=403,
            detail="Invalid credentials"
        )


    return user


# ============================================================
# OWNER SECURITY REPORT
# ============================================================

def send_owner_security_report(
    user,
    request,
    reason
):

    if not BOT_TOKEN or not OWNER_ID:

        return


    ip = (
        request.client.host
        if request.client
        else "unknown"
    )


    username = (
        user.get("username")
        or "none"
    )


    name = (
        user.get("name")
        or "unknown"
    )


    message = (

        "🚨 DASHBOARD SECURITY ALERT\n\n"

        f"Reason: {reason}\n"

        f"Telegram ID: "
        f"{user.get('id', 'unknown')}\n"

        f"Name: {name}\n"

        f"Username: @{username}\n"

        f"IP: {ip}\n"

        f"Time: "
        f"{now_utc().strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )


    try:

        requests.post(

            f"https://api.telegram.org/"
            f"bot{BOT_TOKEN}/sendMessage",

            json={

                "chat_id":
                    OWNER_ID,

                "text":
                    message,
            },

            timeout=8,
        )


    except Exception:

        pass


# ============================================================
# LOGIN FAILURE AUDIT
# ============================================================

def report_login_failure(
    user,
    request
):

    access = load_access()


    access["audit"].append(

        {

            "event":
                "invalid_login",

            "user_id":
                int(
                    user.get(
                        "id",
                        0
                    )
                ),

            "username":
                user.get(
                    "username"
                ),

            "name":
                user.get(
                    "name"
                ),

            "ip":
                (
                    request.client.host
                    if request.client
                    else "unknown"
                ),

            "time":
                now_utc().isoformat(),
        }
    )


    access["audit"] = (
        access["audit"][-200:]
    )


    try:

        save_access(access)

    except Exception:

        pass


    send_owner_security_report(

        user,

        request,

        "Unauthorized Telegram login attempt"
    )


# ============================================================
# BUILD TELEGRAM LOGIN URL
# ============================================================

def build_login_url(
    request: Request
):

    require_config()


    state = secrets.token_urlsafe(
        32
    )


    verifier, challenge = pkce_pair()


    nonce = secrets.token_urlsafe(
        32
    )


    request.session[
        "oidc_state"
    ] = state


    request.session[
        "pkce_verifier"
    ] = verifier


    request.session[
        "oidc_nonce"
    ] = nonce


    params = {

        "client_id":
            TELEGRAM_CLIENT_ID,

        "redirect_uri":
            callback_url(request),

        "response_type":
            "code",

        "scope":
            "openid profile",

        "state":
            state,

        "nonce":
            nonce,

        "code_challenge":
            challenge,

        "code_challenge_method":
            "S256",
    }


    return (
        TELEGRAM_AUTH_URL
        + "?"
        + urllib.parse.urlencode(
            params
        )
    )


# ============================================================
# VERIFY TELEGRAM ID TOKEN
# ============================================================

def verify_id_token(
    id_token,
    nonce
):
    """
    Verify Telegram's OIDC ID token using Telegram's published JWKS.

    The token is validated for:
      - signature
      - issuer
      - audience / client ID
      - expiration
      - issued-at
      - subject
      - nonce (when supplied)
    """

    if not id_token:
        raise ValueError("Telegram token response did not contain id_token")

    jwks_response = requests.get(
        TELEGRAM_JWKS_URL,
        timeout=10,
    )
    jwks_response.raise_for_status()
    jwks = jwks_response.json()

    header = jwt.get_unverified_header(id_token)
    kid = header.get("kid")

    if not kid:
        raise ValueError("Telegram ID token has no kid header")

    jwk = next(
        (
            item
            for item in jwks.get("keys", [])
            if item.get("kid") == kid
        ),
        None,
    )

    if not jwk:
        raise ValueError(
            f"Unknown Telegram signing key: {kid}"
        )

    # PyJWT expects a cryptographic key object for JWK verification.
    signing_key = jwt.PyJWK.from_dict(jwk).key

    algorithms = []
    token_algorithm = header.get("alg")

    if token_algorithm:
        algorithms.append(token_algorithm)

    # Telegram currently documents RS256 as the default signing
    # algorithm and may expose other compatible keys through JWKS.
    for algorithm in ("RS256", "ES256"):
        if algorithm not in algorithms:
            algorithms.append(algorithm)

    claims = jwt.decode(
        id_token,
        signing_key,
        algorithms=algorithms,
        audience=str(TELEGRAM_CLIENT_ID),
        issuer=TELEGRAM_ISSUER,
        options={
            "require": [
                "iss",
                "aud",
                "exp",
                "iat",
                "sub",
            ]
        },
    )

    if (
        nonce
        and claims.get("nonce") != nonce
    ):
        raise ValueError("Invalid Telegram OIDC nonce")

    return claims


# ============================================================
# NORMALIZE TELEGRAM USER
# ============================================================

def normalize_user(
    claims
):

    user_id = int(

        claims.get("sub")
        or claims.get("id")
    )


    return {

        "id":
            user_id,

        "name":
            (
                claims.get("name")
                or
                claims.get(
                    "preferred_username"
                )
                or
                str(user_id)
            ),

        "username":
            claims.get(
                "preferred_username"
            ),

        "picture":
            claims.get(
                "picture"
            ),
    }


# ============================================================
# PUBLIC HOME
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse
)
def public_home(
    request: Request
):

    error = request.query_params.get(
        "error"
    )


    wallpaper = current_wallpaper()


    return templates.TemplateResponse(

        "index.html",

        {

            "request":
                request,

            "bot_url":
                PUBLIC_BOT_URL,

            "odia_url":
                ODIA_GROUP_URL,

            "international_url":
                INTERNATIONAL_GROUP_URL,

            "error":
                error,

            "wallpaper":
                wallpaper,
        }
    )


# ============================================================
# LOGIN
# ============================================================

@app.get("/login")
def login(
    request: Request
):

    try:

        return RedirectResponse(

            build_login_url(
                request
            ),

            status_code=302
        )


    except RuntimeError as exc:

        return HTMLResponse(

            f"<h2>Dashboard setup required</h2>"
            f"<pre>{exc}</pre>",

            status_code=500
        )


# ============================================================
# TELEGRAM OIDC CALLBACK
# ============================================================

@app.get("/auth/callback")
def auth_callback(

    request: Request,

    code: str = "",

    state: str = ""
):

    expected_state = (
        request.session.pop(
            "oidc_state",
            None
        )
    )


    verifier = (
        request.session.pop(
            "pkce_verifier",
            None
        )
    )


    nonce = (
        request.session.pop(
            "oidc_nonce",
            None
        )
    )


    if (

        not code

        or not state

        or not expected_state

        or not secrets.compare_digest(
            state,
            expected_state
        )

    ):

        try:
            send_owner_security_report(
                {
                    "id": OWNER_ID,
                    "name": "Dashboard OIDC",
                    "username": None,
                },
                request,
                "Invalid Telegram OIDC state/code request",
            )
        except Exception:
            pass

        return RedirectResponse(
            "/?error=invalid_auth_request",
            status_code=302,
        )


    try:

        basic = base64.b64encode(

            (
                f"{TELEGRAM_CLIENT_ID}:"
                f"{TELEGRAM_CLIENT_SECRET}"
            ).encode()

        ).decode()


        response = requests.post(

            TELEGRAM_TOKEN_URL,

            headers={

                "Authorization":
                    f"Basic {basic}",

                "Content-Type":
                    "application/x-www-form-urlencoded",
            },

            data={

                "grant_type":
                    "authorization_code",

                "code":
                    code,

                "redirect_uri":
                    callback_url(request),

                "client_id":
                    TELEGRAM_CLIENT_ID,

                "code_verifier":
                    verifier,
            },

            timeout=10,
        )


        response.raise_for_status()

        token_data = response.json()

        if not isinstance(token_data, dict):
            raise ValueError(
                "Telegram token endpoint returned invalid JSON"
            )

        if token_data.get("error"):
            raise ValueError(
                "Telegram token exchange failed: "
                + str(token_data.get("error"))
                + (
                    ": " + str(token_data.get("error_description"))
                    if token_data.get("error_description")
                    else ""
                )
            )

        if not token_data.get("id_token"):
            raise ValueError(
                "Telegram token response did not contain id_token"
            )

        claims = verify_id_token(
            token_data["id_token"],
            nonce
        )


        user = normalize_user(
            claims
        )


        if not is_allowed(
            user["id"]
        ):

            report_login_failure(
                user,
                request
            )


            return RedirectResponse(

                "/?error=invalid_credentials",

                status_code=302
            )


        request.session[
            "telegram_user"
        ] = user


        return RedirectResponse(

            "/admin",

            status_code=302
        )


    except Exception as exc:
        # Never expose OAuth tokens, client secrets, or stack traces
        # to the browser. Keep the public message generic.
        try:
            send_owner_security_report(
                {
                    "id": OWNER_ID,
                    "name": "Dashboard OIDC",
                    "username": None,
                },
                request,
                f"Telegram authentication failed: {type(exc).__name__}: {exc}",
            )
        except Exception:
            pass

        return RedirectResponse(
            "/?error=authentication_failed",
            status_code=302,
        )


# ============================================================
# LOGOUT
# ============================================================

@app.get("/logout")
def logout(
    request: Request
):

    request.session.clear()

    return RedirectResponse(
        "/",
        status_code=302
    )


# ============================================================
# ADMIN PAGE
# ============================================================

@app.get(
    "/admin",
    response_class=HTMLResponse
)
def admin(
    request: Request
):

    user = admin_required(
        request
    )


    access = load_access()


    stats = read_gist_file(

        GIST_FILENAME,

        {}
    )


    wallpaper = current_wallpaper()


    is_owner = (
        int(user["id"])
        == OWNER_ID
    )


    return templates.TemplateResponse(

        "admin.html",

        {

            "request":
                request,

            "user":
                user,

            "stats":
                stats,

            "access":
                access,

            "is_owner":
                is_owner,

            "role":
                (
                    "owner"
                    if is_owner
                    else "sudo"
                ),

            "wallpaper":
                wallpaper,
        }
    )


# ============================================================
# WALLPAPER API
# ============================================================

@app.get("/api/wallpaper")
def wallpaper_api():

    return JSONResponse(
        current_wallpaper()
    )


# ============================================================
# DASHBOARD API
# ============================================================

@app.get("/api/dashboard")
def dashboard_api(
    request: Request
):

    user = admin_required(
        request
    )


    stats = read_gist_file(

        GIST_FILENAME,

        {}
    )


    if not isinstance(
        stats,
        dict
    ):

        stats = {}


    result = dict(stats)


    is_owner = (
        int(user["id"])
        == OWNER_ID
    )


    result["is_owner"] = (
        is_owner
    )


    result["role"] = (
        "owner"
        if is_owner
        else "sudo"
    )


    result["wallpaper"] = (
        current_wallpaper()
    )


    result["server_time"] = (
        now_utc().isoformat()
    )


    return JSONResponse(
        result
    )


# ============================================================
# ADD SUDO USER
# ============================================================

@app.post("/api/sudo/add")
def add_sudo(

    request: Request,

    telegram_id: str = Form(...)
):

    user = admin_required(
        request
    )


    if int(user["id"]) != OWNER_ID:

        raise HTTPException(

            status_code=403,

            detail="Owner only"
        )


    if not telegram_id.strip().isdigit():

        raise HTTPException(

            status_code=400,

            detail=(
                "Telegram ID must be numeric"
            )
        )


    target = int(
        telegram_id.strip()
    )


    if target == OWNER_ID:

        raise HTTPException(

            status_code=400,

            detail=(
                "Owner is already authorized"
            )
        )


    access = load_access()


    if target not in access["sudo_ids"]:

        access["sudo_ids"].append(
            target
        )


        access["sudo_ids"] = sorted(
            set(access["sudo_ids"])
        )


        access["audit"].append(

            {

                "event":
                    "sudo_added",

                "by":
                    int(user["id"]),

                "target":
                    target,

                "time":
                    now_utc().isoformat(),
            }
        )


        access["audit"] = (
            access["audit"][-200:]
        )


        save_access(
            access
        )


    return RedirectResponse(

        "/admin#security",

        status_code=303
    )


# ============================================================
# REMOVE SUDO USER
# ============================================================

@app.post("/api/sudo/remove")
def remove_sudo(

    request: Request,

    telegram_id: str = Form(...)
):

    user = admin_required(
        request
    )


    if int(user["id"]) != OWNER_ID:

        raise HTTPException(

            status_code=403,

            detail="Owner only"
        )


    if not telegram_id.strip().isdigit():

        raise HTTPException(

            status_code=400,

            detail="Invalid Telegram ID"
        )


    target = int(
        telegram_id.strip()
    )


    access = load_access()


    access["sudo_ids"] = [

        x

        for x in access["sudo_ids"]

        if int(x) != target
    ]


    access["audit"].append(

        {

            "event":
                "sudo_removed",

            "by":
                int(user["id"]),

            "target":
                target,

            "time":
                now_utc().isoformat(),
        }
    )


    access["audit"] = (
        access["audit"][-200:]
    )


    save_access(
        access
    )


    return RedirectResponse(

        "/admin#security",

        status_code=303
    )
